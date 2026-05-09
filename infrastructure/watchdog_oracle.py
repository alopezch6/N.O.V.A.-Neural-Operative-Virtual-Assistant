"""
NOVA — Watchdog Oracle
Monitoriza servicios systemd en Oracle y conectividad con el PC local.
Diseñado para correr como cron cada minuto:
  */1 * * * * /usr/bin/python3 /home/ubuntu/nova/watchdog_oracle.py

Estado persistente en .watchdog_state.json para detectar cambios entre ejecuciones.
"""
import json
import subprocess
import requests
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_TG_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN", "")
_TG_CHAT     = int(os.getenv("TELEGRAM_ALLOWED_ID", "0"))
_PC_HEALTH   = "http://100.68.163.22:5000/health"   # PC local vía Tailscale
_SERVICIOS   = ["nova-almacen", "nova-telegram"]
_STATE_FILE  = Path("/home/ubuntu/nova/.watchdog_state.json")


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


# ── Estado persistente ────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


# ── Umbrales de recursos ──────────────────────────────────────────────────────
_RAM_WARN   = 88   # %
_DISCO_WARN = 85   # %
_CPU_WARN   = 90   # %
_LOG_ERRORS_WARN = 5  # líneas ERROR/CRITICAL/Traceback en las últimas 100


# ── Checks ────────────────────────────────────────────────────────────────────

def _service_active(name: str) -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True, text=True,
    )
    return r.stdout.strip() == "active"


def _restart_service(name: str) -> bool:
    r = subprocess.run(
        ["sudo", "systemctl", "restart", name],
        capture_output=True, text=True, timeout=15,
    )
    return r.returncode == 0


def _check_pc() -> bool:
    try:
        r = requests.get(_PC_HEALTH, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _check_recursos() -> dict:
    """RAM, disco y CPU via shell. Devuelve porcentajes (o None si falla)."""
    result: dict = {}
    try:
        r = subprocess.run(["free", "-b"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                result["ram_pct"] = round(int(parts[2]) / int(parts[1]) * 100)
                break
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["df", "/", "--output=pcent"], capture_output=True, text=True, timeout=5
        )
        lines = r.stdout.strip().splitlines()
        if len(lines) >= 2:
            result["disco_pct"] = int(lines[1].strip().rstrip("%"))
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["sh", "-c", "vmstat 1 2 | awk 'NR==4{print 100-$15}'"],
            capture_output=True, text=True, timeout=12,
        )
        val = r.stdout.strip()
        if val.lstrip("-").isdigit():
            result["cpu_pct"] = max(0, int(val))
    except Exception:
        pass
    return result


def _check_log_errors() -> int:
    """Cuenta líneas ERROR/CRITICAL/Traceback en los últimos 100 mensajes de journal."""
    try:
        r = subprocess.run(
            ["journalctl", "-u", "nova-almacen", "-u", "nova-telegram",
             "-n", "100", "--no-pager"],
            capture_output=True, text=True, timeout=10,
        )
        return sum(
            1 for line in r.stdout.splitlines()
            if any(k in line for k in (" ERROR ", "CRITICAL", "Traceback"))
        )
    except Exception:
        return 0


# ── Lógica de alerta ──────────────────────────────────────────────────────────

def _alert_transition(nombre: str, ok: bool, prev: bool | None, ts: str,
                       reiniciar_fn=None) -> bool:
    """Envía Telegram si el estado cambió. Devuelve el nuevo estado efectivo."""
    if prev is None:
        return ok  # primera ejecución: guardamos sin alertar

    if prev and not ok:
        msg = f"⚠️ NOVA | {nombre} caído en Oracle [{ts}]"
        if reiniciar_fn:
            ok_restart = reiniciar_fn()
            msg += "\n🔄 Reinicio automático: " + ("OK" if ok_restart else "FALLIDO")
            return ok_restart  # si reinició exitosamente, consideramos activo
        _tg(msg)
        return False

    if not prev and ok:
        _tg(f"✅ NOVA | {nombre} de nuevo activo [{ts}]")

    return ok


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    state = _load_state()
    ts = datetime.now().strftime("%H:%M:%S")
    changed = False

    # Primera ejecución: anunciarse
    if not state:
        _tg(f"🟢 NOVA Watchdog Oracle iniciado [{ts}]")

    # ── Servicios systemd ──────────────────────────────────────────────────────
    for svc in _SERVICIOS:
        ok = _service_active(svc)
        prev = state.get(svc)
        nuevo = _alert_transition(
            nombre=f"Servicio {svc}",
            ok=ok,
            prev=prev,
            ts=ts,
            reiniciar_fn=lambda s=svc: _restart_service(s),
        )
        if nuevo != prev:
            changed = True
        state[svc] = nuevo

    # ── PC local vía Tailscale ─────────────────────────────────────────────────
    pc_ok = _check_pc()
    prev_pc = state.get("pc_local")
    nuevo_pc = _alert_transition(
        nombre="PC local (Tailscale)",
        ok=pc_ok,
        prev=prev_pc,
        ts=ts,
    )
    if nuevo_pc != prev_pc:
        changed = True
    state["pc_local"] = nuevo_pc

    # ── Recursos: RAM, disco, CPU ──────────────────────────────────────────────
    recursos = _check_recursos()

    for clave, umbral, label in (
        ("ram_pct",   _RAM_WARN,   "RAM"),
        ("disco_pct", _DISCO_WARN, "Disco"),
        ("cpu_pct",   _CPU_WARN,   "CPU"),
    ):
        val = recursos.get(clave)
        if val is None:
            continue
        alta = val >= umbral
        prev_alta = state.get(f"{clave}_alta")
        # Alerta solo en transición bajo→alto (evitar spam)
        if alta and not prev_alta:
            _tg(f"⚠️ NOVA | {label} al {val}% en Oracle [{ts}]")
        elif not alta and prev_alta:
            _tg(f"✅ NOVA | {label} normalizado ({val}%) [{ts}]")
        if alta != prev_alta:
            changed = True
        state[f"{clave}_alta"] = alta

    # ── Errores en logs ────────────────────────────────────────────────────────
    n_errors = _check_log_errors()
    prev_errors_alta = state.get("log_errors_alta", False)
    errors_alta = n_errors >= _LOG_ERRORS_WARN
    if errors_alta and not prev_errors_alta:
        _tg(f"⚠️ NOVA | {n_errors} errores recientes en logs de Oracle [{ts}]")
    elif not errors_alta and prev_errors_alta:
        _tg(f"✅ NOVA | Logs de Oracle normalizados [{ts}]")
    if errors_alta != prev_errors_alta:
        changed = True
    state["log_errors_alta"] = errors_alta

    if changed or not _STATE_FILE.exists():
        _save_state(state)


if __name__ == "__main__":
    main()
