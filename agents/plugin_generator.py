"""
NOVA — Generador de plugins
Crea plugins Python a partir de una descripción en lenguaje natural via Groq.
Cada plugin generado se guarda en plugins/ y se carga dinámicamente.
"""
import ast
import re
from pathlib import Path

from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from mono import log as mlog

_BASE = Path(__file__).resolve().parents[1]
_PLUGINS_DIR = _BASE / "plugins"

# Imports que todo plugin necesita — se inyectan si no están ya en el código generado
_IMPORTS_HEADER = (
    "import subprocess, os, sys, json, re\n"
    "from pathlib import Path\n\n"
)

_groq = Groq(api_key=GROQ_API_KEY)

_SYSTEM_PROMPT = """\
Eres un generador de plugins para NOVA, un asistente personal en Python que corre en DOS nodos:
- Nodo Windows 11 (PC de Alex, RTX 2070 Super)
- Nodo Oracle Ubuntu ARM (servidor cloud)

El MISMO archivo de plugin se ejecuta en ambos nodos. Genera código que funcione en los dos usando
detección de plataforma (sys.platform == "win32" para Windows, else Linux/Oracle).

ESTRUCTURA OBLIGATORIA — copia este esqueleto y rellénalo:

DESCRIPTION = "qué hace este plugin en una línea"
KEYWORDS = ["frase exacta que el usuario escribiría", "variante1", "variante2", "variante3"]
NEEDS_CONFIRM = False  # True solo si la acción es destructiva o irreversible

def ejecutar(params: dict) -> str:
    import sys
    # params["text"] contiene el mensaje original del usuario
    if sys.platform == "win32":
        # Código específico Windows
        pass
    else:
        # Código específico Linux/Oracle
        pass
    return "resultado para el usuario"

REGLAS DE CÓDIGO:
- Usa solo: stdlib Python + subprocess, os, pathlib, psutil, requests, json, re
- Windows: usa PowerShell, wmic, nvidia-smi, tasklist, psutil, winreg (con cuidado)
- Linux/Oracle: usa systemctl, ps, df, free, journalctl, pgrep, pkill
- Para temperatura CPU en Windows: psutil.sensors_temperatures() o WMI MSAcpi_ThermalZoneTemperature
- Para temperatura GPU NVIDIA (Windows): nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits
- Para temperatura en Linux: psutil.sensors_temperatures() o /sys/class/thermal/
- Sin input(), sin bucles infinitos, sin operaciones de red sin timeout (usa timeout=5)
- Captura siempre las excepciones y devuelve un mensaje de error claro si algo falla
- Máximo 35 líneas dentro de ejecutar()
- NEEDS_CONFIRM = True para: matar procesos, reboot, shutdown, borrar archivos

KEYWORDS — OBLIGATORIO incluir MÍNIMO 12 variantes que cubran TODAS las formas en que Alex
podría pedir esto. Incluye siempre:
  1. La frase exacta que activó la petición
  2. Forma imperativa corta: "dime X", "muéstrame X"
  3. Forma imperativa larga: "puedes decirme X", "puedes mostrarme X"
  4. Forma con artículo: "la X del sistema", "el X del pc"
  5. Forma sin verbo: solo "X del sistema", "X actual"
  6. Forma con "obtener/ver/consultar": "ver X", "obtener X", "consultar X"
  7. Forma con "cuánto/cuál/qué": "cuánta X", "cuál es X", "qué X tiene"
  8. Forma con "del pc/del ordenador/del sistema": todas las variantes
  9. Forma con "y": "y dime X", "y la X"
  10. Variantes con y sin tildes/acentos (si aplica)
  11. Forma con "ahora": "X ahora", "dime X ahora"
  12. Cualquier otra variante natural relevante

Ejemplo para temperatura:
KEYWORDS = [
    "temperatura del sistema", "temperatura del pc", "temperatura del ordenador",
    "dime la temperatura", "muéstrame la temperatura", "puedes decirme la temperatura",
    "cuál es la temperatura", "qué temperatura tiene", "temperatura actual",
    "ver temperatura", "obtener temperatura", "temperatura ahora",
    "temperatura cpu", "temperatura gpu", "cuánto calor tiene el pc",
    "y dime la temperatura", "y la temperatura", "temperatura"
]

Responde ÚNICAMENTE con el código Python del plugin.
Sin bloques markdown, sin explicaciones, sin comentarios extra fuera del código.\
"""


def _limpiar_codigo(raw: str) -> str:
    """Elimina envolturas markdown y texto suelto antes/después del código."""
    code = raw.strip()
    # Extraer bloque de código si viene con ```
    match = re.search(r"```(?:python)?\n?(.*?)```", code, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Si no hay ```, limpiar restos de ``` individuales
    code = re.sub(r"```\w*", "", code).strip()
    return code


def _validar(code: str) -> str | None:
    """Devuelve mensaje de error o None si el código es válido."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"Sintaxis incorrecta: {e}"
    if "KEYWORDS" not in code:
        return "El código no contiene KEYWORDS"
    if "def ejecutar" not in code:
        return "El código no contiene la función ejecutar()"
    return None


def generar_plugin(descripcion: str) -> tuple[str, str] | tuple[None, str]:
    """
    Genera código de plugin a partir de una descripción en lenguaje natural.
    Intenta hasta 2 veces si el LLM produce código con errores.
    Returns: (codigo, nombre_archivo) si OK, o (None, mensaje_error) si falla.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", descripcion.lower()).strip("_")[:45]
    filename = f"{slug}.py"
    ultimo_error = "Error desconocido"

    for intento in range(1, 3):
        try:
            resp = _groq.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f"Genera el plugin para: {descripcion}"},
                ],
                max_tokens=900,
                temperature=0.1 * intento,  # Sube un poco en el reintento
            )
            raw = resp.choices[0].message.content.strip()
            code = _limpiar_codigo(raw)
            error = _validar(code)
            if error:
                mlog("PLUGINS", f"Intento {intento} fallido: {error}")
                ultimo_error = error
                continue
            mlog("PLUGINS", f"Plugin generado OK (intento {intento}) → {filename} ({len(code)} chars)")
            return code, filename
        except Exception as e:
            mlog("PLUGINS", f"Error en intento {intento}: {e}")
            ultimo_error = str(e)

    return None, ultimo_error


def guardar_plugin(code: str, filename: str) -> None:
    """Escribe el plugin en plugins/. Inyecta imports estándar si faltan."""
    _PLUGINS_DIR.mkdir(exist_ok=True)
    if "import subprocess" not in code:
        code = _IMPORTS_HEADER + code
    path = _PLUGINS_DIR / filename
    path.write_text(code, encoding="utf-8")
    mlog("PLUGINS", f"Plugin guardado en {path}")
