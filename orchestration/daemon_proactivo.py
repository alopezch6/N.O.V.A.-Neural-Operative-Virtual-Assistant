"""
Daemon proactivo de NOVA.

Cada 6 horas:
  1. Monitoriza el estado de los sistemas (Oracle, PC local, disco)
  2. Cruza los intereses de Alex con búsquedas de internet
  3. Genera notificaciones con prioridad URGENTE / RELEVANTE / INFORMATIVO

NOVA las menciona al inicio de la siguiente conversación según su prioridad.
Las URGENTES también se envían por Telegram inmediatamente.
"""

import json
import threading
import time
import requests
from datetime import datetime
from pathlib import Path

from mono import log as mlog
from utils import twitch_tracker

_PENDIENTES_PATH = Path(__file__).resolve().parents[1] / "notificaciones_pendientes.json"
_MEMORIA_PATH    = Path(__file__).resolve().parents[1] / "memoria.json"
_INTERVALO_HORAS = 6
_MONITOR_INTERVALO = 1800  # cada 30 min para sistemas críticos

# Intereses base como fallback si la memoria no está disponible
_INTERESES_BASE = [
    "World of Warcraft", "Valorant", "League of Legends",
    "Real Zaragoza", "inteligencia artificial noticias",
]

# Umbrales de alerta del sistema
_DISCO_MINIMO_GB = 2.0
_RAM_MAXIMA_PCT  = 90
_CPU_MAXIMA_PCT  = 95


# ── Lectura de intereses ──────────────────────────────────────────────────────

def _leer_intereses() -> list[str]:
    try:
        data = json.loads(_MEMORIA_PATH.read_text(encoding="utf-8"))
        perfil = data.get("perfil", data)  # soporta ambos formatos
        juegos = perfil.get("juegos", [])
        intereses = perfil.get("intereses", [])
        ciudad = perfil.get("ciudad", "")
        temas = list(dict.fromkeys(juegos + intereses))
        if ciudad:
            temas.append(f"noticias {ciudad}")
        return temas if temas else _INTERESES_BASE
    except Exception:
        return _INTERESES_BASE


# ── Monitorización de sistemas ────────────────────────────────────────────────

def _check_oracle() -> list[dict]:
    """Comprueba el estado de Oracle Cloud via Ollama API."""
    alertas = []
    try:
        from config import OLLAMA_HOST_ORACLE, ALMACEN_URL, ALMACEN_TOKEN
        r = requests.get(f"{ALMACEN_URL}/estado", headers={"X-Nova-Token": ALMACEN_TOKEN}, timeout=5)
        if r.status_code == 200:
            d = r.json()
            oracle = d.get("oracle", {})
            disco_libre = oracle.get("disco_libre_gb", 99)
            ram_pct = oracle.get("ram_pct", 0)
            cpu_pct = oracle.get("cpu_pct", 0)

            if disco_libre < _DISCO_MINIMO_GB:
                alertas.append({
                    "prioridad": "URGENTE",
                    "tema": "disco Oracle",
                    "info": f"⚠️ Disco de Oracle casi lleno: solo {disco_libre:.1f} GB libres. Hay que limpiar.",
                    "ts": datetime.now().isoformat(),
                })
            if ram_pct > _RAM_MAXIMA_PCT:
                alertas.append({
                    "prioridad": "URGENTE",
                    "tema": "RAM Oracle",
                    "info": f"⚠️ Oracle al {ram_pct}% de RAM. Posible saturación.",
                    "ts": datetime.now().isoformat(),
                })
    except Exception as e:
        mlog("MONITOR", f"No se pudo verificar estado de Oracle: {e}")
    return alertas


def _check_pc_local() -> list[dict]:
    """Comprueba si el PC local está online via HUD de NOVA."""
    alertas = []
    try:
        from config import PC_TAILSCALE_IP
        if not PC_TAILSCALE_IP:
            return []
        r = requests.get(f"http://{PC_TAILSCALE_IP}:5000/estado", timeout=3)
        if r.status_code != 200:
            return []
        d = r.json()
        pc = d.get("pc", {})
        cpu = pc.get("cpu", 0)
        if cpu and cpu > _CPU_MAXIMA_PCT:
            alertas.append({
                "prioridad": "RELEVANTE",
                "tema": "CPU PC",
                "info": f"El PC local lleva rato al {cpu}% de CPU.",
                "ts": datetime.now().isoformat(),
            })
    except Exception:
        pass  # PC offline es normal
    return alertas


def _monitorizar_sistemas() -> list[dict]:
    alertas = []
    alertas.extend(_check_oracle())
    alertas.extend(_check_pc_local())
    if alertas:
        mlog("MONITOR", f"{len(alertas)} alerta(s) de sistema detectada(s).")
    return alertas


# ── Búsqueda de novedades ─────────────────────────────────────────────────────

def _clasificar_prioridad(tema: str, info: str) -> str:
    t = (tema + " " + info).lower()
    # Urgente: fallos, caídas, problemas de seguridad
    if any(k in t for k in ["error", "caída", "fallo", "crítico", "urgente", "hack", "brecha"]):
        return "URGENTE"
    # Relevante: eventos de hoy sobre intereses directos de Alex
    if any(k in t for k in ["hoy", "esta noche", "partido", "directo", "actualización", "parche", "update"]):
        return "RELEVANTE"
    return "INFORMATIVO"


