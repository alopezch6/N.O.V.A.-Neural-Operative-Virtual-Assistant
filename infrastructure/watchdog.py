"""
NOVA — Watchdog PC local
Monitoriza nova.py, Ollama y conectividad con Oracle.
Se lanza desde iniciar_nova.bat con pythonw.exe (sin consola).
"""
import time
import subprocess
import sys
import requests
import psutil
from datetime import datetime
from pathlib import Path

# ── Config (inline para no depender de config.py y sus side-effects) ──────────
import os
from dotenv import load_dotenv
load_dotenv(Path("B:/NOVA/.env"))

_TG_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT       = int(os.getenv("TELEGRAM_ALLOWED_ID", "0"))
_ORACLE_TELEM  = "http://100.111.223.84:9100/telemetria"
_ORACLE_ALMACEN= "http://100.111.223.84:9101/almacen/ping"
_LOCAL_HEALTH  = "http://127.0.0.1:5000/health"
_LOCAL_OLLAMA  = "http://127.0.0.1:11434/api/tags"
_NOVA_DIR      = Path("B:/NOVA")
_NOVA_PY       = _NOVA_DIR / "nova.py"
_PYTHON        = r"C:\Users\Alex\AppData\Local\Programs\Python\Python311\python.exe"
_INTERVAL      = 60   # segundos entre chequeos
_STARTUP_WAIT  = 40   # espera inicial para que nova.py y Ollama carguen

_prev: dict[str, bool] = {}


# ── Telegram ──────────────────────────────────────────────────────────────────

def _tg(msg: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
            json={"chat_id": _TG_CHAT, "text": msg},
            timeout=6,
        )
    except Exception:
        pass


# ── Checks individuales ───────────────────────────────────────────────────────

def _check_oracle() -> bool:
    try:
        r = requests.get(_ORACLE_TELEM, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _check_almacen() -> bool:
    try:
        r = requests.get(_ORACLE_ALMACEN, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _check_hud() -> bool:
    try:
        r = requests.get(_LOCAL_HEALTH, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _check_ollama() -> bool:
    try:
        r = requests.get(_LOCAL_OLLAMA, timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _check_nova_process() -> bool:
    for proc in psutil.process_iter(['cmdline']):
        try:
            cmd = proc.info.get('cmdline') or []
            if any('nova.py' in c for c in cmd):
                return True
        except Exception:
            pass
    return False


# ── Auto-restart ──────────────────────────────────────────────────────────────

def _restart_nova() -> bool:
    if not _NOVA_PY.exists():
        return False
    try:
        subprocess.Popen(
            [_PYTHON, str(_NOVA_PY)],
            cwd=str(_NOVA_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    except Exception:
        return False


# ── Lógica de alerta con detección de cambio de estado ───────────────────────

def _check_and_alert(nombre: str, ok: bool, reiniciar_fn=None) -> None:
    prev = _prev.get(nombre)
    ts = datetime.now().strftime("%H:%M:%S")

    if prev is None:
        _prev[nombre] = ok
        return

    if prev and not ok:
        msg = f"⚠️ NOVA | {nombre} ha caído [{ts}]"
        if reiniciar_fn:
            ok_restart = reiniciar_fn()
            msg += "\n🔄 Reinicio automático: " + ("OK — arrancando..." if ok_restart else "FALLIDO")
        _tg(msg)

    elif not prev and ok:
        _tg(f"✅ NOVA | {nombre} de nuevo en línea [{ts}]")

    _prev[nombre] = ok


# ── Loop principal ─────────────────────────────────────────────────────────────

def run() -> None:
    _tg(f"🟢 NOVA Watchdog PC local iniciado [{datetime.now().strftime('%H:%M:%S')}]")
    time.sleep(_STARTUP_WAIT)  # espera a que nova.py y Ollama carguen completamente

    while True:
        _check_and_alert("Oracle — Telemetría (9100)",  _check_oracle())
        _check_and_alert("Oracle — Almacén (9101)",     _check_almacen())
        _check_and_alert("Servidor HUD local (5000)",   _check_hud())
        _check_and_alert("Ollama local (11434)",        _check_ollama())
        _check_and_alert("NOVA proceso principal",      _check_nova_process(), _restart_nova)
        time.sleep(_INTERVAL)


if __name__ == "__main__":
    run()
