import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import ollama
import socket
import random
import json
import threading
import re
import time
import itertools
from datetime import datetime
from groq import Groq

from config import (
    SYSTEM_PROMPT, HISTORIAL_PATH,
    OLLAMA_HOST_LOCAL, OLLAMA_HOST_ORACLE,
    MODEL_FAST, MODEL_SMART,
    GROQ_API_KEY, GROQ_MODEL, GROQ_MODEL_FALLBACK,
    RESPUESTAS_ACTIVACION,
    USE_ALEXA_TTS,
)
from interfaces.voz import nova_habla, nova_escucha, esperar_activacion, nova_tts, nova_reproduce, nova_alexa_flush
from utils.internet import obtener_info_internet, necesita_internet
from memory.memoria import (
    obtener_contexto_memoria, extraer_y_guardar_memoria,
    obtener_contexto_cruzado,
    cargar_historial as _cargar_historial_remoto,
    guardar_historial as _guardar_historial_remoto,
)
from interfaces.servidor import actualizar_estado, iniciar_servidor
from utils.acciones import maybe_handle_action_request
from agents.agente import (
    maybe_handle_auto, maybe_handle_agentic,
    check_pending_agentico, continuar_agentico,
    maybe_auto_extend,
)
from agents.orquestador import maybe_handle_orchestrated
from agents.explorador import necesita_explorar_nova, obtener_contexto_nova, obtener_resumen_propio
from mono import log as mlog
from orchestration import daemon_proactivo
from utils import presencia
from memory import personas as _personas_mod


_cliente_local  = ollama.Client(host=OLLAMA_HOST_LOCAL,  timeout=30.0)
_cliente_oracle = ollama.Client(host=OLLAMA_HOST_ORACLE, timeout=30.0)
_cliente_local_ping = ollama.Client(host=OLLAMA_HOST_LOCAL, timeout=2.0)
_groq_client = Groq(api_key=GROQ_API_KEY)

# Razonamiento interno capturado de los bloques <think> de DeepSeek-R1.
# Se inyecta en el siguiente turno para que el modelo sepa qué razonó antes.
_pensamiento_sesion = ""

_local_cache    = {"ok": False, "ts": 0.0}
_internet_cache = {"ok": False, "ts": 0.0}

def _local_disponible():
    now = time.time()
    if now - _local_cache["ts"] < 15:
        return _local_cache["ok"]
    mlog("LOCAL", f"Verificando disponibilidad del núcleo local ({OLLAMA_HOST_LOCAL})...")
    try:
        _cliente_local_ping.list()
        _local_cache["ok"] = True
        mlog("LOCAL", f"Núcleo local en línea. Modelo: {MODEL_FAST}")
    except Exception:
        _local_cache["ok"] = False
        mlog("LOCAL", "Núcleo local no disponible. Iniciando protocolo de fallback.")
    _local_cache["ts"] = now
    return _local_cache["ok"]

def _internet_disponible():
    now = time.time()
    if now - _internet_cache["ts"] < 10:
        return _internet_cache["ok"]
    try:
        socket.setdefaulttimeout(1.5)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
        s.close()
        _internet_cache["ok"] = True
    except Exception:
        _internet_cache["ok"] = False
    _internet_cache["ts"] = now
    return _internet_cache["ok"]

_ORACLE_KEYWORDS = [
    "código", "codifica", "programa", "script", "función", "algoritmo",
    "bug", "error", "depura", "debug", "compila",
    "redacta", "escribe", "traduce", "resume el",
    "calcula", "matemáticas", "ecuación",
    "analiza en detalle", "explícame en detalle", "razona",
]

# Señales de razonamiento profundo: activan DeepSeek-R1 incluso con internet
# porque su chain-of-thought supera a modelos generales en análisis complejo.
_DEEP_REASONING_KEYWORDS = [
    "por qué", "cómo funciona", "explícame cómo", "diferencia entre",
    "compara", "ventajas y desventajas", "pros y contras",
    "planifica", "diseña", "arquitectura", "estrategia",
    "analiza", "reflexiona", "razona paso a paso", "paso a paso",
    "qué harías", "qué opinas", "cuál es mejor",
    "ayúdame a decidir", "toma de decisión",
]

def _necesita_oracle(texto):
    t = texto.lower()
    return any(k in t for k in _ORACLE_KEYWORDS)

def _requiere_razonamiento_profundo(texto):
    """Detecta queries que se benefician del chain-of-thought de DeepSeek-R1."""
    t = texto.lower()
    señales = sum(1 for k in _DEEP_REASONING_KEYWORDS if k in t)
    # 2+ señales, o 1 señal con query larga (>90 chars = pregunta elaborada)
    return señales >= 2 or (señales >= 1 and len(texto) > 90)

_PLAN_KEYWORDS = [
    "puedes", "puedo", "sabes", "capaz", "capacidad", "haz", "hace",
    "conectate", "conecta", "abre", "instala", "reinicia",
    "ejecuta", "estado", "log", "logs",
]


