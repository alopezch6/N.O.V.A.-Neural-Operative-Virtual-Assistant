"""
NOVA — Telegram Bot
Brain routing: Ollama local (PC encendido) → Gemini 2.0 Flash (siempre disponible, ~1s)
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import base64
import re
import json
import time
import io
import asyncio
import threading
import atexit
import sys
from pathlib import Path
from datetime import datetime, time as dt_time

import pytz
import ollama
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes

import requests as _requests
from orchestration.reporte_diario import enviar_reporte, obtener_audio_texto, get_noticias_cache
from orchestration.daemon_inactividad import enviar_informe_nocturno, iniciar_daemon, registrar_actividad as _registrar_actividad

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_ID,
    SYSTEM_PROMPT,
    OLLAMA_HOST_LOCAL, MODEL_FAST,
    GROQ_API_KEY, GROQ_MODEL,
    MODEL_SMART,
)

_GROQ_FALLBACK_MODEL  = "llama-3.3-70b-versatile"
_GROQ_VISION_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"
_PID_FILE = Path("/tmp/nova_telegram_bot.pid")
from utils.acciones import maybe_handle_action_request
from utils.internet import obtener_info_internet, necesita_internet
from memory.memoria import (
    obtener_contexto_memoria, extraer_y_guardar_memoria, obtener_contexto_cruzado,
    cargar_historial as _cargar_historial_remoto,
    guardar_historial as _guardar_historial_remoto,
)
from agents.explorador import necesita_explorar_nova, obtener_contexto_nova, aprender_todo, cache_info, obtener_resumen_propio

# ── Clientes ─────────────────────────────────────────────────────────────────
_cliente_local  = ollama.Client(host=OLLAMA_HOST_LOCAL, timeout=60.0)
_cliente_ping   = ollama.Client(host=OLLAMA_HOST_LOCAL, timeout=2.0)
_cliente_oracle = ollama.Client(host="http://127.0.0.1:11434", timeout=120.0)
_groq           = Groq(api_key=GROQ_API_KEY)

_local_cache = {"ok": False, "ts": 0.0}

def _local_disponible():
    now = time.time()
    if now - _local_cache["ts"] < 15:
        return _local_cache["ok"]
    try:
        _cliente_ping.list()
        _local_cache["ok"] = True
    except Exception:
        _local_cache["ok"] = False
    _local_cache["ts"] = now
    return _local_cache["ok"]

# ── Historial ─────────────────────────────────────────────────────────────────

def _cargar_historial():
    return _cargar_historial_remoto("telegram")

def _guardar_historial(h):
    _guardar_historial_remoto(h, "telegram")

# ── Utilidades ────────────────────────────────────────────────────────────────
def _obtener_hora():
    now = datetime.now()
    return f"{now.strftime('%A %d de %B de %Y')}, {now.strftime('%H:%M')}"

def _limpiar(texto):
    texto = re.sub(r'<think>.*?</think>', '', texto, flags=re.DOTALL)
    return texto.strip()

def _partir_mensaje(texto, limite=4000):
    if len(texto) <= limite:
        return [texto]
    partes = []
    while texto:
        corte = texto.rfind('\n', 0, limite) if len(texto) > limite else len(texto)
        if corte <= 0:
            corte = limite
        partes.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    return partes

def _quiere_nota_voz(texto: str) -> bool:
    t = texto.lower()
    triggers = (
        "nota de voz",
        "en voz",
        "por voz",
        "en audio",
        "mandamelo en voz",
        "mándamelo en voz",
        "mandamelo por voz",
        "mándamelo por voz",
        "mandame una nota de voz",
        "mándame una nota de voz",
        "respondeme en voz",
        "respóndeme en voz",
        "contesta en voz",
        "contestame en voz",
        "contéstame en voz",
    )
    return any(trigger in t for trigger in triggers)

def _preparar_peticion(texto: str) -> tuple[str, bool]:
    quiere_voz = _quiere_nota_voz(texto)
    if not quiere_voz:
        return texto.strip(), False

    limpio = texto
    patrones = (
        r"\bresp[oó]ndeme en voz\b",
        r"\brespondeme en voz\b",
        r"\bcont[eé]stame en voz\b",
        r"\bcontestame en voz\b",
        r"\bcontesta en voz\b",
        r"\bm[aá]ndamelo en voz\b",
        r"\bmandamelo en voz\b",
        r"\bm[aá]ndamelo por voz\b",
        r"\bmandamelo por voz\b",
        r"\bm[aá]ndame una nota de voz\b",
        r"\bmandame una nota de voz\b",
        r"\bnota de voz\b",
        r"\ben voz\b",
        r"\bpor voz\b",
        r"\ben audio\b",
    )
    for patron in patrones:
        limpio = re.sub(patron, " ", limpio, flags=re.IGNORECASE)
    limpio = re.sub(r"\s+", " ", limpio).strip(" ,.;:-")

    return (limpio or texto.strip()), True

# ── Brain ─────────────────────────────────────────────────────────────────────
def _pensar(mensaje, historial):
    contexto_memoria = obtener_contexto_memoria(mensaje)

    ctx_internet = ""
    if necesita_internet(mensaje):
        info = obtener_info_internet(mensaje)
        if info:
            ctx_internet = (
                f"\n[Información actualizada de internet — leída ahora mismo]:\n{info}\n"
                "[IMPORTANTE: Responde basándote en esta información. No la ignores ni la complementes con suposiciones.]\n"
            )

    ctx_nova = ""
    if necesita_explorar_nova(mensaje):
        codigo = obtener_contexto_nova(mensaje)
        if codigo:
            ctx_nova = (
                f"\n[Código fuente real de NOVA (B:\\NOVA) — leído en este momento]:\n{codigo}\n"
                "\n[IMPORTANTE: Responde ÚNICAMENTE basándote en el código fuente mostrado arriba."
                " No inventes archivos, funciones ni módulos que no aparezcan explícitamente en ese código."
                " Si algo no está en el código proporcionado, dilo.]\n"
            )

    msg_completo = f"[{_obtener_hora()}]{ctx_internet}{ctx_nova}\nAlex dice: {mensaje}"
    historial.append({"role": "user", "content": msg_completo})
    if len(historial) > 20:
        historial = historial[-20:]

    resumen_propio = obtener_resumen_propio()
    bloque_self = (
        f"\n\nAUTOCONOCIMIENTO (generado leyendo mi propio código):\n{resumen_propio}"
        if resumen_propio else
        "\n\nCAPACIDADES PROPIAS:"
        "\n- Tienes acceso de lectura al código fuente de B:\\NOVA en el PC local de Alex via Tailscale."
        "\n- Usa /aprender con el PC encendido para generar tu autoconocimiento."
    )

    ctx_voz = obtener_contexto_cruzado("telegram")
    bloque_voz = f"\n\nCONTEXTO RECIENTE (voz):\n{ctx_voz}" if ctx_voz else ""

    system = (
        SYSTEM_PROMPT
        + f"\n\nMEMORIA PERSISTENTE:\n{contexto_memoria}"
        + bloque_self
        + bloque_voz
        + "\n\nIMPORTANTE: Respondes por Telegram (texto). Puedes usar Markdown y listas."
    )

    # Groq siempre primero; si el modelo intenta usar tools no configuradas → fallback inmediato
    model_activo = GROQ_MODEL
    # Temperatura baja cuando hay código real en contexto: menos creatividad, más precisión
    temperature = 0.15 if (ctx_nova or ctx_internet) else 0.3
    print(f"[TG] [groq/{model_activo}] temp={temperature} {mensaje[:60]}")
    texto = None
    for intento in range(3):
        try:
            respuesta = _groq.chat.completions.create(
                model=model_activo,
                messages=[{"role": "system", "content": system}] + historial,
                max_tokens=1024,
                temperature=temperature,
                timeout=25,
            )
            texto = respuesta.choices[0].message.content.strip()
            break
        except Exception as e:
            err = str(e)
            print(f"[TG] Groq intento {intento + 1}/3 falló: {e}")
            if "tool_use_failed" in err or "called a tool" in err:
                # El modelo intentó usar tools internas que Groq rechaza → cambiar modelo
                print(f"[TG] {model_activo} intentó usar tools → fallback a {_GROQ_FALLBACK_MODEL}")
                model_activo = _GROQ_FALLBACK_MODEL
            elif intento < 2:
                time.sleep(3)
    if not texto:
        raise RuntimeError("Groq no respondió tras 3 intentos.")

    historial.append({"role": "assistant", "content": texto})
    _guardar_historial(historial)

    threading.Thread(
        target=extraer_y_guardar_memoria,
        args=(mensaje, texto, ollama.Client(host="http://100.111.223.84:11434", timeout=120.0)),
        daemon=True,
    ).start()

    return texto, historial

# ── Handlers ──────────────────────────────────────────────────────────────────
_historial_lock = threading.Lock()
_historial: list = _cargar_historial()

def _autorizado(update: Update) -> bool:
    return update.effective_user.id == TELEGRAM_ALLOWED_ID

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    await update.message.reply_text("NOVA online. ¿Qué necesitas, Alex?")

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    global _historial
    with _historial_lock:
        _historial = []
        _guardar_historial(_historial)
    await update.message.reply_text("Historial borrado.")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    local_ok = _local_disponible()
    brain = f"Local ({MODEL_FAST})" if local_ok else f"Groq ({GROQ_MODEL})"
    await update.message.reply_text(
        f"Brain activo: {brain}\nMensajes en historial: {len(_historial)}"
    )

def _leer_noticia_sync(n: int) -> str:
    cache = get_noticias_cache()
    if not cache:
        return "No hay noticias cargadas. Espera al reporte de las 06:45 o usa /reporte."
    if n < 1 or n > len(cache):
        return f"Solo hay {len(cache)} noticias disponibles. Usa un número del 1 al {len(cache)}."

    noticia = cache[n - 1]
    titulo = noticia['titulo']
    url = noticia['url']
    resumen_rss = noticia.get('resumen', '')

    texto_articulo = ""
    try:
        r = _requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        if r.status_code == 200:
            import re as _re, html as _html
            parrafos = _re.findall(r'<p[^>]*>(.*?)</p>', r.text, _re.DOTALL | _re.IGNORECASE)
            texto = ' '.join(
                _re.sub(r'\s+', ' ', _html.unescape(_re.sub(r'<[^>]+>', '', p))).strip()
                for p in parrafos if len(p.strip()) > 50
            )
            if len(texto) > 300:
                texto_articulo = texto[:4000]
    except Exception:
        pass

    contenido = texto_articulo or resumen_rss
    if len(contenido) > 200:
        try:
            resp = _groq.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": (
                    f"Resume esta noticia de Zaragoza en 3-4 párrafos claros y directos. "
                    f"Título: {titulo}\n\nContenido:\n{contenido}"
                )}],
                max_tokens=512,
                temperature=0.3,
            )
            resumen = resp.choices[0].message.content.strip()
            return f"*{titulo}*\n\n{resumen}\n\n[Leer completo]({url})"
        except Exception:
            pass

    return f"*{titulo}*\n\n{contenido or 'Sin contenido disponible.'}\n\n[Ver en Heraldo]({url})"


async def cmd_noticia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Uso: /noticia <número>  (ej: /noticia 2)")
        return
    n = int(context.args[0])
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    loop = asyncio.get_event_loop()
    texto = await loop.run_in_executor(None, _leer_noticia_sync, n)
    for parte in _partir_mensaje(texto):
        await update.message.reply_text(parte, parse_mode="Markdown")


async def cmd_aprender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    loop = asyncio.get_event_loop()
    resultado = await loop.run_in_executor(None, aprender_todo)
    info = cache_info()
    await update.message.reply_text(f"🧠 {resultado}\n\n_{info}_", parse_mode="Markdown")

async def cmd_reporte(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    await enviar_reporte(context)

def _oracle_exec(cmd_key: str) -> str:
    """Ejecuta un comando de diagnóstico en Oracle vía almacen."""
    from config import ALMACEN_URL, ALMACEN_TOKEN
    try:
        r = _requests.post(
            f"{ALMACEN_URL}/diagnostico/exec",
            json={"cmd": cmd_key},
            headers={"X-Nova-Token": ALMACEN_TOKEN},
            timeout=12,
        )
        if r.status_code == 200:
            return r.json().get("output", "(sin salida)")
        return f"Error HTTP {r.status_code}"
    except Exception as e:
        return f"Sin respuesta de Oracle: {e}"


def _pc_health() -> dict:
    """Consulta el /health del PC local vía Tailscale."""
    from config import PC_TAILSCALE_IP
    try:
        r = _requests.get(f"http://{PC_TAILSCALE_IP}:5000/health", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"ok": False, "nova": False, "ollama": False}


def _recopilar_diagnostico() -> str:
    """Recopila estado real de Oracle y PC local. Devuelve texto crudo para el LLM."""
    secciones = []

    for key in ("status-almacen", "status-telegram"):
        out = _oracle_exec(key)
        secciones.append(f"=== {key} ===\n{out[:700]}")

    for key in ("logs-almacen", "logs-telegram"):
        out = _oracle_exec(key)
        secciones.append(f"=== {key} (últimas 30 líneas) ===\n{out[:900]}")

    for key in ("disco", "ram", "uptime", "procesos"):
        out = _oracle_exec(key)
        secciones.append(f"=== {key} ===\n{out[:300]}")

    pc = _pc_health()
    secciones.append(
        "=== PC local (Tailscale) ===\n"
        f"Accesible: {'Sí' if pc.get('ok') else 'NO — PC apagado o Tailscale caído'}\n"
        f"nova.py corriendo: {'Sí' if pc.get('nova') else 'No'}\n"
        f"Ollama local: {'Online' if pc.get('ollama') else 'Offline'}"
    )

    return "\n\n".join(secciones)


def _analizar_diagnostico(raw: str) -> str:
    prompt = (
        "Eres NOVA. Analiza este diagnóstico real de los sistemas y da un informe claro a Alex.\n\n"
        f"{raw}\n\n"
        "Responde con:\n"
        "1. Estado general (todo OK / hay problemas)\n"
        "2. Qué servicios están activos o caídos\n"
        "3. Errores relevantes en logs (si los hay)\n"
        "4. Recursos Oracle (disco, RAM) — avisa si algo está al límite\n"
        "5. Estado del PC local\n"
        "6. Acción recomendada si hay algún problema\n\n"
        "Formato Markdown, directo y sin rodeos."
    )
    resp = _groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=700,
        temperature=0.1,
    )
    return resp.choices[0].message.content.strip()


def _ejecutar_deploy_remoto() -> str:
    """Llama al endpoint /deploy del PC local via Tailscale."""
    from config import PC_TAILSCALE_IP, ALMACEN_TOKEN
    try:
        r = _requests.post(
            f"http://{PC_TAILSCALE_IP}:5000/deploy",
            headers={"X-Nova-Token": ALMACEN_TOKEN},
            timeout=90,
        )
        if r.status_code == 200:
            return r.json().get("resultado", "Deploy completado.")
        return f"Error HTTP {r.status_code} desde el PC local."
    except _requests.exceptions.ConnectionError:
        return "El PC local no está disponible. Enciéndelo e inténtalo de nuevo."
    except Exception as e:
        return f"Error inesperado: {e}"


async def cmd_diagnostico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    msg = await update.message.reply_text("Analizando sistemas... un momento.")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    loop = asyncio.get_event_loop()

    raw     = await loop.run_in_executor(None, _recopilar_diagnostico)
    analisis = await loop.run_in_executor(None, _analizar_diagnostico, raw)

    context.user_data["diag_raw"] = raw

    keyboard = [[
        InlineKeyboardButton("🚀 Deploy ahora",  callback_data="deploy_confirm"),
        InlineKeyboardButton("📋 Ver logs raw",   callback_data="diag_raw"),
    ]]
    await msg.delete()
    await update.message.reply_text(
        analisis,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        return
    keyboard = [[
        InlineKeyboardButton("🚀 Desplegar", callback_data="deploy_confirm"),
        InlineKeyboardButton("❌ Cancelar",  callback_data="deploy_cancel"),
    ]]
    await update.message.reply_text(
        "Sincronizar código del PC local → Oracle y reiniciar servicios?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def callback_diag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != TELEGRAM_ALLOWED_ID:
        await query.answer("Acceso denegado.")
        return
    await query.answer()
    raw = context.user_data.get("diag_raw", "Sin datos. Ejecuta /diagnostico primero.")
    await query.edit_message_reply_markup(reply_markup=None)
    for parte in _partir_mensaje(raw, limite=4000):
        await query.message.reply_text(f"```\n{parte}\n```", parse_mode="Markdown")


async def callback_deploy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != TELEGRAM_ALLOWED_ID:
        await query.answer("Acceso denegado.")
        return
    await query.answer()

    if query.data == "deploy_confirm":
        await query.edit_message_text("Desplegando... un momento.")
        loop = asyncio.get_event_loop()
        resultado = await loop.run_in_executor(None, _ejecutar_deploy_remoto)
        await query.edit_message_text(resultado)
    else:
        await query.edit_message_text("Cancelado.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _autorizado(update):
        await update.message.reply_text("Acceso denegado.")
        return

    texto = update.message.text.strip()
    if not texto:
        return

    _registrar_actividad()

    accion = maybe_handle_action_request(texto, list(_historial))
    if accion and accion.get("handled"):
        reply_text = accion.get("reply", "")
        if reply_text == "__SCREENSHOT__":
            # Recuperar imagen del PC vía Tailscale y enviarla como foto
            from config import PC_TAILSCALE_IP, ALMACEN_TOKEN
            try:
                r = _requests.post(
                    f"http://{PC_TAILSCALE_IP}:5000/pc/screenshot",
                    headers={"X-Nova-Token": ALMACEN_TOKEN},
                    timeout=15,
                )
                if r.status_code == 200:
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=io.BytesIO(r.content),
                        caption="Captura del PC",
                    )
                    return
                else:
                    await update.message.reply_text(f"Error tomando captura: HTTP {r.status_code}")
                    return
            except Exception as e:
                await update.message.reply_text(f"No pude obtener la captura: {e}")
                return
        await update.message.reply_text(reply_text, parse_mode="Markdown")
        return

    texto_limpio, quiere_voz = _preparar_peticion(texto)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    loop = asyncio.get_event_loop()
    global _historial

    def _run():
        with _historial_lock:
            respuesta, h = _pensar(texto_limpio, list(_historial))
            _historial[:] = h
            return respuesta

    try:
        respuesta = await asyncio.wait_for(
            loop.run_in_executor(None, _run),
            timeout=60.0,
        )
        if quiere_voz:
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id,
                    action=ChatAction.RECORD_VOICE,
                )
                audio = await loop.run_in_executor(None, obtener_audio_texto, respuesta)
                if audio:
                    await context.bot.send_voice(
                        chat_id=update.effective_chat.id,
                        voice=io.BytesIO(audio),
                    )
                    return
            except Exception as audio_error:
                print(f"[TG] Audio error: {audio_error}")
        for parte in _partir_mensaje(respuesta):
            await update.message.reply_text(parte)
    except asyncio.TimeoutError:
        print("[TG] TIMEOUT: _pensar tardó más de 60s")
        await update.message.reply_text("Tardé demasiado en responder. Inténtalo de nuevo.")
    except Exception as e:
        print(f"[TG] ERROR: {e}")
        await update.message.reply_text(f"Error: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analiza imágenes enviadas por Telegram usando un modelo de visión de Groq."""
    if not _autorizado(update):
        return
    photo   = update.message.photo[-1]  # mayor resolución
    caption = update.message.caption or "Describe qué ves en esta imagen con detalle."

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    try:
        file_obj  = await context.bot.get_file(photo.file_id)
        img_bytes = await file_obj.download_as_bytearray()
        b64       = base64.b64encode(bytes(img_bytes)).decode()

        loop = asyncio.get_event_loop()

        def _analizar():
            resp = _groq.chat.completions.create(
                model=_GROQ_VISION_MODEL,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": caption},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
                max_tokens=1024,
                temperature=0.2,
            )
            return resp.choices[0].message.content.strip()

        respuesta = await asyncio.wait_for(
            loop.run_in_executor(None, _analizar),
            timeout=30.0,
        )
        for parte in _partir_mensaje(respuesta):
            await update.message.reply_text(parte)

    except asyncio.TimeoutError:
        await update.message.reply_text("Tardé demasiado analizando la imagen.")
    except Exception as e:
        print(f"[TG] Error en handle_photo: {e}")
        await update.message.reply_text(f"Error analizando imagen: {e}")


