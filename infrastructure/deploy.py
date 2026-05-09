"""
NOVA — Deploy
Sincroniza todos los .py del PC local → Oracle y reinicia los servicios.
Puede usarse como script (python deploy.py) o importarse desde acciones/servidor.
"""
import subprocess
from pathlib import Path

_BASE     = Path(__file__).parent
_SSH_KEY  = _BASE / "ssh-key-2026-04-18.key"
_SSH_HOST = "ubuntu@92.5.116.97"
_REMOTE   = "/home/ubuntu/nova"
_SERVICIOS = ["nova-almacen", "nova-telegram"]

# Archivos que nunca se sincronizan a Oracle (solo tienen sentido en local)
_EXCLUIDOS = {"voz.py", "nova.py"}


def _ssh(cmd: str, timeout: int = 30) -> tuple[int, str]:
    r = subprocess.run(
        ["ssh", "-i", str(_SSH_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=8", _SSH_HOST, cmd],
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def ejecutar_deploy() -> str:
    """Sincroniza código y reinicia Oracle. Devuelve resumen legible."""
    if not _SSH_KEY.exists():
        return "No encuentro la clave SSH. Verifica que está en B:\\NOVA\\ssh-key-2026-04-18.key"

    archivos = sorted(
        f for f in _BASE.glob("*.py") if f.name not in _EXCLUIDOS
    )
    if not archivos:
        return "No hay archivos .py para sincronizar."

    # 1 — SCP todos los .py elegibles
    r = subprocess.run(
        ["scp", "-i", str(_SSH_KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=8"]
        + [str(f) for f in archivos]
        + [f"{_SSH_HOST}:{_REMOTE}/"],
        capture_output=True, text=True, timeout=90,
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        return f"Error al copiar archivos: {(r.stdout + r.stderr).strip()[:300]}"

    n = len(archivos)

    # 2 — Reiniciar servicios
    restart_cmd = " && ".join(f"sudo systemctl restart {s}" for s in _SERVICIOS)
    code, out = _ssh(restart_cmd, timeout=30)
    if code != 0:
        return f"{n} archivos sincronizados, pero falló el reinicio: {out[:200]}"

    # 3 — Invalidar caché de autoconocimiento para forzar re-aprendizaje
    _ssh("rm -f /home/ubuntu/nova/self_knowledge.json /home/ubuntu/nova/self_summary.json")

    # 4 — Verificar estado final
    _, estados = _ssh(
        "systemctl is-active " + " ".join(_SERVICIOS),
        timeout=10,
    )
    estado_str = " / ".join(
        f"{s}: {e}" for s, e in zip(_SERVICIOS, estados.splitlines())
    )

    return f"Deploy completado. {n} archivos → Oracle. {estado_str}. Autoconocimiento invalidado — NOVA re-aprenderá en la próxima consulta."


if __name__ == "__main__":
    print(ejecutar_deploy())