def _requiere_modo_agente(texto):
    t = texto.lower()
    return any(k in t for k in _PLAN_KEYWORDS)


# ── Frases de corrección que Alex usa cuando NOVA se equivoca ─────────────────
_FRASES_CORRECCION = [
    "eso está mal", "te equivocas", "no es así", "estás equivocada",
    "eso no es correcto", "me dijiste mal", "no tenías razón",
    "eso es incorrecto", "no, es que", "no, lo que",
]


def _detectar_y_registrar_correccion(texto: str, historial: list) -> None:
    t = texto.lower()
    if not any(p in t for p in _FRASES_CORRECCION):
        return
    ultima = next((e["content"] for e in reversed(historial) if e.get("role") == "assistant"), None)
    if not ultima:
        return
    from memoria import añadir_hecho
    añadir_hecho(
        f"[CORRECCIÓN DE ALEX — ALTA PRIORIDAD] NOVA dijo algo incorrecto: "
        f"'{ultima[:180]}' — Alex corrigió: '{texto[:180]}'"
    )
    mlog("MEMORIA", "Corrección de Alex guardada con alta prioridad en memoria.")


def _contexto_momento() -> str:
    """Devuelve contexto del momento del día para que NOVA adapte su tono."""
    now = datetime.now()
    hora = now.hour
    dia = now.weekday()  # 0=lunes, 6=domingo
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

    if 0 <= hora < 7:
        actividad = "Alex probablemente está durmiendo o trasnochando"
        tono = "muy concisa, no hagas preguntas ni des detalles innecesarios"
    elif 7 <= hora < 9:
        actividad = "primera hora de la mañana, Alex está empezando el día"
        tono = "eficiente y directa"
    elif 9 <= hora < 14:
        actividad = "mañana" + (" laborable" if dia < 5 else " de fin de semana")
        tono = "normal"
    elif 14 <= hora < 16:
        actividad = "hora de comer"
        tono = "relajada y concisa"
    elif 16 <= hora < 20:
        actividad = "tarde" + (" laborable" if dia < 5 else " de fin de semana, Alex probablemente jugando")
        tono = "normal" if dia < 5 else "más informal"
    elif 20 <= hora < 23:
        actividad = "noche"
        if dia in (1, 2, 3):
            actividad += " — martes/miércoles/jueves, posible sesión de WoW u otro juego"
        tono = "más informal y cercana, puede hacer comentarios sobre gaming si viene al caso"
    else:
        actividad = "noche tardía"
        tono = "concisa, Alex probablemente terminando el día"

    return f"Es {dias[dia]}, {hora:02d}:{now.minute:02d}h. Contexto: {actividad}. Tono sugerido: {tono}."


def _analizar_tono_historial(historial: list) -> str:
    """Detecta el estado de Alex en los últimos mensajes para adaptar la personalidad."""
    if not historial:
        return ""
    _FRUSTRACION = ["no funciona", "no va", "joder", "hostia", "coño", "mierda",
                    "otra vez", "sigue sin", "por qué no", "qué mal", "bug"]
    _RELAJADO = ["gracias", "perfecto", "genial", "muy bien", "bien hecho",
                 "exacto", "justo eso", "me has salvado", "eres la mejor"]

    recientes = [t for t in historial[-8:] if t.get("role") == "user"]
    if not recientes:
        return ""

    textos = " ".join(t["content"] for t in recientes).lower()
    avg_len = sum(len(t["content"]) for t in recientes) / len(recientes)
    n_frustracion = sum(1 for k in _FRUSTRACION if k in textos)
    n_relajado = sum(1 for k in _RELAJADO if k in textos)

    if n_frustracion >= 2 or avg_len < 12:
        return "ESTADO DE ALEX: parece en modo eficiente o algo impaciente. Sé más directa y concisa de lo normal, sin adornos ni explicaciones largas."
    if n_relajado >= 2 and avg_len > 35:
        return "ESTADO DE ALEX: está relajado y satisfecho. Puedes ser más sarcástica e ingeniosa, añade algún comentario de contexto si viene al caso."
    return ""


def _detectar_contradiccion(texto: str) -> str:
    """
    Compara el mensaje de Alex contra hechos del perfil base.
    Devuelve aviso si detecta contradicción evidente, o "" si no hay nada.
    Solo comprueba datos del perfil fijo — sin llamar al LLM.
    """
    from memoria import cargar_memoria
    t = texto.lower()
    try:
        memoria = cargar_memoria()
        perfil  = memoria.get("perfil", {})
        ciudad  = (perfil.get("ciudad") or "").lower()
        nombre  = (perfil.get("nombre") or "").lower()

        # Detección simple: si Alex dice "vivo en X" y X no es su ciudad
        if "vivo en " in t or "vivimos en " in t or "soy de " in t:
            for ciudad_alt in ["madrid", "barcelona", "valencia", "sevilla", "bilbao",
                               "málaga", "alicante", "murcia", "palma", "las palmas"]:
                if ciudad_alt in t and ciudad and ciudad_alt != ciudad:
                    return (
                        f"CONTRADICCIÓN POSIBLE: Alex dice vivir en {ciudad_alt.title()} "
                        f"pero en memoria figura {ciudad.title()}. Pregunta si ha cambiado o es un error."
                    )
    except Exception:
        pass
    return ""