# ── Jobs de background ────────────────────────────────────────────────────────

async def _check_recordatorios_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ejecutado cada minuto. Envía recordatorios vencidos."""
    try:
        from recordatorios import pendientes_vencidos, marcar_enviado
        for r in pendientes_vencidos():
            await context.bot.send_message(
                chat_id=TELEGRAM_ALLOWED_ID,
                text=f"⏰ Recordatorio [{r['id']}]: {r['mensaje']}",
            )
            marcar_enviado(r["id"])
    except Exception as e:
        print(f"[TG] Error en check_recordatorios: {e}")


async def _sugerir_plugins_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ejecutado cada lunes a las 10:00. Sugiere plugins basados en el historial."""
    try:
        historial = _cargar_historial()
        if len(historial) < 10:
            return
        mensajes = [
            re.sub(r'\[.*?\]\n+Alex dice:\s*', '', m["content"], flags=re.DOTALL).strip()
            for m in historial[-80:] if m["role"] == "user"
        ]
        if len(mensajes) < 5:
            return
        sample = "\n".join(f"- {m[:200]}" for m in mensajes[-30:])
        prompt = (
            "Eres NOVA analizando el historial de Alex para detectar necesidades sin cubrir.\n"
            "Basándote en estas peticiones recientes, sugiere 2-3 plugins nuevos que serían útiles.\n"
            "Para cada uno: nombre corto + qué haría en una línea.\n"
            "No sugieras lo que ya existe (diagnóstico, deploy, procesos, recordatorios, visión).\n\n"
            f"Peticiones recientes:\n{sample}"
        )
        loop = asyncio.get_event_loop()
        def _pedir():
            resp = _groq.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.5,
            )
            return resp.choices[0].message.content.strip()
        sugerencias = await asyncio.wait_for(
            loop.run_in_executor(None, _pedir), timeout=20.0
        )
        await context.bot.send_message(
            chat_id=TELEGRAM_ALLOWED_ID,
            text=f"💡 *Sugerencias de plugins esta semana:*\n\n{sugerencias}\n\n_Di 'añádete una función para...' para que lo implemente._",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[TG] Error en sugerir_plugins_job: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"[TG] Excepción: {context.error}")

