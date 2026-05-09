"""
Gestor de tareas autónomas programadas.
NOVA puede registrar tareas que se ejecutan periódicamente sin intervención de Alex.

Ejemplos:
  - "cada 24h revisa el disco de Oracle"
  - "cada 168h (semanal) limpia logs del servidor"

Las tareas se guardan en tareas_autonomas.json.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from mono import log as mlog

_TAREAS_PATH = Path(__file__).resolve().parents[1] / "tareas_autonomas.json"


# ── CRUD ──────────────────────────────────────────────────────────────────────

def _cargar() -> list:
    if _TAREAS_PATH.exists():
        try:
            return json.loads(_TAREAS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _guardar(tareas: list) -> None:
    _TAREAS_PATH.write_text(
        json.dumps(tareas, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def añadir_tarea(descripcion: str, accion: str, intervalo_horas: float) -> dict:
    """
    Registra una nueva tarea autónoma.
    descripcion: qué hace (para mostrar a Alex)
    accion: instrucción que se pasa al bucle agéntico
    intervalo_horas: cada cuántas horas ejecutar
    """
    tareas = _cargar()
    tarea = {
        "id":               len(tareas) + 1,
        "descripcion":      descripcion,
        "accion":           accion,
        "intervalo_horas":  intervalo_horas,
        "creada":           datetime.now().isoformat()[:16],
        "ultima_ejecucion": None,
        "ultimo_resultado": None,
        "activa":           True,
    }
    tareas.append(tarea)
    _guardar(tareas)
    mlog("AUTONOMO", f"Nueva tarea: '{descripcion}' cada {intervalo_horas}h")
    return tarea


def eliminar_tarea(tarea_id: int) -> bool:
    tareas = _cargar()
    for t in tareas:
        if t.get("id") == tarea_id:
            t["activa"] = False
            _guardar(tareas)
            return True
    return False


def listar_tareas() -> list:
    return [t for t in _cargar() if t.get("activa")]


def obtener_resumen_tareas() -> str:
    """Resumen para el system prompt o para mostrar a Alex."""
    activas = listar_tareas()
    if not activas:
        return ""
    lineas = ["Tareas autónomas activas:"]
    for t in activas:
        ultima = t.get("ultima_ejecucion") or "nunca"
        lineas.append(f"- [{t['id']}] {t['descripcion']} (cada {t['intervalo_horas']}h, última: {ultima})")
    return "\n".join(lineas)


# ── Ejecución ─────────────────────────────────────────────────────────────────

def _debe_ejecutar(tarea: dict) -> bool:
    if not tarea.get("activa"):
        return False
    ultima = tarea.get("ultima_ejecucion")
    if not ultima:
        return True
    try:
        dt_ultima = datetime.fromisoformat(ultima)
        horas_pasadas = (datetime.now() - dt_ultima).total_seconds() / 3600
        return horas_pasadas >= tarea["intervalo_horas"]
    except Exception:
        return True


def _ejecutar_tarea(tarea: dict) -> str:
    """Ejecuta la tarea via el bucle agéntico de Hermes3."""
    try:
        from agente import _run_agentic_loop
        resultado = _run_agentic_loop(tarea["accion"])
        if resultado and resultado.get("reply"):
            return resultado["reply"][:300]
    except Exception as e:
        return f"Error: {e}"
    return "Sin resultado."


# ── Daemon ────────────────────────────────────────────────────────────────────

def _loop() -> None:
    while True:
        time.sleep(1800)  # revisar cada 30 minutos
        tareas = _cargar()
        modificado = False
        for tarea in tareas:
            if _debe_ejecutar(tarea):
                mlog("AUTONOMO", f"Ejecutando tarea #{tarea['id']}: '{tarea['descripcion']}'...")
                resultado = _ejecutar_tarea(tarea)
                tarea["ultima_ejecucion"] = datetime.now().isoformat()[:16]
                tarea["ultimo_resultado"] = resultado
                modificado = True
                mlog("AUTONOMO", f"Tarea #{tarea['id']} completada: {resultado[:80]}")
        if modificado:
            _guardar(tareas)


def iniciar() -> None:
    threading.Thread(target=_loop, daemon=True, name="daemon-autonomo").start()
    mlog("AUTONOMO", f"Daemon de tareas autónomas activo. {len(listar_tareas())} tarea(s) registrada(s).")