def _evaluar_respuesta_async(texto_alex: str, respuesta_nova: str) -> None:
    """
    Evalúa la calidad de la respuesta via Hermes3 en background (no bloquea).
    Guarda métricas en evaluaciones.jsonl para análisis posterior.
    """
    def _eval():
        try:
            prompt = (
                f'Alex dijo: "{texto_alex[:200]}"\n'
                f'NOVA respondió: "{respuesta_nova[:300]}"\n\n'
                "Puntúa la respuesta de NOVA del 1 al 5:\n"
                "5=perfecta, 4=buena, 3=aceptable, 2=mejorable, 1=incorrecta o irrelevante\n"
                "Responde SOLO con JSON: {\"puntuacion\": N, \"razon\": \"frase corta\"}"
            )
            resp = _cliente_oracle.chat(
                model="hermes3:8b",
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0.0},
            )
            resultado = resp["message"]["content"].strip()
            import re as _re, json as _json
            match = _re.search(r'\{.*\}', resultado, _re.DOTALL)
            if match:
                datos = _json.loads(match.group())
                puntuacion = datos.get("puntuacion", 0)
                razon      = datos.get("razon", "")
                linea = _json.dumps({
                    "ts": datetime.now().isoformat()[:16],
                    "puntuacion": puntuacion,
                    "razon": razon,
                    "query": texto_alex[:80],
                }, ensure_ascii=False)
                from pathlib import Path as _Path
                eval_path = _Path(__file__).parent / "evaluaciones.jsonl"
                with open(eval_path, "a", encoding="utf-8") as f:
                    f.write(linea + "\n")
                if puntuacion <= 2:
                    mlog("EVAL", f"Respuesta baja calidad ({puntuacion}/5): {razon}")
        except Exception:
            pass

    threading.Thread(target=_eval, daemon=True).start()


def _build_system_prompt(contexto_memoria, mensaje, contexto_internet, contexto_nova, historial=None):
    global _pensamiento_sesion
    resumen_propio = obtener_resumen_propio()
    partes = [SYSTEM_PROMPT, f"\n\nFECHA Y HORA ACTUAL: {obtener_hora()}", f"\n\nMEMORIA PERSISTENTE:\n{contexto_memoria}"]

    # Estado contextual: hora, día, actividad probable de Alex
    partes.append(f"\n\nCONTEXTO DEL MOMENTO: {_contexto_momento()}")

    # Presencia real: si Alex está jugando o lleva tiempo inactivo
    ctx_presencia = presencia.contexto_para_nova()
    if ctx_presencia:
        partes.append(f"\n\n{ctx_presencia}")

    # Patrones de uso: qué suele preguntar Alex en este momento
    try:
        import patrones_uso as _pu
        resumen_patrones = _pu.generar_resumen_patrones()
        if resumen_patrones:
            partes.append(f"\n\n{resumen_patrones}")
    except Exception:
        pass

    # Personalidad adaptativa según el tono reciente de Alex
    if historial:
        tono = _analizar_tono_historial(historial)
        if tono:
            partes.append(f"\n\n{tono}")

    if _pensamiento_sesion:
        partes.append(
            f"\n\nRAZONAMIENTO INTERNO PREVIO (lo que pensaste en tu última respuesta, no lo repitas en voz alta):\n{_pensamiento_sesion[:900]}"
        )

    if resumen_propio:
        partes.append(f"\n\nAUTOCONOCIMIENTO:\n{resumen_propio}")
    else:
        partes.append(
            "\n\nCAPACIDADES OPERATIVAS:"
            "\n- Puedes ejecutar acciones internas si existe una herramienta local."
            "\n- Puedes consultar Oracle cuando la tarea lo requiera."
            "\n- Puedes inspeccionar tu propio codigo y arquitectura si te preguntan por ello."
        )

    if contexto_internet:
        partes.append(
            f"\n\nCONTEXTO EN TIEMPO REAL (leido ahora mismo de internet):\n{contexto_internet}"
            "\n\nIMPORTANTE: Responde basandote en esta informacion. No la ignores ni la complementes con suposiciones."
        )

    if contexto_nova:
        partes.append(
            f"\n\nCONTEXTO DE TU CODIGO (leido en este momento desde B:\\NOVA):\n{contexto_nova}"
            "\n\nIMPORTANTE: Responde UNICAMENTE basandote en el codigo mostrado arriba."
            " No inventes archivos, funciones ni modulos que no aparezcan en ese codigo."
            " Si algo no esta en el codigo proporcionado, dilo."
        )

    ctx_telegram = obtener_contexto_cruzado("voz")
    if ctx_telegram:
        partes.append(
            f"\n\nCONTEXTO RECIENTE (Telegram) — usa esto solo si Alex pregunta explicitamente por algo que hablo por Telegram. No lo mezcles ni lo respondas espontaneamente en la conversacion de voz actual:\n{ctx_telegram}"
        )

    # Tareas pendientes de Alex
    try:
        import gestor_tareas as _gt
        ctx_tareas = _gt.obtener_contexto_tareas()
        if ctx_tareas:
            partes.append(
                f"\n\n{ctx_tareas}"
                "\nSi la conversacion está relacionada con alguna de estas tareas, menciónalo o pregunta si ya la completó. "
                "Si Alex confirma que terminó una, llama a gestor_tareas.marcar_completada() mentalmente y díselo."
            )
    except Exception:
        pass

    # Personas mencionadas en el mensaje actual
    ctx_personas = _personas_mod.obtener_contexto_personas(mensaje)
    if ctx_personas:
        partes.append(f"\n\n{ctx_personas}")

    # Contradicción detectada heurísticamente
    contradiccion = _detectar_contradiccion(mensaje)
    if contradiccion:
        partes.append(f"\n\nAVISO: {contradiccion}")

    # Metacognición: advertir cuando no hay contexto de internet para datos actuales
    _DATOS_ACTUALES = ["cuando", "hoy", "ahora", "esta semana", "este mes", "resultado",
                       "partido", "precio", "temperatura", "noticias", "últimas"]
    if not contexto_internet and any(k in mensaje.lower() for k in _DATOS_ACTUALES):
        partes.append(
            "\n\nMETACOGNICIÓN: Esta pregunta puede requerir datos actuales pero no tienes contexto de internet. "
            "Si no tienes el dato concreto, dilo directamente en lugar de usar tu conocimiento de entrenamiento (que puede estar desactualizado)."
        )

    if _requiere_modo_agente(mensaje):
        partes.append(
            "\n\nMODO AGENTE:"
            "\n- Solo puedes ejecutar acciones implementadas en acciones.py o generadas por el agente autoextensible."
            "\n- Si no tienes esa capacidad implementada, dilo directamente. Nunca prometas ejecutar algo que no puedes."
            "\n- El agente autoextensible ya ha intentado resolver esto antes de que llegues aqui. Si llegas aqui, es que no era ejecutable automaticamente."
        )

    return "".join(partes)