# ── Systemd watchdog ──────────────────────────────────────────────────────────
def _start_watchdog():
    import socket as _socket
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    watchdog_usec = os.environ.get("WATCHDOG_USEC")
    if not notify_socket or not watchdog_usec:
        return
    interval = int(watchdog_usec) / 1_000_000 / 2
    def _ping():
        sock_path = notify_socket.lstrip("@")
        while True:
            try:
                with _socket.socket(_socket.AF_UNIX, _socket.SOCK_DGRAM) as s:
                    s.connect(sock_path)
                    s.sendall(b"WATCHDOG=1")
            except Exception:
                pass
            time.sleep(interval)
    threading.Thread(target=_ping, daemon=True).start()
    print(f"[TG] Watchdog activo, ping cada {interval:.0f}s")

# ── Main ──────────────────────────────────────────────────────────────────────
def _acquire_pid_lock():
    if _PID_FILE.exists():
        try:
            old_pid = int(_PID_FILE.read_text().strip())
            os.kill(old_pid, 0)  # lanza OSError si el proceso no existe
            print(f"[TG] Ya hay una instancia corriendo (PID {old_pid}). Saliendo.")
            sys.exit(1)
        except (OSError, ValueError):
            pass  # proceso muerto o PID corrupto → sobreescribir
    _PID_FILE.write_text(str(os.getpid()))
    atexit.register(lambda: _PID_FILE.unlink(missing_ok=True))