def _es_reciente(info: str) -> bool:
    """Descarta resultados que mencionan fechas de hace más de 7 días sin fecha reciente."""
    import re
    from datetime import timedelta
    now = datetime.now()
    limite = now - timedelta(days=7)
    meses = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    }
    # Busca patrones "DD de mes" o "DD/MM[/YYYY]"
    patron_texto = re.findall(r'(\d{1,2})\s+de\s+(\w+)', info.lower())
    patron_num   = re.findall(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', info)

    fechas = []
    for dia_s, mes_s in patron_texto:
        mes_n = meses.get(mes_s)
        if mes_n:
            try:
                fechas.append(datetime(now.year, mes_n, int(dia_s)))
            except ValueError:
                pass
    for dia_s, mes_s, año_s in patron_num:
        try:
            año = int(año_s) if año_s else now.year
            fechas.append(datetime(año, int(mes_s), int(dia_s)))
        except ValueError:
            pass

    if not fechas:
        return True  # Sin fechas detectadas → aceptar
    return any(f >= limite for f in fechas)


def _buscar_novedades(intereses: list[str]) -> list[dict]:
    from internet import obtener_info_internet
    now = datetime.now()
    año = str(now.year)

    notificaciones = []
    for tema in intereses[:4]:
        try:
            info = obtener_info_internet(f"novedades {tema} esta semana {año}")
            if not info or len(info.strip()) < 80:
                continue
            if not _es_reciente(info):
                mlog("PROACTIVO", f"Resultado obsoleto para '{tema}', omitiendo.")
                continue
            prioridad = _clasificar_prioridad(tema, info)
            notificaciones.append({
                "prioridad": prioridad,
                "tema": tema,
                "info": info.strip()[:350],
                "ts": now.isoformat(),
            })
            mlog("PROACTIVO", f"[{prioridad}] Novedad para '{tema}'.")
        except Exception as e:
            mlog("PROACTIVO", f"Error buscando '{tema}': {e}")
    return notificaciones


# ── Almacenamiento de pendientes ──────────────────────────────────────────────

def obtener_pendientes(min_prioridad: str = "INFORMATIVO") -> list[dict]:
    """
    Lee y vacía las notificaciones pendientes filtrando por prioridad mínima.
    Orden: URGENTE > RELEVANTE > INFORMATIVO
    """
    if not _PENDIENTES_PATH.exists():
        return []
    try:
        data = json.loads(_PENDIENTES_PATH.read_text(encoding="utf-8"))
        _PENDIENTES_PATH.unlink(missing_ok=True)
        if not isinstance(data, list):
            return []
        orden = {"URGENTE": 0, "RELEVANTE": 1, "INFORMATIVO": 2}
        umbral = orden.get(min_prioridad, 2)
        filtradas = [n for n in data if orden.get(n.get("prioridad", "INFORMATIVO"), 2) <= umbral]
        return sorted(filtradas, key=lambda n: orden.get(n.get("prioridad", "INFORMATIVO"), 2))
    except Exception:
        return []


def guardar_pendientes(notificaciones: list[dict]) -> None:
    _PENDIENTES_PATH.write_text(
        json.dumps(notificaciones, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _enviar_urgentes_telegram(alertas: list[dict]) -> None:
    """Envía alertas urgentes por Telegram sin esperar a que Alex active NOVA."""
    urgentes = [a for a in alertas if a.get("prioridad") == "URGENTE"]
    if not urgentes:
        return
    try:
        import asyncio
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_ID
        import telegram
        async def _send():
            bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
            for a in urgentes:
                await bot.send_message(chat_id=TELEGRAM_ALLOWED_ID, text=f"🚨 NOVA — ALERTA: {a['info']}")
        asyncio.run(_send())
        mlog("PROACTIVO", f"{len(urgentes)} alerta(s) urgente(s) enviada(s) por Telegram.")
    except Exception as e:
        mlog("PROACTIVO", f"No se pudo enviar alerta Telegram: {e}")


# ── Loop principal ────────────────────────────────────────────────────────────

def _loop_proactivo() -> None:
    time.sleep(1800)  # primera ejecución 30 min tras arranque
    while True:
        mlog("PROACTIVO", "Ciclo proactivo iniciado.")
        try:
            # 1. Monitorizar sistemas
            alertas_sistema = _monitorizar_sistemas()
            if alertas_sistema:
                _enviar_urgentes_telegram(alertas_sistema)

            # 2. Buscar novedades según intereses
            intereses = _leer_intereses()
            novedades = _buscar_novedades(intereses)

            # 3. Comprobar directos de Twitch
            try:
                notifs_twitch = twitch_tracker.generar_notificaciones_twitch()
            except Exception as e:
                mlog("PROACTIVO", f"Error Twitch tracker: {e}")
                notifs_twitch = []

            # 4. Fusionar y guardar — máx 8 en cola, urgentes primero
            todas = alertas_sistema + novedades + notifs_twitch
            if todas:
                existentes = obtener_pendientes()
                fusionadas = (existentes + todas)[-8:]
                orden = {"URGENTE": 0, "RELEVANTE": 1, "INFORMATIVO": 2}
                fusionadas.sort(key=lambda n: orden.get(n.get("prioridad", "INFORMATIVO"), 2))
                guardar_pendientes(fusionadas)
                mlog("PROACTIVO", f"{len(todas)} notificación(es) guardada(s).")
            else:
                mlog("PROACTIVO", "Sin novedades ni alertas este ciclo.")

        except Exception as e:
            mlog("PROACTIVO", f"Error en ciclo proactivo: {e}")

        time.sleep(_INTERVALO_HORAS * 3600)


def iniciar() -> None:
    t = threading.Thread(target=_loop_proactivo, daemon=True, name="daemon-proactivo")
    t.start()
    mlog("PROACTIVO", f"Daemon proactivo activo — ciclo cada {_INTERVALO_HORAS}h, monitor sistemas cada 30 min.")