def get_cliente_y_modelo(texto):
    """Routing inteligente por complejidad: Groq para conversación, DeepSeek-R1 para razonamiento profundo."""
    internet_ok = _internet_disponible()
    local_ok = _local_disponible()
    consulta_propia = necesita_explorar_nova(texto)
    actualizar_estado("thinking", local=local_ok, oracle=True)

    if internet_ok:
        # Razonamiento profundo → DeepSeek-R1 con chain-of-thought aunque haya internet
        if _requiere_razonamiento_profundo(texto) and not consulta_propia:
            mlog("ANÁLISIS", f"Razonamiento profundo detectado → Oracle DeepSeek-R1 (chain-of-thought)")
            return _cliente_oracle, MODEL_SMART, "ollama"
        mlog("ANÁLISIS", f"Internet disponible → Groq/{GROQ_MODEL}")
        return _groq_client, GROQ_MODEL, "groq"

    # Sin internet: Oracle para tareas complejas, local para conversacional
    if _necesita_oracle(texto) and not consulta_propia:
        mlog("ANÁLISIS", "Sin internet. Tarea compleja → Oracle DeepSeek")
        return _cliente_oracle, MODEL_SMART, "ollama"

    if local_ok:
        mlog("ANÁLISIS", f"Sin internet → núcleo local → {MODEL_FAST}")
        return _cliente_local, MODEL_FAST, "ollama"

    mlog("ORACLE", f"Fallback → Nodo Oracle → {MODEL_SMART}")
    return _cliente_oracle, MODEL_SMART, "ollama"


def cargar_historial():
    return _cargar_historial_remoto("voz")

def guardar_historial(historial):
    _guardar_historial_remoto(historial, "voz")

def _comprimir_historial(historial: list) -> list:
    """Cuando el historial supera 40 turnos, resume los más antiguos en lugar de truncar.
    Mantiene los últimos 20 turnos frescos y comprime el resto en un resumen."""
    if len(historial) <= 40:
        return historial

    a_comprimir = historial[:-20]
    recientes = historial[-20:]

    texto_para_resumir = "\n".join(
        f"{t['role'].upper()}: {t['content'][:250]}"
        for t in a_comprimir
        if t.get("role") in ("user", "assistant")
    )

    try:
        resp = _groq_client.chat.completions.create(
            model=GROQ_MODEL_FALLBACK,
            messages=[
                {"role": "system", "content": (
                    "Eres un asistente que resume conversaciones. "
                    "Resume los puntos clave de esta conversación en 4-6 frases en español. "
                    "Incluye: temas tratados, decisiones tomadas, preferencias expresadas, "
                    "y cualquier dato relevante sobre Alex o sobre NOVA. "
                    "Sin bullet points. Solo texto continuo."
                )},
                {"role": "user", "content": texto_para_resumir},
            ],
            max_tokens=250,
            temperature=0.1,
        )
        resumen = resp.choices[0].message.content.strip()
        mlog("MEMORIA", f"Historial comprimido: {len(a_comprimir)} turnos → resumen de {len(resumen)} chars.")
        entrada_resumen = {
            "role": "system",
            "content": f"[RESUMEN DE CONVERSACIÓN ANTERIOR — {len(a_comprimir)} turnos]\n{resumen}"
        }
        return [entrada_resumen] + recientes
    except Exception as e:
        mlog("MEMORIA", f"Compresión de historial falló ({e}), truncando a 40 turnos.")
        return historial[-40:]