def main():
    print("NOVA Telegram Bot — iniciando...")
    _acquire_pid_lock()
    _start_watchdog()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("reset",       cmd_reset))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("aprender",    cmd_aprender))
    app.add_handler(CommandHandler("reporte",     cmd_reporte))
    app.add_handler(CommandHandler("noticia",     cmd_noticia))
    app.add_handler(CommandHandler("deploy",      cmd_deploy))
    app.add_handler(CommandHandler("diagnostico", cmd_diagnostico))
    app.add_handler(CallbackQueryHandler(callback_diag,   pattern="^diag_raw$"))
    app.add_handler(CallbackQueryHandler(callback_deploy, pattern="^deploy_"))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    iniciar_daemon()

    if app.job_queue is not None:
        madrid = pytz.timezone('Europe/Madrid')
        # Reporte diario 07:00
        app.job_queue.run_daily(
            enviar_reporte,
            time=dt_time(7, 0, tzinfo=madrid),
            name="reporte_diario",
        )
        # Informe nocturno 00:00
        app.job_queue.run_daily(
            enviar_informe_nocturno,
            time=dt_time(0, 0, tzinfo=madrid),
            name="informe_nocturno",
        )
        # Recordatorios: cada 60 segundos
        app.job_queue.run_repeating(
            _check_recordatorios_job,
            interval=60,
            first=15,
            name="check_recordatorios",
        )
        # Sugerencias de plugins: cada lunes a las 10:00
        app.job_queue.run_daily(
            _sugerir_plugins_job,
            time=dt_time(10, 0, tzinfo=madrid),
            days=(0,),
            name="sugerir_plugins",
        )
    else:
        print("[TG] JobQueue no disponible; reporte diario, recordatorios y sugerencias desactivados.")

    print(f"Bot listo. Escuchando mensajes de ID {TELEGRAM_ALLOWED_ID}...")
    app.run_polling(drop_pending_updates=False)

if __name__ == "__main__":
    main()
