import subprocess, os, sys, json, re
from pathlib import Path

DESCRIPTION = "Mata procesos del bot según un patrón"
KEYWORDS = ["matar procesos del bot", "kill procesos bot", "terminar procesos bot", "eliminar procesos bot"]
NEEDS_CONFIRM = True

import os, re, psutil

def ejecutar(params: dict) -> str:
    try:
        txt = params.get("text", "")
        m = re.search(r"matar\s+(\w+)", txt, re.I)
        pattern = m.group(1) if m else "python"
        killed = []
        for p in psutil.process_iter(['pid','name','cmdline']):
            try:
                name = p.info['name'] or ""
                cmd = " ".join(p.info['cmdline'] or [])
                if pattern.lower() in name.lower() or pattern.lower() in cmd.lower():
                    if p.pid != os.getpid():
                        p.kill()
                        killed.append(f"{p.pid}:{name}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return f"Procesos muertos: {', '.join(killed)}" if killed else "No se encontraron procesos que coincidan."
    except Exception as e:
        return f"Error al matar procesos: {e}"