def obtener_hora():
    now = datetime.now()
    return f"{now.strftime('%A %d de %B de %Y')}, {now.strftime('%H:%M')}"

def saludo_segun_hora():
    hora = datetime.now().hour
    if 6 <= hora < 12:
        return "Buenos días, Alex."
    elif 12 <= hora < 21:
        return "Buenas tardes, Alex."
    else:
        return "Buenas noches, Alex."

def limpiar_para_voz(texto):
    texto = re.sub(r'<think>.*?</think>', '', texto, flags=re.DOTALL)
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'#+\s*', '', texto)
    texto = re.sub(r'`+', '', texto)
    texto = re.sub(r'\[.*?\]\(.*?\)', '', texto)
    texto = re.sub(r'^\s*[-]\s*', '', texto, flags=re.MULTILINE)
    return texto.strip()

def nova_piensa_streaming(mensaje, historial):
    actualizar_estado("thinking")
    mlog("ESCUCHA", f"Petición recibida: \"{mensaje[:60]}{'...' if len(mensaje) > 60 else ''}\"")

    mlog("MEMORIA", "Recuperando contexto persistente...")
    contexto_memoria = obtener_contexto_memoria()

    contexto_internet = ""
    _query_internet = mensaje
    # Si el usuario ordena buscar ("búscalo", "búscalo en internet"...) sin incluir
    # el tema real, recuperar la última pregunta del historial como query de búsqueda.
    _META_BUSQUEDA = ["buscalo", "busca en internet", "buscalo en internet",
                      "investiga", "mira en internet", "consulta en internet"]
    if any(k in mensaje.lower() for k in _META_BUSQUEDA):
        for entry in reversed(historial):
            if entry.get("role") == "user":
                prev = entry["content"]
                # Extraer solo la parte "Alex dice: ..." del mensaje anterior
                if "Alex dice:" in prev:
                    prev = prev.split("Alex dice:")[-1].strip()
                if len(prev) > 5 and prev != mensaje:
                    _query_internet = prev
                    mlog("RED", f"Query de búsqueda extraída del historial: \"{_query_internet[:60]}\"")
                    break
    if necesita_internet(mensaje) or _query_internet != mensaje:
        mlog("RED", "Consulta requiere información en tiempo real. Accediendo a fuentes externas...")
        info = obtener_info_internet(_query_internet)
        if info:
            mlog("RED", "Datos externos recuperados. Inyectando en contexto.")
            contexto_internet = f"\n[Información actualizada]:\n{info}\n"

    if contexto_internet.startswith("\n["):
        contexto_internet = contexto_internet.strip()
        partes_ctx = contexto_internet.split("\n", 1)
        contexto_internet = partes_ctx[1] if len(partes_ctx) > 1 else contexto_internet

    mensaje_completo = f"[{obtener_hora()}]\n{contexto_internet}\nAlex dice: {mensaje}"
    contexto_nova = ""
    if necesita_explorar_nova(mensaje):
        mlog("ANALISIS", "Peticion sobre capacidades o arquitectura. Cargando autoconocimiento...")
        contexto_nova = obtener_contexto_nova(mensaje)

    bloques = [f"[{obtener_hora()}]"]
    if contexto_internet:
        bloques.append(f"[Informacion actualizada]:\n{contexto_internet}")
    if contexto_nova:
        bloques.append(f"[Contexto de NOVA]:\n{contexto_nova}")
    bloques.append(f"Alex dice: {mensaje}")
    mensaje_completo = "\n\n".join(bloques)
    historial.append({"role": "user", "content": mensaje_completo})

    if len(historial) > 40:
        historial = _comprimir_historial(historial)

    system_con_memoria = _build_system_prompt(
        contexto_memoria,
        mensaje,
        contexto_internet,
        contexto_nova,
        historial=historial,
    )

    cliente, modelo, backend = get_cliente_y_modelo(mensaje)

    texto_acumulado = ""
    respuesta_completa = ""
    separadores = re.compile(r'(?<=[.!?])\s+')

    mlog("NÚCLEO", "Modelo activo. Iniciando generación de respuesta...")
    actualizar_estado("talking")

    temperature = 0.15 if (contexto_nova or contexto_internet) else 0.3

    def _stream_groq(msgs):
        raw = _groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=msgs,
            stream=True,
            max_tokens=300,
            temperature=temperature,
        )
        for chunk in raw:
            yield chunk.choices[0].delta.content or ""

    def _stream_ollama(cli, mdl, msgs):
        raw = cli.chat(model=mdl, messages=msgs, stream=True, options={"temperature": temperature})
        for chunk in raw:
            yield chunk['message']['content']

    msgs_completos = [{"role": "system", "content": system_con_memoria}] + historial

    if backend == "groq":
        try:
            fragmentos = _stream_groq(msgs_completos)
            # Forzar primer chunk no vacío para detectar errores antes de hablar
            first = next((c for c in fragmentos if c), None)
            if not first:
                raise RuntimeError("Groq devolvió stream vacío o solo tokens vacíos")
            fragmentos = itertools.chain([first], fragmentos)
        except Exception as e:
            mlog("GROQ", f"{GROQ_MODEL} no disponible ({e}). Intentando fallback Groq → {GROQ_MODEL_FALLBACK}...")
            try:
                def _stream_groq_fallback(msgs):
                    raw = _groq_client.chat.completions.create(
                        model=GROQ_MODEL_FALLBACK,
                        messages=msgs,
                        stream=True,
                        max_tokens=300,
                        temperature=temperature,
                    )
                    for chunk in raw:
                        yield chunk.choices[0].delta.content or ""
                fragmentos = _stream_groq_fallback(msgs_completos)
                first = next((c for c in fragmentos if c), None)
                if not first:
                    raise RuntimeError("Llama también devolvió stream vacío")
                fragmentos = itertools.chain([first], fragmentos)
                mlog("GROQ", f"Fallback a {GROQ_MODEL_FALLBACK} activo.")
            except Exception as e2:
                mlog("ERROR", f"Groq fallback también falló ({e2}). Último recurso → Oracle DeepSeek.")
                fragmentos = _stream_ollama(_cliente_oracle, MODEL_SMART, msgs_completos)
    else:
        fragmentos = _stream_ollama(cliente, modelo, msgs_completos)

    # Pipeline: genera TTS mientras reproduce la frase anterior
    import queue as _q
    audio_q = _q.Queue()

    def _play_worker():
        while True:
            item = audio_q.get()
            if item is None:
                break
            frase, buf = item
            print(f"NOVA: {frase}")
            nova_reproduce(buf)

    play_thread = threading.Thread(target=_play_worker, daemon=True)
    play_thread.start()

    def _encolar(frase):
        buf = nova_tts(frase)
        if buf:
            audio_q.put((frase, buf))

    en_thinking = False
    pensamiento_capturado = []
    t_inicio = time.time()

    def _procesar_fragmentos(frags):
        nonlocal texto_acumulado, respuesta_completa, en_thinking
        for fragmento in frags:
            if time.time() - t_inicio > 120:
                mlog("ERROR", "Timeout — modelo no responde en el límite establecido.")
                audio_q.put(None)
                play_thread.join()
                nova_habla("El servidor no responde, intentalo de nuevo.")
                return False
            if '<think>' in fragmento:
                en_thinking = True
                continue
            if '</think>' in fragmento:
                en_thinking = False
                continue
            if en_thinking:
                pensamiento_capturado.append(fragmento)
                continue
            texto_acumulado += fragmento
            respuesta_completa += fragmento
            partes = separadores.split(texto_acumulado)
            if len(partes) > 1:
                for frase in partes[:-1]:
                    frase = limpiar_para_voz(frase)
                    if len(frase) > 10:
                        _encolar(frase)
                texto_acumulado = partes[-1]
        return True

    try:
        ok = _procesar_fragmentos(fragmentos)
    except Exception as e:
        if backend == "groq":
            mlog("ERROR", f"Groq falló mid-stream ({e}). Fallback → Oracle DeepSeek.")
            # Vaciar cola de audio parcial y esperar a que el worker termine
            while not audio_q.empty():
                try:
                    audio_q.get_nowait()
                except Exception:
                    break
            audio_q.put(None)
            play_thread.join()
            texto_acumulado = ""
            respuesta_completa = ""
            # Reiniciar pipeline de audio limpio
            audio_q2 = _q.Queue()
            def _play_worker2():
                while True:
                    item = audio_q2.get()
                    if item is None:
                        break
                    frase, buf = item
                    print(f"NOVA: {frase}")
                    nova_reproduce(buf)
            play_thread2 = threading.Thread(target=_play_worker2, daemon=True)
            play_thread2.start()
            audio_q = audio_q2
            play_thread = play_thread2
            nova_habla("Un momento, cambiando al servidor alternativo.")
            ok = _procesar_fragmentos(_stream_ollama(_cliente_oracle, MODEL_SMART, msgs_completos))
        else:
            audio_q.put(None)
            play_thread.join()
            raise

    if not ok:
        return "Timeout.", historial

    if texto_acumulado.strip():
        texto_final = limpiar_para_voz(texto_acumulado)
        if texto_final:
            _encolar(texto_final)

    audio_q.put(None)
    play_thread.join()
    nova_alexa_flush()  # En modo Alexa envía la respuesta completa al Echo

    # Guardar pensamiento interno de DeepSeek para el siguiente turno
    global _pensamiento_sesion
    if pensamiento_capturado:
        _pensamiento_sesion = "".join(pensamiento_capturado)[:900]
        mlog("RAZONAMIENTO", f"Pensamiento interno capturado ({len(_pensamiento_sesion)} chars) — disponible en siguiente turno.")
    else:
        _pensamiento_sesion = ""

    respuesta_completa = limpiar_para_voz(respuesta_completa)
    if not respuesta_completa:
        mlog("ERROR", f"Respuesta vacía tras generación (backend={backend}, modelo={GROQ_MODEL if backend == 'groq' else MODEL_SMART}). Revisa la salida del stream.")
    historial.append({"role": "assistant", "content": respuesta_completa})
    guardar_historial(historial)

    mlog("MEMORIA", "Extrayendo datos relevantes para memoria persistente...")
    threading.Thread(
        target=extraer_y_guardar_memoria,
        args=(mensaje, respuesta_completa, _cliente_oracle),
        daemon=True
    ).start()

    # Extracción de personas mencionadas (background)
    _personas_mod.extraer_personas_async(mensaje, _cliente_oracle)

    # Auto-evaluación de la respuesta (background, no bloquea)
    _evaluar_respuesta_async(mensaje, respuesta_completa)

    mlog("CICLO", "Procesamiento completo. Retornando a modo escucha.")
    return respuesta_completa, historial

