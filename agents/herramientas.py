"""
Herramientas del bucle agéntico de NOVA.
Cada tool define su riesgo y proporciona su schema OpenAI para tool calling.
"""

import re
import subprocess
import requests
from pathlib import Path

SAFE    = "safe"
CONFIRM = "confirm"

# Patrones de comandos que siempre requieren confirmación del usuario
_CMD_CONFIRM = [
    r"\brm\b", r"\bdel\s", r"\brmdir\b", r"\brd\s+/s\b",
    r"\bformat\b",
    r"\bshutdown\b", r"\brestart-computer\b",
    r"\bpip\s+(install|uninstall)\b",
    r"\bssh\b", r"100\.111\.223\.84",   # Oracle via Tailscale
    r"\bwsl\b.*-e\b",
    r"\bnetsh\b", r"\btaskkill\b",
    r"\breg\s+(add|delete|import|export)\b",
    r"\bschtasks\b",
    r"\bpowershell\b.*-encodedcommand\b",
    r"\bcurl\b.*\|\s*(bash|sh)\b",
    r"\bscp\b", r"\brsync\b",
]


def _cmd_risk(cmd: str) -> tuple[str, str]:
    for p in _CMD_CONFIRM:
        if re.search(p, cmd, re.IGNORECASE):
            return CONFIRM, f"Ejecutar: {cmd[:100]}"
    return SAFE, ""


def riesgo_accion(tool_name: str, args: dict) -> tuple[str, str]:
    """Devuelve (nivel, descripcion_legible). nivel: 'safe' | 'confirm'."""
    if tool_name in ("leer_fichero", "buscar_web", "fetch_url",
                     "buscar_ficheros", "grep_en_ficheros"):
        return SAFE, ""

    if tool_name == "editar_fichero":
        path   = args.get("path", "")
        buscar = args.get("buscar", "")[:40]
        nueva  = args.get("reemplazar", "")[:40]
        return CONFIRM, f"editar {path}: «{buscar}» → «{nueva}»"

    if tool_name == "escribir_fichero":
        path   = args.get("path", "")
        lineas = args.get("contenido", "").count("\n") + 1
        return CONFIRM, f"escribir {path} ({lineas} líneas)"

    if tool_name == "ejecutar_comando":
        return _cmd_risk(args.get("cmd", ""))

    return SAFE, ""


# ── Implementaciones ──────────────────────────────────────────────────────────

def leer_fichero(path: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"[ERROR] Fichero no encontrado: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > 8000:
            content = content[:8000] + "\n... [truncado a 8000 caracteres]"
        return content
    except Exception as e:
        return f"[ERROR] {e}"


def escribir_fichero(path: str, contenido: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(contenido, encoding="utf-8")
        return f"Fichero escrito correctamente: {path}"
    except Exception as e:
        return f"[ERROR] {e}"


def editar_fichero(path: str, buscar: str, reemplazar: str) -> str:
    try:
        p = Path(path)
        if not p.exists():
            return f"[ERROR] Fichero no encontrado: {path}"
        content = p.read_text(encoding="utf-8", errors="replace")
        if buscar not in content:
            return f"[ERROR] Texto no encontrado en {path}: {buscar[:60]!r}"
        new_content = content.replace(buscar, reemplazar, 1)
        p.write_text(new_content, encoding="utf-8")
        return f"Editado correctamente: {path}"
    except Exception as e:
        return f"[ERROR] {e}"


def ejecutar_comando(cmd: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
        )
        output = (result.stdout + result.stderr).strip()
        return output or "(sin salida)"
    except subprocess.TimeoutExpired:
        return f"[ERROR] Timeout: el comando tardó más de {timeout}s"
    except Exception as e:
        return f"[ERROR] {e}"


def buscar_web(query: str) -> str:
    # Tavily primero (diseñado para IA, resultados actuales y precisos)
    try:
        from config import TAVILY_API_KEY
        if TAVILY_API_KEY:
            from tavily import TavilyClient
            from datetime import datetime
            hoy    = datetime.now().strftime("%d de %B de %Y")
            client = TavilyClient(api_key=TAVILY_API_KEY)
            result = client.search(f"{query} {hoy}", max_results=5, search_depth="advanced")
            partes = []
            for r in (result.get("results") or [])[:5]:
                titulo    = r.get("title", "")
                contenido = (r.get("content") or r.get("snippet") or "")[:300]
                if titulo or contenido:
                    partes.append(f"- {titulo}: {contenido}" if titulo else f"- {contenido}")
            if partes:
                return "\n".join(partes)
    except Exception:
        pass

    # Fallback a DuckDuckGo
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=5):
                results.append(f"- {r['title']}: {r['body'][:200]}")
        return "\n".join(results) if results else "Sin resultados."
    except Exception as e:
        return f"[ERROR] {e}"


def fetch_url(url: str) -> str:
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "NOVA/1.0"})
        text = re.sub(r'<[^>]+>', ' ', r.text)
        text = re.sub(r'\s+', ' ', text).strip()
        if len(text) > 5000:
            text = text[:5000] + "\n... [truncado]"
        return text
    except Exception as e:
        return f"[ERROR] {e}"


