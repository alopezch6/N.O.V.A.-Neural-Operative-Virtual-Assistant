"""
Tracker de directos de Twitch.
- Obtiene token OAuth via client_credentials
- Comprueba si streamers de una lista están en directo
- Genera notificaciones para daemon_proactivo

Lista de streamers en B:/NOVA/twitch_streamers.json
"""

import json
import time
import requests
from pathlib import Path
from datetime import datetime
from mono import log as mlog

_STREAMERS_PATH = Path(__file__).resolve().parents[1] / "twitch_streamers.json"
_TOKEN_CACHE    = {"token": None, "expires": 0.0}

# Streamers por defecto para Alex (puede editar twitch_streamers.json)
_STREAMERS_DEFAULT = [
    "ibai", "auronplay", "xokas", "illojuan", "rivers_gg",
    "elxokas", "willyrex", "vegetta777"
]


def _cargar_streamers() -> list[str]:
    if _STREAMERS_PATH.exists():
        try:
            return json.loads(_STREAMERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Crear archivo por defecto
    _STREAMERS_PATH.write_text(
        json.dumps(_STREAMERS_DEFAULT, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return _STREAMERS_DEFAULT


def _get_token() -> str | None:
    from config import TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        return None

    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires"]:
        return _TOKEN_CACHE["token"]

    try:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            data={
                "client_id":     TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type":    "client_credentials",
            },
            timeout=5,
        )
        if r.status_code == 200:
            d = r.json()
            _TOKEN_CACHE["token"]   = d["access_token"]
            _TOKEN_CACHE["expires"] = now + d.get("expires_in", 3600) - 60
            return _TOKEN_CACHE["token"]
    except Exception as e:
        mlog("TWITCH", f"Error obteniendo token: {e}")
    return None


def obtener_directos() -> list[dict]:
    """
    Devuelve lista de streamers en directo.
    Cada elemento: {"nombre": str, "juego": str, "titulo": str, "viewers": int}
    """
    from config import TWITCH_CLIENT_ID
    token = _get_token()
    if not token:
        return []

    streamers = _cargar_streamers()
    if not streamers:
        return []

    try:
        # Batched query: hasta 100 streamers por petición
        params = [("user_login", s.lower()) for s in streamers[:20]]
        r = requests.get(
            "https://api.twitch.tv/helix/streams",
            params=params,
            headers={
                "Client-ID":    TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {token}",
            },
            timeout=5,
        )
        if r.status_code != 200:
            return []

        directos = []
        for stream in r.json().get("data", []):
            directos.append({
                "nombre":  stream["user_name"],
                "juego":   stream.get("game_name", ""),
                "titulo":  stream.get("title", "")[:80],
                "viewers": stream.get("viewer_count", 0),
            })
        return directos

    except Exception as e:
        mlog("TWITCH", f"Error consultando streams: {e}")
        return []


# Estado de directos para detectar cambios (nuevo directo = notificación)
_estado_anterior: set = set()


def generar_notificaciones_twitch() -> list[dict]:
    """
    Compara estado actual con anterior.
    Devuelve notificaciones solo para streamers que ACABAN de empezar.
    """
    global _estado_anterior

    directos = obtener_directos()
    if not directos:
        return []

    actuales = {d["nombre"].lower() for d in directos}
    nuevos   = actuales - _estado_anterior
    _estado_anterior = actuales

    notificaciones = []
    for d in directos:
        if d["nombre"].lower() in nuevos:
            viewers = d["viewers"]
            juego   = f" jugando a {d['juego']}" if d["juego"] else ""
            info    = f"{d['nombre']} acaba de empezar directo en Twitch{juego} ({viewers:,} viewers)."
            notificaciones.append({
                "prioridad": "RELEVANTE",
                "tema":      f"Twitch – {d['nombre']}",
                "info":      info,
                "ts":        datetime.now().isoformat(),
            })
            mlog("TWITCH", info)

    return notificaciones