def _responder_agentico(resultado: dict, historial: list) -> tuple[bool, list]:
    """Habla la respuesta del bucle agéntico y devuelve (activo, historial)."""
    if resultado.get("needs_confirmation"):
        actualizar_estado("talking")
        nova_habla(resultado["confirmacion_msg"])
        actualizar_estado("idle")
        return True, historial
    if resultado.get("handled"):
        actualizar_estado("talking")
        respuesta = limpiar_para_voz(resultado["reply"])
        nova_habla(respuesta)
        actualizar_estado("idle")
    return True, historial


def procesar_texto(texto, historial):
    texto_lower = texto.lower()

    # Registrar patrones de uso (en background, no bloquea)
    try:
        import patrones_uso as _pu
        threading.Thread(target=_pu.registrar_uso, args=(texto,), daemon=True).start()
    except Exception:
        pass

    # Detectar si Alex está corrigiendo a NOVA y guardar con alta prioridad
    _detectar_y_registrar_correccion(texto, historial)

    # Detectar tareas pendientes mencionadas por Alex
    try:
        import gestor_tareas as _gt
        _gt.procesar_mensaje(texto, historial)
    except Exception:
        pass

    if any(p in texto_lower for p in ["apagar nova", "cerrar nova", "exit", "salir", "apagate", "hasta luego nova", "adios nova"]):
        mlog("SISTEMA", "Directiva de apagado recibida. Cerrando módulos...")
        actualizar_estado("idle")
        nova_habla("Hasta luego.")
        return False, historial

    if any(p in texto_lower for p in ["cancela", "para ya", "detente", "calla", "callate", "silencio"]):
        mlog("SISTEMA", "Interrupción manual. Abortando proceso en curso.")
        actualizar_estado("idle")
        nova_habla("Cancelado.")
        return True, historial

    # Confirmación de acción agéntica pendiente
    pending = check_pending_agentico()
    if pending:
        resp_lower = texto_lower.strip()
        # Si parece respuesta de confirmación (corta o contiene sí/no)
        from agente import CONFIRM_WORDS, CANCEL_WORDS
        es_confirmacion = (
            any(w in resp_lower for w in CONFIRM_WORDS) or
            any(w in resp_lower for w in CANCEL_WORDS) or
            len(resp_lower) < 25
        )
        if es_confirmacion:
            mlog("AGENTE_V2", f"Respuesta a confirmación pendiente: {texto[:40]}")
            resultado = continuar_agentico(texto, pending)
            if resultado:
                return _responder_agentico(resultado, historial)
        else:
            # Comando diferente: cancela el pendiente y procesa normalmente
            from agente import _clear_agentico_pending
            _clear_agentico_pending()
            mlog("AGENTE_V2", "Confirmación pendiente descartada por nuevo comando.")

    accion = maybe_handle_action_request(texto, historial)
    if accion and accion.get("handled"):
        actualizar_estado("talking")
        respuesta = limpiar_para_voz(accion["reply"])
        mlog("MOTOR", f"Accion ejecutada sin pasar por el LLM: {texto[:60]}")
        nova_habla(respuesta)
        actualizar_estado("idle")
        return True, historial

    auto = maybe_handle_auto(texto, historial)
    if auto and auto.get("handled"):
        actualizar_estado("talking")
        respuesta = limpiar_para_voz(auto["reply"])
        mlog("AGENTE", f"Agente autoextensible respondio: {texto[:60]}")
        nova_habla(respuesta)
        actualizar_estado("idle")
        return True, historial

    # Bucle agéntico multi-paso (ficheros, comandos, búsquedas iterativas)
    agentico = maybe_handle_agentic(texto)
    if agentico:
        mlog("AGENTE_V2", f"Bucle agéntico activado: {texto[:60]}")
        return _responder_agentico(agentico, historial)

    orq = maybe_handle_orchestrated(texto)
    if orq and orq.get("handled"):
        actualizar_estado("talking")
        respuesta = limpiar_para_voz(orq["reply"])
        mlog("ORQUESTADOR", f"Orquestador respondio: {texto[:60]}")
        nova_habla(respuesta)
        actualizar_estado("idle")
        return True, historial

    auto_ext = maybe_auto_extend(texto, historial)
    if auto_ext and auto_ext.get("handled"):
        actualizar_estado("talking")
        respuesta = limpiar_para_voz(auto_ext["reply"])
        mlog("AUTO_EXT", f"Plugin creado automáticamente para: {texto[:60]}")
        nova_habla(respuesta)
        actualizar_estado("idle")
        return True, historial

    respuesta, historial = nova_piensa_streaming(texto, historial)
    actualizar_estado("idle")
    return True, historial

