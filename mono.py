"""
NOVA — Monólogo interno
Imprime el log de decisiones de NOVA en tiempo real con formato ANSI
y mantiene un buffer compartido para el HUD.
"""

from collections import deque
from datetime import datetime
import sys

_R = "\033[0m"
_B = "\033[1m"

_COLS = {
    "SISTEMA":  "\033[97m",
    "ESCUCHA":  "\033[96m",
    "ANÁLISIS": "\033[93m",
    "MEMORIA":  "\033[94m",
    "RED":      "\033[34m",
    "NÚCLEO":   "\033[95m",
    "LOCAL":    "\033[95m",
    "ORACLE":   "\033[35m",
    "PROCESO":  "\033[93m",
    "SÍNTESIS": "\033[92m",
    "AUDIO":    "\033[92m",
    "CICLO":    "\033[92m",
    "MOTOR":    "\033[96m",
    "ERROR":    "\033[91m",
}

_buffer: deque = deque(maxlen=8)

def get_buffer() -> list:
    return list(_buffer)

def log(modulo: str, mensaje: str) -> None:
    ts    = datetime.now().strftime("%H:%M:%S")
    color = _COLS.get(modulo.upper(), "\033[97m")
    mod   = f"{modulo.upper():<9}"
    print(f"\033[90m[{ts}]\033[0m {color}{_B}◈ {mod}{_R}\033[90m │\033[0m {mensaje}", flush=True)
    _buffer.append({"ts": ts, "mod": modulo.upper(), "msg": mensaje})
def log(modulo: str, mensaje: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    color = _COLS.get(modulo.upper(), "\033[97m")
    mod = f"{modulo.upper():<9}"
    line = f"\033[90m[{ts}]\033[0m {color}{_B}* {mod}{_R}\033[90m |\033[0m {mensaje}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((line + '\n').encode(sys.stdout.encoding or 'utf-8', errors='replace'))
        sys.stdout.flush()
    _buffer.append({"ts": ts, "mod": modulo.upper(), "msg": mensaje})
