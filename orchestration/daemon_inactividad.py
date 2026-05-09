"""
NOVA — Daemon de inactividad
Detecta periodos sin actividad y ejecuta investigación autónoma.
Genera el informe nocturno de lo aprendido.
"""

import threading
import time
from datetime import date
from pathlib import Path

from memory import memoria_profunda as _mp
from mono import log as mlog

_BASE = Path(__file__).resolve().parents[1]

_UMBRAL_INACTIVIDAD = 30 * 60  # 30 min de silencio → activar investigación
_INTERVALO_CHECK    =  5 * 60  # Comprobar cada 5 min
_COOLDOWN_INVEST    = 60 * 60  # Mínimo 1h entre investigaciones

_ultima_actividad     = time.time()
_ultima_investigacion = 0.0
_daemon_iniciado      = False
_lock = threading.Lock()


def registrar_actividad() -> None:
    """Llamar cada vez que Alex interactúa con NOVA."""
    global _ultima_actividad
    _ultima_actividad = time.time()


# ── Investigación autónoma ────────────────────────────────────────────────────

def _temas_investigacion() -> list[str]:
    """Temas basados en conversaciones recientes + intereses base de Alex."""
    temas = []
    try:
        turnos = _mp.historial_reciente(n=20)
        temas = [t["contenido"][:60] for t in turnos if t["rol"] == "user"][-3:]
    except Exception:
        pass
    temas += [
        "noticias inteligencia artificial esta semana",
        "World of Warcraft The War Within actualizaciones",
        "Valorant parche novedades",
    ]
    return temas[:5]


def _investigar_tema(tema: str) -> str | None:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            resultados = list(ddgs.text(tema, max_results=3, region="es-es"))
        partes = []
        for r in resultados[:2]:
            titulo = r.get("title", "")
            body   = r.get("body", "")[:200]
            if titulo:
                partes.append(f"{titulo}: {body}")
        return " | ".join(partes) if partes else None
    except Exception:
        return None


def _ejecutar_investigacion() -> int:
    global _ultima_investigacion
    _ultima_investigacion = time.time()

    hallazgos = 0
    for tema in _temas_investigacion():
        mlog("DAEMON", f"Investigando: {tema[:50]}")
        resultado = _investigar_tema(tema)
        if resultado:
            _mp.guardar_turno(
                rol="aprendizaje",
                contenido=f"[{tema[:40]}] {resultado}",
                session_id="daemon",
                canal="sistema",
                tipo="aprendizaje",
            )
            hallazgos += 1
            time.sleep(2)  # rate limiting

    mlog("DAEMON", f"Investigación completada: {hallazgos} hallazgos")
    return hallazgos


def _bucle_daemon() -> None:
    mlog("DAEMON", "Daemon de inactividad iniciado")
    while True:
        try:
            time.sleep(_INTERVALO_CHECK)
            ahora          = time.time()
            inactivo_desde = ahora - _ultima_actividad
            cooldown_ok    = (ahora - _ultima_investigacion) > _COOLDOWN_INVEST

            if inactivo_desde > _UMBRAL_INACTIVIDAD and cooldown_ok:
                mlog("DAEMON", f"Inactivo {int(inactivo_desde / 60)} min → investigando")
                threading.Thread(target=_ejecutar_investigacion, daemon=True).start()
        except Exception as e:
            mlog("DAEMON", f"Error en bucle: {e}")


def iniciar_daemon() -> None:
    """Arranca el daemon en background. Idempotente."""
    global _daemon_iniciado
    with _lock:
        if _daemon_iniciado:
            return
        _daemon_iniciado = True
    threading.Thread(target=_bucle_daemon, daemon=True).start()


# ── Informe nocturno ──────────────────────────────────────────────────────────

def generar_informe_nocturno() -> str:
    hoy          = date.today().isoformat()
    aprendizajes = _mp.aprendizajes_hoy()
    stats        = _mp.estadisticas()
    total_7d     = stats.get("ultimos_7_dias", 0)

    if not aprendizajes:
        return (
            f"🌙 *Informe nocturno — {hoy}*\n\n"
            f"Sin periodos de inactividad prolongada hoy.\n"
            f"Conversaciones registradas (últimos 7 días): {total_7d}\n\n"
            f"_Sistema nominal._"
        )

    lineas = [
        f"🌙 *Informe nocturno — {hoy}*\n",
        f"He investigado {len(aprendizajes)} temas durante los periodos de inactividad:\n",
    ]
    for i, contenido in enumerate(aprendizajes, 1):
        resumen = contenido[:300] + ("…" if len(contenido) > 300 else "")
        lineas.append(f"*{i}.* {resumen}\n")

    lineas.append(f"\n_Conversaciones activas (7 días): {total_7d} · Sistema nominal._")
    return "\n".join(lineas)


async def enviar_informe_nocturno(context) -> None:
    """Callback para el JobQueue de telegram_bot.py — 00:00."""
    from config import TELEGRAM_ALLOWED_ID
    texto = generar_informe_nocturno()
    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_ALLOWED_ID,
            text=texto,
            parse_mode="Markdown",
        )
        mlog("DAEMON", "Informe nocturno enviado")
    except Exception as e:
        mlog("DAEMON", f"Error enviando informe nocturno: {e}")