def iniciar_nova():
    print("=" * 40)
    print("  N.O.V.A - Sistema iniciado")
    print("=" * 40)

    mlog("SISTEMA", "Inicializando módulos de núcleo...")

    if USE_ALEXA_TTS:
        mlog("ALEXA", "Iniciando conexión con dispositivo Echo...")
        from alexa_voz import inicializar_alexa
        inicializar_alexa()

    historial = cargar_historial()
    mlog("MEMORIA", f"Historial cargado: {len(historial)} entradas previas.")
    mlog("SISTEMA", "Todos los subsistemas operativos. Activando interfaz de voz.")
    actualizar_estado("idle")

    time.sleep(9)  # Espera a que el boot animation llegue a la fase de voz
    bienvenida = "Bienvenido a casa, señor. Todos los sistemas están operativos y en línea. He sincronizado sus bases de datos y el entorno de trabajo está optimizado. Dígame, ¿por dónde desea que empecemos hoy?"
    actualizar_estado("talking")
    nova_habla(bienvenida)
    actualizar_estado("idle")

    while True:
        mlog("ESCUCHA", "En modo escucha activa. Esperando palabra de activación...")
        actualizar_estado("idle")
        comando_inmediato = esperar_activacion()

        if comando_inmediato:
            mlog("ESCUCHA", f"Palabra clave detectada con comando directo: \"{comando_inmediato[:50]}\"")
            print(f"Alex: {comando_inmediato}")
            actualizar_estado("listening")
            activo, historial = procesar_texto(comando_inmediato, historial)
            if not activo:
                return
        else:
            mlog("ESCUCHA", "Activación detectada. Abriendo canal de voz.")
            activacion = random.choice(RESPUESTAS_ACTIVACION)

            # Notificaciones proactivas: urgentes siempre, relevantes si las hay
            pendientes = daemon_proactivo.obtener_pendientes(min_prioridad="RELEVANTE")
            if pendientes:
                primera = pendientes[0]
                if primera.get("prioridad") == "URGENTE":
                    nota = f" Alerta: {primera['info'][:120]}"
                else:
                    nota = f" Por cierto, tengo algo sobre {primera['tema']} cuando quieras."
                activacion = activacion.rstrip(".") + nota

            actualizar_estado("talking")
            nova_habla(activacion)
            actualizar_estado("listening")

        while True:
            texto = nova_escucha()

            if texto is None:
                mlog("CICLO", "Silencio prolongado. Cerrando canal de voz. Volviendo a modo espera.")
                actualizar_estado("idle")
                break

            activo, historial = procesar_texto(texto, historial)
            if not activo:
                return