def buscar_ficheros(patron: str, directorio: str = "B:\\NOVA") -> str:
    try:
        files = sorted(Path(directorio).glob(patron))
        if not files:
            return "No se encontraron ficheros."
        return "\n".join(str(f) for f in files[:50])
    except Exception as e:
        return f"[ERROR] {e}"


def grep_en_ficheros(patron: str, directorio: str = "B:\\NOVA",
                     extension: str = "*.py") -> str:
    try:
        matches = []
        for f in sorted(Path(directorio).glob(f"**/{extension}")):
            try:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                ):
                    if re.search(patron, line, re.IGNORECASE):
                        matches.append(f"{f.name}:{i}: {line.strip()}")
            except Exception:
                pass
        return "\n".join(matches[:100]) if matches else "Sin resultados."
    except Exception as e:
        return f"[ERROR] {e}"


# ── Dispatcher ────────────────────────────────────────────────────────────────

def ejecutar_herramienta(nombre: str, args: dict) -> str:
    dispatch = {
        "leer_fichero":     lambda: leer_fichero(args["path"]),
        "escribir_fichero": lambda: escribir_fichero(args["path"], args["contenido"]),
        "editar_fichero":   lambda: editar_fichero(args["path"], args["buscar"], args["reemplazar"]),
        "ejecutar_comando": lambda: ejecutar_comando(args["cmd"], args.get("timeout", 30)),
        "buscar_web":       lambda: buscar_web(args["query"]),
        "fetch_url":        lambda: fetch_url(args["url"]),
        "buscar_ficheros":  lambda: buscar_ficheros(args["patron"], args.get("directorio", "B:\\NOVA")),
        "grep_en_ficheros": lambda: grep_en_ficheros(
            args["patron"], args.get("directorio", "B:\\NOVA"), args.get("extension", "*.py")
        ),
    }
    fn = dispatch.get(nombre)
    if fn is None:
        return f"[ERROR] Herramienta desconocida: {nombre}"
    return fn()


# ── Schemas OpenAI (para Ollama tool calling) ─────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "leer_fichero",
            "description": "Lee el contenido completo de un fichero. Seguro, no modifica nada.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta absoluta o relativa al fichero"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escribir_fichero",
            "description": (
                "Escribe contenido completo en un fichero (crea o sobrescribe). "
                "ACCIÓN DESTRUCTIVA — requiere confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":      {"type": "string", "description": "Ruta del fichero"},
                    "contenido": {"type": "string", "description": "Contenido completo a escribir"},
                },
                "required": ["path", "contenido"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editar_fichero",
            "description": (
                "Reemplaza UNA ocurrencia exacta de un texto dentro de un fichero. "
                "Usa leer_fichero primero para ver el texto exacto. "
                "ACCIÓN MODIFICADORA — requiere confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path":       {"type": "string", "description": "Ruta del fichero"},
                    "buscar":     {"type": "string", "description": "Texto exacto a buscar (con espacios e indentación)"},
                    "reemplazar": {"type": "string", "description": "Texto de reemplazo"},
                },
                "required": ["path", "buscar", "reemplazar"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ejecutar_comando",
            "description": (
                "Ejecuta un comando de shell en el sistema local. "
                "Comandos con rm, del, pip, ssh, Oracle (100.111.223.84), netsh, taskkill "
                "o similares REQUIEREN confirmación del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd":     {"type": "string",  "description": "Comando a ejecutar"},
                    "timeout": {"type": "integer", "description": "Timeout en segundos (defecto: 30)"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_web",
            "description": "Busca información actualizada en internet. Usa Tavily (IA-optimizado) con fallback a DuckDuckGo. Incluye la fecha actual en la búsqueda automáticamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta de búsqueda"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Descarga y devuelve el texto de una URL específica.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL a descargar"}
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_ficheros",
            "description": "Busca ficheros por patrón glob en el proyecto NOVA.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patron":     {"type": "string", "description": "Patrón glob (ej: *.py, **/*.json)"},
                    "directorio": {"type": "string", "description": "Directorio base (defecto: B:\\NOVA)"},
                },
                "required": ["patron"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_en_ficheros",
            "description": "Busca un texto o patrón regex en los ficheros del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patron":     {"type": "string", "description": "Patrón de búsqueda (texto o regex)"},
                    "directorio": {"type": "string", "description": "Directorio base (defecto: B:\\NOVA)"},
                    "extension":  {"type": "string", "description": "Extensión de ficheros (defecto: *.py)"},
                },
                "required": ["patron"],
            },
        },
    },
]
