"""
Módulo de presencia y actividad de Alex.
- Detecta si está activo en el PC via última entrada de teclado/ratón
- Detecta qué juego/app tiene en ejecución
- Expone helpers para que NOVA adapte su comportamiento
"""

import ctypes
import time
from mono import log as mlog

_JUEGOS = {
    "wow.exe":                "World of Warcraft",
    "wowclassic.exe":         "WoW Classic",
    "valorant.exe":           "Valorant",
    "valorant-win64-shipping.exe": "Valorant",
    "leagueclient.exe":       "League of Legends",
    "league of legends.exe":  "League of Legends",
    "cs2.exe":                "CS2",
    "csgo.exe":               "CS2",
    "rustclient.exe":         "Rust",
    "rust.exe":               "Rust",
    "discord.exe":            "Discord",
    "steam.exe":              "Steam",
    "epicgameslauncher.exe":  "Epic Games",
    "fortnite.exe":           "Fortnite",
    "minecraft.exe":          "Minecraft",
    "javaw.exe":              "Minecraft",
}

_cache = {"juego": None, "ts": 0.0}
_CACHE_TTL = 30.0


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _segundos_desde_ultimo_input() -> float:
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
        return millis / 1000.0
    except Exception:
        return 0.0


def esta_activo(umbral_segundos: int = 300) -> bool:
    """True si Alex ha tenido actividad en los últimos N segundos (5 min por defecto)."""
    return _segundos_desde_ultimo_input() < umbral_segundos


def obtener_juego_activo() -> str | None:
    """Devuelve el nombre del juego en ejecución, o None. Cacheado 30s."""
    now = time.time()
    if now - _cache["ts"] < _CACHE_TTL:
        return _cache["juego"]

    juego = None
    try:
        import psutil
        for proc in psutil.process_iter(["name"]):
            nombre = (proc.info["name"] or "").lower()
            match = _JUEGOS.get(nombre)
            if match:
                juego = match
                break
    except Exception:
        pass

    _cache["juego"] = juego
    _cache["ts"] = now
    return juego


def obtener_actividad_actual() -> str:
    """Descripción concisa de la actividad actual de Alex."""
    juego = obtener_juego_activo()
    if juego:
        return f"Alex está jugando a {juego} en este momento."

    inactivo = _segundos_desde_ultimo_input()
    if inactivo < 120:
        return "Alex está activo en el PC."
    elif inactivo < 600:
        return f"Alex lleva {int(inactivo // 60)} minutos sin actividad en el PC."
    else:
        horas = inactivo / 3600
        if horas >= 1:
            return f"Alex lleva aproximadamente {int(horas)} hora(s) sin actividad — posiblemente no está."
        return f"Alex lleva {int(inactivo // 60)} minutos sin actividad."


def contexto_para_nova() -> str:
    """Devuelve una línea de contexto para inyectar en el system prompt."""
    juego = obtener_juego_activo()
    inactivo = _segundos_desde_ultimo_input()

    if juego:
        return f"PRESENCIA: Alex está jugando a {juego}. Si no es urgente, sé breve para no interrumpir."
    if inactivo > 3600:
        return "PRESENCIA: Alex lleva más de una hora sin actividad en el PC — puede que no esté delante."
    if inactivo < 60:
        return "PRESENCIA: Alex acaba de interactuar con el PC hace menos de un minuto."
    return ""