if __name__ == "__main__":
    hilo_servidor = threading.Thread(target=iniciar_servidor, daemon=True)
    hilo_servidor.start()
    print("NOVA: Servidor HUD iniciado en http://127.0.0.1:5000")
    daemon_proactivo.iniciar()

    # Tareas autónomas programadas
    try:
        import tareas_autonomas
        tareas_autonomas.iniciar()
    except Exception as e:
        mlog("SISTEMA", f"Daemon autónomo no disponible: {e}")

    # Consolidación nocturna (3 AM)
    try:
        import consolidacion_nocturna
        consolidacion_nocturna.iniciar(_groq_client, GROQ_MODEL_FALLBACK)
    except Exception as e:
        mlog("SISTEMA", f"Consolidación nocturna no disponible: {e}")

    # Hilo de recordatorios por voz
    def _loop_recordatorios():
        import time as _time
        while True:
            _time.sleep(30)
            try:
                from recordatorios import pendientes_vencidos, marcar_enviado
                for r in pendientes_vencidos():
                    mlog("RECORDATORIO", f"Vencido [{r['id']}]: {r['mensaje']}")
                    nova_habla(f"Recordatorio: {r['mensaje']}")
                    marcar_enviado(r["id"])
            except Exception as e:
                mlog("RECORDATORIO", f"Error comprobando recordatorios: {e}")

    threading.Thread(target=_loop_recordatorios, daemon=True, name="recordatorios").start()

    iniciar_nova()
