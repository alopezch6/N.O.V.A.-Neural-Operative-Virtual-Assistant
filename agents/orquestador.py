"""
Orquestador NOVA — Hermes como director
Clasifica el intent y enruta a OpenClaw o Open Interpreter.
Hermes (hermes3:8b en Oracle) decide cuando la deteccion rapida no es suficiente.
"""

import subprocess
import ollama
from mono import log as mlog

_HERMES_HOST  = "http://100.111.223.84:11434"
_HERMES_MODEL = "hermes3:8b"
_hermes_client = ollama.Client(host=_HERMES_HOST, timeout=20.0)

_OPENCLAW_KEYWORDS = [
    "email", "correo", "gmail",
    "envía un correo", "envia un correo", "manda un correo",
    "envía un email", "envia un email", "manda un email",
    "calendario", "calendar", "agenda",
    "añade al calendario", "agrega al calendario",
    "crea un evento", "nuevo evento", "reunión", "reunion", "cita",
    "reminder",
    "busca en internet", "búsqueda web",
]

_INTERPRETER_KEYWORDS = [
    "analiza el archivo", "analiza este archivo",
    "procesa el csv", "procesa este csv",
    "haz un gráfico", "haz una gráfica", "visualiza los datos",
    "analiza estos datos", "procesa estos datos",
    "lee el excel", "lee el csv",
    "ejecuta este script", "ejecuta este código",
]


def _deteccion_rapida(texto: str) -> str | None:
    t = texto.lower()
    if any(k in t for k in _OPENCLAW_KEYWORDS):
        return "openclaw"
    if any(k in t for k in _INTERPRETER_KEYWORDS):
        return "interpreter"
    return None


def _ask_hermes(texto: str) -> str:
    prompt = f"""Clasifica esta petición en una de estas categorías:
- "openclaw": email, Gmail, calendario, agenda, evento, recordatorio, búsqueda web
- "interpreter": ejecutar código Python, analizar archivos, procesar datos, CSV, Excel, gráficos
- "nova": conversación, pregunta general, cualquier otra cosa

Petición: "{texto}"

Responde SOLO con una palabra: openclaw, interpreter, o nova"""
    try:
        resp = _hermes_client.chat(
            model=_HERMES_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0},
        )
        result = resp["message"]["content"].strip().lower()
        if "openclaw" in result:
            return "openclaw"
        if "interpreter" in result:
            return "interpreter"
        return "nova"
    except Exception as e:
        mlog("HERMES", f"No disponible, pasando a NOVA: {e}")
        return "nova"


def _contexto_para_agente(query: str) -> str:
    """Recupera contexto relevante de ChromaDB para inyectar en agentes externos."""
    try:
        import memoria_profunda as _mp
        resultados = _mp.buscar_contexto(query, n=3, solo_hechos=False)
        if not resultados:
            return ""
        lineas = ["[Contexto NOVA relevante:]"]
        for r in resultados:
            rol   = "Alex" if r["rol"] == "user" else "NOVA"
            fecha = (r.get("timestamp") or "")[:10]
            lineas.append(f"- [{fecha}] {rol}: {r['contenido'][:150]}")
        return "\n".join(lineas) + "\n\n"
    except Exception:
        return ""


def _call_openclaw(texto: str) -> str:
    contexto = _contexto_para_agente(texto)
    mensaje  = (contexto + texto) if contexto else texto
    try:
        result = subprocess.run(
            ["wsl", "-e", "openclaw", "agent", "--message", mensaje],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
        )
        salida = result.stdout.strip()
        return salida if salida else "Tarea enviada a OpenClaw."
    except subprocess.TimeoutExpired:
        return "OpenClaw tardó demasiado en responder."
    except Exception as e:
        return f"Error contactando OpenClaw: {e}"


def _call_interpreter(texto: str) -> str:
    contexto = _contexto_para_agente(texto)
    mensaje  = (contexto + texto) if contexto else texto
    try:
        import interpreter as oi
        oi.llm.model      = "ollama/qwen2.5:7b"
        oi.llm.api_base   = "http://localhost:11434"
        oi.auto_run       = True
        oi.verbose        = False
        msgs = oi.chat(mensaje, return_messages=True)
        for msg in reversed(msgs):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return "Tarea ejecutada con Open Interpreter."
    except Exception as e:
        return f"Error en Open Interpreter: {e}"


def maybe_handle_orchestrated(texto: str) -> dict | None:
    """
    Intenta resolver la peticion via OpenClaw o Open Interpreter.
    Retorna {"handled": True, "reply": str} o None para pasar al LLM conversacional.
    """
    agente = _deteccion_rapida(texto)

    if agente is None:
        mlog("HERMES", f"Consultando Hermes para clasificar: {texto[:50]}")
        agente = _ask_hermes(texto)

    if agente == "nova":
        return None

    if agente == "openclaw":
        mlog("ORQUESTADOR", f"→ OpenClaw: {texto[:60]}")
        respuesta = _call_openclaw(texto)
        return {"handled": True, "reply": respuesta}

    if agente == "interpreter":
        mlog("ORQUESTADOR", f"→ Open Interpreter: {texto[:60]}")
        respuesta = _call_interpreter(texto)
        return {"handled": True, "reply": respuesta}

    return None
