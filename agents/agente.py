"""
NOVA — Agente autoextensible
Cuando acciones.py no reconoce una peticion, este modulo:
1. Detecta si la peticion es ejecutable con codigo Python
2. Genera el snippet via LLM
3. Pide confirmacion a Alex
4. Ejecuta en subproceso controlado
5. Guarda la capacidad para futuras peticiones (sin volver a generar)
"""

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from mono import log as mlog
from utils.apps import open_app, normalize_app_name

_BASE = Path(__file__).resolve().parents[1]
_CAPACIDADES_PATH = _BASE / "capacidades.json"
_PENDING_PATH = _BASE / "agente_pending.json"

_groq = Groq(api_key=GROQ_API_KEY)

# Operaciones destructivas que nunca se ejecutan
_BLACKLIST = [
    r"\bos\.remove\b",
    r"\bos\.rmdir\b",
    r"\bshutil\.rmtree\b",
    r"\bshutil\.rmdir\b",
    r"rm\s+-[rRfF]",
    r"del\s+/[sqSQ]",
    r"\bformat\b.*[A-Za-z]:\\",
    r"\bwinreg\b",
    r"HKEY_",
]

# ── Vocabulario de confirmacion ────────────────────────────────────────────────
CONFIRM_WORDS = {
    # Afirmaciones simples
    "si", "sí", "yes", "ok", "okay", "okey", "vale", "venga", "dale",
    "claro", "perfecto", "correcto", "exacto", "efectivamente", "afirmativo",
    "de acuerdo", "por supuesto", "obvio", "obviamente", "evidentemente",
    # Imperativo directo
    "hazlo", "haz", "hazla", "hazlos", "hazlas",
    "ejecuta", "ejecutalo", "ejecutala",
    "adelante", "procede", "continua", "continúa", "sigue", "anda",
    "lanzalo", "lánzalo", "arranca", "arrancalo",
    # Frases de confirmacion
    "que si", "que sí", "que lo hagas", "que la hagas",
    "que lo haga", "que la haga", "que lo ejecutes",
    "que si hazlo", "venga va", "va", "vamos", "vamos a ello",
    "a por ello", "adelante con ello", "sin problema", "sin problemas",
    "eso es", "asi es", "así es", "exactamente", "justo eso",
    "script", "haz el script", "make it", "do it",
    # Coloquial espanol
    "tio si", "tío sí", "hostia si", "joder si", "pues si", "pues sí",
    "anda ya", "venga hombre", "que si que si", "que sí que sí",
}

# ── Vocabulario de cancelacion ─────────────────────────────────────────────────
CANCEL_WORDS = {
    # Negaciones simples
    "no", "nope", "nel", "nanai", "para nada",
    # Cancelacion explicita
    "cancela", "cancelar", "cancelado", "abort", "abortar",
    "para", "parar", "detente", "detener", "stop",
    "olvida", "olvídalo", "olvidalo", "olvídate", "olvidate",
    "dejalo", "déjalo", "dejame", "déjame",
    # Cambio de opinion
    "mejor no", "al final no", "que no", "no lo hagas",
    "no hace falta", "no importa", "no pasa nada",
    "espera", "un momento", "momento",
}

# ── Raices verbales de accion ──────────────────────────────────────────────────
# Se comprueban como palabras completas o prefijos (admiten sufijos: me/lo/la/te/nos/le)
_ACTION_ROOTS = [
    # Abrir / iniciar apps
    "abre", "abrir", "abrirme", "abrelo", "abrela", "abrirlo", "abrirla",
    "abrelo", "ábrelo", "ábrela", "ábrelos", "ábrelas",
    "inicia", "iniciar", "iniciame", "inicialo",
    "arranca", "arrancar", "arrancalo",
    "lanza", "lanzar", "lanzame", "lanzalo",
    "ejecuta", "ejecutar", "ejecutame", "ejecutalo",
    # Cerrar / matar procesos
    "cierra", "cerrar", "cierralo", "cierrala", "ciérralo", "ciérrala",
    "mata", "matar", "matalo",
    "termina", "terminar", "terminalo",
    "finaliza", "finalizar",
    "sal", "salir",
    "kill",
    # Reproduccion multimedia
    "reproduce", "reproducir", "reproducelo", "reprodúcelo",
    "pon", "poner", "ponme", "ponlo",
    "pausa", "pausar", "pausalo",
    "reanuda", "reanudar",
    "para", "detén", "detener",
    "salta", "saltar",
    "siguiente", "anterior",
    "shuffle", "aleatorio",
    # Volumen / audio
    "silencia", "silenciar", "silencialo",
    "mutea", "mutear",
    "desmutea", "desmutear",
    # Descargas
    "descarga", "descargar", "descargame", "descargalo",
    "baja", "bajar",
    # Red / conectividad
    "conecta", "conectar", "conectame",
    "desconecta", "desconectar",
    # Sistema
    "captura", "screenshot",
    "reinicia", "reiniciar",
    "apaga", "apagar",
    "suspende", "suspender",
    "bloquea", "bloquear",
    # Archivos
    "mueve", "mover",
    "copia", "copiar",
    "crea", "crear",
    "renombra", "renombrar",
    # Instalacion
    "instala", "instalar",
    "desinstala", "desinstalar",
    "actualiza", "actualizar",
]

# ── Frases de accion completas ─────────────────────────────────────────────────
_ACTION_PHRASES = [
    # Peticiones con "puedes"
    "puedes abrir", "puedes abrirme", "puedes ejecutar", "puedes lanzar",
    "puedes cerrar", "puedes descargar", "puedes instalar", "puedes iniciar",
    "puedes arrancar", "puedes reproducir", "puedes poner", "puedes parar",
    "puedes silenciar", "puedes capturar", "puedes hacer una captura",
    "puedes crear", "puedes mover", "puedes copiar", "puedes conectar",
    "puedes activar", "puedes desactivar", "puedes reiniciar",
    # Peticiones con "me puedes" / "me podrías"
    "me puedes abrir", "me puedes ejecutar", "me puedes lanzar",
    "me puedes poner", "me puedes instalar", "me puedes descargar",
    "me podrias abrir", "me podrías abrir", "me podrias poner",
    "me podrías poner", "me podrias ejecutar", "me podrías ejecutar",
    # Abre + articulo
    "abre el", "abre la", "abre los", "abre las", "abre un", "abre una",
    # Pon + articulo
    "pon el", "pon la", "ponme el", "ponme la",
    # Volumen
    "sube el volumen", "baja el volumen", "pon el volumen",
    "cambia el volumen", "sube el sonido", "baja el sonido",
    "pon el sonido", "sube el audio", "baja el audio",
    # Brillo
    "sube el brillo", "baja el brillo", "pon el brillo",
    # Monitor / pantalla
    "apaga el monitor", "apaga la pantalla", "apaga las pantallas",
    "enciende el monitor", "enciende la pantalla",
    # Capturas
    "toma una captura", "captura de pantalla", "haz una captura",
    "haz un screenshot", "toma un screenshot",
    # Archivos y carpetas
    "mueve el archivo", "copia el archivo", "crea la carpeta",
    "crea el archivo", "crea una carpeta", "crea un archivo",
    "renombra el archivo", "renombra la carpeta",
    # Red
    "activa el wifi", "desactiva el wifi", "pon modo avion",
    "activa modo avion", "desactiva modo avion",
    "conecta a", "desconecta de",
    # Apps especificas frecuentes
    "abre spotify", "abre discord", "abre steam", "abre chrome",
    "abre opera", "abre firefox", "abre el navegador",
    "abre whatsapp", "abre telegram", "abre netflix",
    "abre el explorador", "abre el task manager", "abre el administrador",
]


# ── Estado persistente ─────────────────────────────────────────────────────────

def _load_pending() -> dict | None:
    if _PENDING_PATH.exists():
        try:
            return json.loads(_PENDING_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_pending(data: dict) -> None:
    _PENDING_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_pending() -> None:
    if _PENDING_PATH.exists():
        _PENDING_PATH.unlink(missing_ok=True)


# ── Capacidades guardadas ──────────────────────────────────────────────────────

def _load_capacidades() -> dict:
    if _CAPACIDADES_PATH.exists():
        try:
            return json.loads(_CAPACIDADES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_capacidades(caps: dict) -> None:
    _CAPACIDADES_PATH.write_text(json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")


_STOPWORDS = {"el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
              "al", "a", "en", "por", "para", "con", "que", "me", "te", "se",
              "lo", "le", "y", "o", "es", "son", "hay", "pero", "si", "no"}

def _find_saved(texto: str) -> dict | None:
    caps = _load_capacidades()
    lower = texto.lower().strip()
    if lower in caps:
        return caps[lower]
    words = set(lower.split()) - _STOPWORDS
    if not words:
        return None
    for key, val in caps.items():
        key_words = set(key.split()) - _STOPWORDS
        if key_words and len(words & key_words) >= 2:
            return val
    return None


def _persist_capability(texto: str, code: str, description: str) -> None:
    caps = _load_capacidades()
    key = texto.lower().strip()
    if key in caps:
        caps[key]["uses"] = caps[key].get("uses", 0) + 1
    else:
        caps[key] = {
            "code": code,
            "description": description,
            "created": datetime.now().isoformat(timespec="seconds"),
            "uses": 1,
        }
    _save_capacidades(caps)


# ── Seguridad ──────────────────────────────────────────────────────────────────

def _is_safe(code: str) -> bool:
    for pattern in _BLACKLIST:
        if re.search(pattern, code, re.IGNORECASE):
            return False
    return True


# ── Deteccion heuristica ───────────────────────────────────────────────────────

def is_actionable(texto: str) -> bool:
    t = texto.lower().strip()
    padded = f" {t} "
    # Comprobar frases completas
    if any(phrase in padded for phrase in _ACTION_PHRASES):
        return True
    # Comprobar raices verbales como palabras (con posibles sufijos pegados)
    words = t.split()
    for word in words:
        if any(word == root or word.startswith(root) for root in _ACTION_ROOTS):
            return True
    return False


# ── Ejecucion ──────────────────────────────────────────────────────────────────

_SNIPPET_HEADER = (
    "import os, sys, subprocess, glob, shutil, re, json, time, threading, pathlib; "
    "from pathlib import Path; "
)

def _run_snippet(code: str, timeout: int = 15) -> tuple[bool, str]:
    full_code = _SNIPPET_HEADER + code
    try:
        result = subprocess.run(
            [sys.executable, "-c", full_code],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output or ""
    except subprocess.TimeoutExpired:
        return False, "Timeout: el script tardo demasiado."
    except Exception as e:
        return False, f"Error de ejecucion: {e}"


# ── Generacion de snippet ──────────────────────────────────────────────────────

def _generate_snippet(texto: str) -> dict:
    prompt = f"""Eres un asistente tecnico para Windows 11. El usuario pide: "{texto}"

Determina si esto puede resolverse con un snippet Python en Windows 11.
Es ejecutable: abrir apps, controlar sistema, peticiones HTTP, leer archivos, volumen, etc.
NO es ejecutable: preguntas, conversaciones, peticiones de explicacion, tareas de razonamiento.

Si es ejecutable, escribe el codigo Python minimo para hacerlo.
Reglas del codigo:
- Solo librerias estandar de Python (subprocess, os, glob, shutil, winreg, ctypes)
- NUNCA uses "start nombre_app" porque Windows no lo reconoce para la mayoria de apps
- Para abrir apps instaladas en Windows usa este patron (busca el exe real):
  * Discord: glob en %LOCALAPPDATA%\\Discord\\app-*\\Discord.exe
  * Spotify: glob en %APPDATA%\\Spotify\\Spotify.exe o %LOCALAPPDATA%\\Microsoft\\WindowsApps\\Spotify.exe
  * Steam: glob en C:\\Program Files (x86)\\Steam\\steam.exe o shutil.which("steam")
  * Apps de Microsoft Store: subprocess.Popen("start ms-windows-store:", shell=True)
  * Apps genericas: usar shutil.which("nombre") primero, si no glob en Program Files y AppData
- NUNCA hagas subprocess.Popen([shutil.which(...)]) directamente — shutil.which puede devolver None
  Guarda el resultado en una variable y comprueba que no es None antes de usarlo
- Sin input(), sin prints innecesarios, sin bucles infinitos
- Maximo 4 lineas

Responde UNICAMENTE con JSON valido, sin texto extra, sin markdown:
{{"runnable": true, "code": "...", "description": "descripcion corta en espanol de lo que hace"}}
o
{{"runnable": false, "reason": "por que no es ejecutable"}}"""

    try:
        resp = _groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.1,
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        mlog("AGENTE", f"Error generando snippet: {e}")

    return {"runnable": False, "reason": "Error de conexion con el LLM"}


# ── Creacion de plugins bajo demanda ──────────────────────────────────────────

_PLUGIN_CREATION_PATTERNS = [
    # crear
    "crea una función para", "crea una funcion para",
    "crea un plugin para", "crea una capacidad para",
    "crea un comando para", "crea una herramienta para",
    "crea un script para", "crea la función", "crea el plugin",
    "crear una función para", "crear una funcion para",
    "crear un plugin para", "crear una capacidad para",
    "puedes crear una función", "puedes crear una funcion",
    "puedes crear la función", "puedes crear la funcion",
    "puedes crear un plugin", "puedes crear el plugin",
    "puedes crear una capacidad", "puedes crear la capacidad",
    "puedes crear un comando", "puedes crear el comando",
    "puedes crear una herramienta", "puedes crear la herramienta",
    "puedes crear un script", "puedes crear el script",
    "puedes crear la solución", "puedes crear la solucion",
    "crear la solución", "crear la solucion",
    # hacer
    "puedes hacer una función", "puedes hacer una funcion",
    "puedes hacer la función", "puedes hacer la funcion",
    "puedes hacer un plugin", "puedes hacer el plugin",
    "puedes hacer un comando", "puedes hacer el comando",
    "puedes hacer una herramienta", "puedes hacer un script",
    "puedes hacer algo para",
    "haz una función para", "haz un script para", "haz un plugin para",
    "hacer algo para que puedas",
    "hagas algo para que puedas",
    "haz algo para que puedas",
    "podrías hacer algo para", "podrias hacer algo para",
    # añadir
    "añade una función para", "añade una funcion para",
    "añade un plugin", "añade una capacidad",
    "añade la función", "añade la funcion",
    # implementar
    "implementa una función", "implementa una funcion",
    "implementa un plugin", "implementa la función",
    "implementa la funcion", "implementa la accion",
    "implementa la acción", "puedes implementar",
    "implementar una función", "implementar una funcion",
    # programar / desarrollar / escribir
    "puedes programar", "programa una función", "programa un plugin",
    "puedes desarrollar", "desarrolla una función",
    "escribe una función para", "escribe un script para",
    # aprender / enseñar
    "aprende a ", "aprende esto", "aprende eso",
    "puedes aprender a", "quiero que aprendas a",
    "te enseño a", "enséñate a", "ensenate a",
    # guardar / memorizar
    "guarda esto como capacidad", "guarda esto como función",
    "guárdalo como capacidad", "guardalo como capacidad",
    "guárdate esto como", "guardate esto como",
    "memoriza esta función", "memoriza esto", "memoriza eso",
    # poder hacer / ser capaz
    "para que puedas", "para que seas capaz",
    "que puedas decirme", "que puedas obtener",
    "quiero que puedas", "necesito que puedas",
    # solucionar / arreglar
    "puedes solucionar eso", "puedes arreglar eso",
    "puedes resolver eso", "soluciona eso",
]

_PRONOMBRES_REFERENCIA = [
    "eso", "esto", "lo anterior", "lo de antes",
    "esa función", "esa funcion", "esa capacidad", "ese plugin",
    "ese comando", "esa herramienta", "ese script",
    "lo que dijiste", "lo que pedí antes", "lo que pedí",
    "lo que acabas de decir", "lo que mencionaste",
    "la solución", "el problema", "lo que falta",
    "lo que no puedes", "lo que no sabes", "lo que no tienes",
    "esa tarea", "esa acción", "esa accion",
]


def _resolver_referencia(texto: str, historial: list | None) -> str:
    """Si el texto contiene un pronombre vago ('eso', 'esto'...), extrae el tema del turno anterior."""
    lower = texto.lower()
    if not any(p in lower for p in _PRONOMBRES_REFERENCIA):
        return texto
    if not historial:
        return texto
    # Buscar la última petición del usuario (no la actual)
    for entry in reversed(historial[:-1]):
        if entry.get("role") == "user":
            contenido = entry["content"]
            # El historial puede contener "Alex dice: ..." — extraer solo la petición
            if "Alex dice:" in contenido:
                contenido = contenido.split("Alex dice:")[-1].strip()
            if len(contenido) > 5:
                mlog("AGENTE", f"Referencia resuelta: '{texto[:40]}' → '{contenido[:60]}'")
                return contenido
    return texto


def _maybe_crear_plugin(texto: str, historial: list | None) -> dict | None:
    """Detecta peticiones de creación de plugin y lo genera via plugin_generator."""
    lower = texto.lower()
    if not any(p in lower for p in _PLUGIN_CREATION_PATTERNS):
        return None

    # Extraer la descripción de lo que debe hacer el plugin
    descripcion = texto.strip()
    for patron in _PLUGIN_CREATION_PATTERNS:
        if patron in lower:
            idx = lower.index(patron) + len(patron)
            resto = texto[idx:].strip(" .?¿¡!")
            if resto:
                descripcion = resto
            break

    # Si la descripción es vaga ("eso", "esto"...), resolverla con el historial
    descripcion = _resolver_referencia(descripcion, historial)

    # Si sigue siendo vaga (pronombre genérico o muy corta), buscar en historial el último
    # mensaje de usuario que no sea una petición de crear plugin
    _VAGAS = {"la función", "la funcion", "el plugin", "la capacidad", "la solución",
              "la solucion", "la acción", "la accion", "la herramienta", "el comando",
              "el script", "eso", "esto", "lo anterior", ""}
    if not descripcion or descripcion.lower() in _VAGAS or len(descripcion) < 8:
        if historial:
            for entry in reversed(historial[:-1] if len(historial) > 1 else historial):
                if entry.get("role") == "user":
                    contenido = entry.get("content", "")
                    if "Alex dice:" in contenido:
                        contenido = contenido.split("Alex dice:")[-1].strip()
                    if len(contenido) > 8 and not any(p in contenido.lower() for p in _PLUGIN_CREATION_PATTERNS):
                        mlog("AGENTE", f"Descripción resuelta desde historial: '{contenido[:60]}'")
                        descripcion = contenido
                        break

    mlog("AGENTE", f"Creando plugin para: {descripcion[:80]}")

    try:
        from plugin_generator import generar_plugin, guardar_plugin
        from acciones import _replicar_plugin
        code, filename_or_error = generar_plugin(descripcion)
        if code is None:
            return {"handled": True, "reply": f"No he podido generar el plugin: {filename_or_error}"}
        guardar_plugin(code, filename_or_error)
        sync_msg = _replicar_plugin(filename_or_error, code)
        nombre_limpio = filename_or_error.replace("_", " ").replace(".py", "")
        return {"handled": True, "reply": f"Plugin creado: '{nombre_limpio}'. {sync_msg}"}
    except Exception as e:
        mlog("AGENTE", f"Error creando plugin: {e}")
        return {"handled": True, "reply": f"Error al crear el plugin: {e}"}


# ── Punto de entrada principal ─────────────────────────────────────────────────

def maybe_handle_auto(texto: str, historial: list | None = None) -> dict | None:
    """
    Intenta resolver una peticion generando y ejecutando codigo Python.
    Retorna {"handled": True, "reply": str} o None para pasar al LLM conversacional.
    """
    stripped = texto.strip()
    lower = stripped.lower()

    # Detectar peticion de creacion de plugin antes de la heuristica normal
    plugin_result = _maybe_crear_plugin(stripped, historial)
    if plugin_result:
        return plugin_result

    # Resolver referencias vagas usando el historial antes de buscar capacidades
    texto_resuelto = _resolver_referencia(stripped, historial)
    if texto_resuelto != stripped:
        stripped = texto_resuelto
        lower = stripped.lower()

    # Verificacion heuristica rapida antes de llamar al LLM
    if not is_actionable(stripped):
        return None

    # Intento de apertura de app directamente (sin LLM)
    app_name = normalize_app_name(stripped)
    if app_name:
        mlog("AGENTE", f"Intentando abrir app: {app_name}")
        ok, result_msg = open_app(app_name)
        if ok:
            return {"handled": True, "reply": f"{result_msg} abierto."}
        mlog("AGENTE", f"App no encontrada por registro: {app_name}. Pasando al LLM.")

    # Capacidad guardada: ejecutar directamente sin LLM
    saved = _find_saved(stripped)
    if saved:
        mlog("AGENTE", f"Capacidad guardada encontrada: {stripped[:50]}")
        success, output = _run_snippet(saved["code"])
        if success:
            caps = _load_capacidades()
            key = stripped.lower().strip()
            for k in caps:
                if k == key or len(set(key.split()) & set(k.split())) >= 2:
                    caps[k]["uses"] = caps[k].get("uses", 0) + 1
                    break
            _save_capacidades(caps)
            reply = saved["description"] + (" Hecho." if not output else f" {output}")
            return {"handled": True, "reply": reply}
        mlog("AGENTE", "Capacidad guardada fallo. Regenerando snippet.")

    # Generar nuevo snippet via LLM
    mlog("AGENTE", f"Peticion no implementada. Generando snippet para: {stripped[:50]}")
    result = _generate_snippet(stripped)

    if not result.get("runnable"):
        mlog("AGENTE", f"No ejecutable: {result.get('reason', '?')}")
        return None  # Pasa al LLM conversacional

    code = result.get("code", "").strip()
    description = result.get("description", "Ejecutando accion.")

    if not code:
        return None

    if not _is_safe(code):
        mlog("AGENTE", f"Snippet bloqueado por seguridad: {code[:100]}")
        return {"handled": True, "reply": "No puedo ejecutar eso, contiene operaciones restringidas."}

    # Ejecutar directamente y guardar la capacidad
    mlog("AGENTE", f"Ejecutando snippet: {code[:80]}")
    success, output = _run_snippet(code)
    if success:
        _persist_capability(stripped, code, description)
        return {"handled": True, "reply": description + " Hecho."}
    else:
        last_line = [l.strip() for l in output.splitlines() if l.strip()]
        error_msg = last_line[-1] if last_line else "error desconocido"
        mlog("AGENTE", f"Snippet fallo: {output}")
        return {"handled": True, "reply": f"He intentado hacerlo pero ha fallado. {error_msg[:120]}"}


# ── Auto-extensión: crear plugin automáticamente cuando NOVA no sabe hacer algo ─

# Temas del sistema que claramente pueden automatizarse con Python/subprocess
_AUTO_EXTEND_TOPICS = (
    "temperatura", "temp ", "grados",
    "cpu", "gpu", "ram", "memoria", "disco", "almacenamiento",
    "proceso", "procesos", "tarea", "tareas",
    "batería", "bateria", "carga",
    "red", "ping", "latencia", "velocidad de red", "ip ",
    "servicio", "servicios",
    "ventilador", "fan",
    "uso del sistema", "uso de la cpu", "uso de la gpu",
    "uptime", "tiempo encendido", "tiempo activo",
    "rendimiento", "estadísticas", "estadisticas",
    "puerto", "puertos",
    "logs", "errores del sistema",
    "voltaje", "frecuencia",
)

# Palabras que indican pregunta de conocimiento general (no automatizable)
_KNOWLEDGE_QUESTIONS = (
    "quién es", "quien es", "qué es", "que es",
    "cómo funciona", "como funciona", "por qué", "por que",
    "cuándo fue", "cuando fue", "cuándo nació", "historia de",
    "explícame", "explicame", "háblame de", "hablame de",
    "define ", "definición de",
)


def _es_auto_extensible(texto: str) -> bool:
    """True si la petición es sobre datos del sistema que Python puede obtener."""
    lower = texto.lower()
    if any(k in lower for k in _KNOWLEDGE_QUESTIONS):
        return False
    return any(t in lower for t in _AUTO_EXTEND_TOPICS)


def maybe_auto_extend(texto: str, historial: list | None = None) -> dict | None:
    """
    Último recurso antes del LLM: si la petición es sobre algo accionable del sistema
    que NOVA no sabe hacer, crea un plugin automáticamente y lo ejecuta.
    """
    stripped = texto.strip()
    if not _es_auto_extensible(stripped):
        return None

    mlog("AGENTE", f"Auto-extensión: creando plugin para '{stripped[:60]}'")
    try:
        from plugin_generator import generar_plugin, guardar_plugin
        from acciones import _replicar_plugin, _cargar_plugins
        code, filename_or_error = generar_plugin(stripped)
        if code is None:
            mlog("AGENTE", f"Auto-extensión fallida: {filename_or_error}")
            return None  # Dejar pasar al LLM

        guardar_plugin(code, filename_or_error)
        _cargar_plugins()
        sync_msg = _replicar_plugin(filename_or_error, code)
        nombre_limpio = filename_or_error.replace("_", " ").replace(".py", "").strip()

        # Intentar ejecutar el plugin recién creado
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location(
                filename_or_error[:-3],
                _BASE / "plugins" / filename_or_error,
            )
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            resultado_ejecucion = mod.ejecutar({"text": stripped})
        except Exception as exec_err:
            mlog("AGENTE", f"Auto-extensión: plugin creado pero ejecución falló: {exec_err}")
            resultado_ejecucion = None

        if resultado_ejecucion:
            return {
                "handled": True,
                "reply": (
                    f"No tenía esa capacidad, así que la he creado. {resultado_ejecucion}"
                ),
            }
        return {
            "handled": True,
            "reply": (
                f"No tenía esa capacidad, así que la he creado: '{nombre_limpio}'. "
                f"{sync_msg} Ya puedes pedírmela directamente."
            ),
        }
    except Exception as e:
        mlog("AGENTE", f"Auto-extensión error: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# BUCLE AGÉNTICO — tool use multi-paso con Hermes3 en Oracle
# ══════════════════════════════════════════════════════════════════════════════

import ollama as _ollama
from memory import memoria_profunda as _mp_agente

_AGENTICO_PENDING_PATH = _BASE / "agentico_pending.json"

_HERMES_HOST  = "http://100.111.223.84:11434"
_HERMES_MODEL = "hermes3:8b"
_hermes_agente = _ollama.Client(host=_HERMES_HOST, timeout=90.0)

_MAX_ITERACIONES = 20

_AGENT_SYSTEM = (
    "Eres NOVA, asistente IA personal de Alex. Usas herramientas para completar tareas paso a paso.\n\n"
    "ENTORNO:\n"
    "- Sistema: Windows 11. Proyecto NOVA en B:\\NOVA\n"
    "- Oracle Cloud vía Tailscale: 100.111.223.84\n"
    "- Responde siempre en español de España\n\n"
    "RAZONAMIENTO (ReAct):\n"
    "- Cada paso: Razona qué necesitas → Actúa con una herramienta → Observa el resultado → Evalúa si ya es suficiente\n"
    "- Para para cuando tengas suficiente información. No uses más herramientas de las necesarias.\n"
    "- Para editar un fichero: primero usa leer_fichero para ver el texto exacto, luego editar_fichero\n"
    "- Usa el texto exacto (con espacios e indentación) al llamar a editar_fichero\n"
    "- Para comandos en Oracle: usa ejecutar_comando con ssh o los scripts de NOVA\n"
    "- Cuando termines, responde en 1-2 frases resumiendo lo que hiciste\n"
    "- Máximo 20 iteraciones de razonamiento por tarea"
)

# Frases que activan el modo agéntico (multi-paso con ficheros/comandos)
_AGENTIC_KEYWORDS = [
    "lee el archivo", "lee el fichero", "lee el código", "lee el script",
    "leer el archivo", "leer el fichero",
    "muéstrame el archivo", "muéstrame el código", "muestrame el archivo",
    "modifica el archivo", "modifica el fichero", "modifica el código",
    "edita el archivo", "edita el fichero", "edita el código",
    "cambia en el archivo", "cambia en el fichero",
    "escribe en el archivo", "escribe en el fichero",
    "añade al archivo", "añade al fichero",
    "crea un archivo", "crea un fichero", "crea un nuevo fichero",
    "actualiza el archivo", "actualiza el fichero",
    "refactoriza", "refactorizar",
    "arregla el bug", "arregla el error", "corrige el código", "corrige el error",
    "mejora el código", "optimiza el código",
    "implementa la función", "implementa el método", "implementa una función",
    "añade la función", "añade una función", "añade el método",
    "busca en el código", "busca en los ficheros", "busca en los archivos",
    "ejecuta el script", "corre el script",
    "qué hace el archivo", "qué hace el fichero", "explica el archivo",
]


def _es_agentico(texto: str) -> bool:
    t = texto.lower()
    return any(k in t for k in _AGENTIC_KEYWORDS)


# ── Estado persistente del bucle ──────────────────────────────────────────────

def _load_agentico_pending() -> dict | None:
    if _AGENTICO_PENDING_PATH.exists():
        try:
            return json.loads(_AGENTICO_PENDING_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_agentico_pending(data: dict) -> None:
    _AGENTICO_PENDING_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _clear_agentico_pending() -> None:
    _AGENTICO_PENDING_PATH.unlink(missing_ok=True)


# ── Bucle principal ───────────────────────────────────────────────────────────

def _run_agentic_loop(texto: str, messages: list | None = None) -> dict | None:
    """
    Ejecuta el bucle agéntico con Hermes3:8b en Oracle.
    Devuelve:
      {"handled": True, "reply": str}                   — completado
      {"needs_confirmation": True, "confirmacion_msg": str}  — pausado por confirmación
      None                                               — fallo, pasa al LLM conversacional
    """
    from herramientas import TOOL_SCHEMAS, riesgo_accion, ejecutar_herramienta, CONFIRM

    if messages is None:
        # Inyectar contexto de memoria relevante desde ChromaDB
        contexto_mem = ""
        try:
            resultados = _mp_agente.buscar_contexto(texto, n=3, solo_hechos=False)
            if resultados:
                lineas = ["\nContexto relevante de conversaciones anteriores:"]
                for r in resultados:
                    rol   = "Alex" if r["rol"] == "user" else "NOVA"
                    fecha = (r.get("timestamp") or "")[:10]
                    lineas.append(f"- [{fecha}] {rol}: {r['contenido'][:200]}")
                contexto_mem = "\n".join(lineas)
        except Exception:
            pass

        messages = [
            {"role": "system", "content": _AGENT_SYSTEM + contexto_mem},
            {"role": "user",   "content": texto},
        ]

    for iteracion in range(_MAX_ITERACIONES):
        try:
            response = _hermes_agente.chat(
                model=_HERMES_MODEL,
                messages=messages,
                tools=TOOL_SCHEMAS,
                options={"temperature": 0.1},
            )
        except Exception as e:
            mlog("AGENTE_V2", f"Error conectando con Hermes: {e}")
            return None

        msg        = response["message"]
        tool_calls = msg.get("tool_calls") or []

        # Sin tool calls → respuesta final del modelo
        if not tool_calls:
            content = (msg.get("content") or "").strip()
            if not content:
                return None
            return {"handled": True, "reply": content}

        # Añadir mensaje del asistente con tool calls
        messages.append(msg)

        # Procesar cada tool call
        for tc in tool_calls:
            fn        = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {}

            nivel, desc = riesgo_accion(tool_name, tool_args)

            if nivel == CONFIRM:
                # Guardar estado y pedir confirmación al usuario
                _save_agentico_pending({
                    "texto_original": texto,
                    "messages": messages,
                    "pending_tool": {
                        "name":       tool_name,
                        "args":       tool_args,
                        "descripcion": desc,
                    },
                })
                return {
                    "needs_confirmation": True,
                    "confirmacion_msg": f"Voy a {desc}. ¿Confirmas?",
                }

            # Tool segura: ejecutar directamente
            mlog("AGENTE_V2", f"[{iteracion+1}/{_MAX_ITERACIONES}] Tool: {tool_name}({list(tool_args.keys())})")
            resultado = ejecutar_herramienta(tool_name, tool_args)
            messages.append({"role": "tool", "content": resultado})

    return {"handled": True, "reply": "Operaciones completadas."}


# ── Orquestación paralela de subtareas ────────────────────────────────────────

_PARALLEL_TRIGGER_KEYWORDS = [
    " y también ", " además ", " al mismo tiempo ", " a la vez ",
    " y luego ", " y después ", " también quiero ", " y busca ",
    " y comprueba ", " y mira ", " y revisa ",
]


def _detectar_subtareas(texto: str) -> list[str] | None:
    """
    Detecta si el texto contiene múltiples tareas independientes que pueden
    ejecutarse en paralelo. Devuelve lista de subtareas o None.
    """
    t = texto.lower()
    if not any(k in t for k in _PARALLEL_TRIGGER_KEYWORDS):
        return None
    if len(texto) < 40:
        return None

    try:
        prompt = (
            f'El usuario pide: "{texto}"\n\n'
            "¿Contiene 2 o más tareas INDEPENDIENTES que se puedan hacer en paralelo?\n"
            "Si sí, responde SOLO con JSON: {\"paralelo\": true, \"tareas\": [\"tarea1\", \"tarea2\"]}\n"
            "Si no (una sola tarea o dependientes entre sí), responde: {\"paralelo\": false}\n"
            "Máximo 2 tareas. Sin texto extra."
        )
        resp = _groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=80,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("paralelo") and len(data.get("tareas", [])) >= 2:
                return data["tareas"]
    except Exception:
        pass
    return None


def _run_paralelo(subtareas: list[str]) -> dict:
    """Ejecuta subtareas en paralelo y combina resultados."""
    import threading
    resultados = [None] * len(subtareas)

    def _ejecutar(i, subtarea):
        try:
            res = _run_agentic_loop(subtarea)
            resultados[i] = res
        except Exception as e:
            resultados[i] = {"handled": True, "reply": f"Error en subtarea {i+1}: {e}"}

    hilos = [threading.Thread(target=_ejecutar, args=(i, t), daemon=True)
             for i, t in enumerate(subtareas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(timeout=60)

    respuestas = []
    for i, r in enumerate(resultados):
        if r and r.get("reply"):
            respuestas.append(f"[{i+1}] {r['reply']}")
        elif r is None:
            respuestas.append(f"[{i+1}] Sin resultado.")

    return {"handled": True, "reply": " | ".join(respuestas) if respuestas else "Subtareas completadas."}


# ── Puntos de entrada públicos ────────────────────────────────────────────────

def maybe_handle_agentic(texto: str) -> dict | None:
    """
    Activa el bucle agéntico si el texto requiere operaciones multi-paso con ficheros o comandos.
    Detecta subtareas paralelas antes de entrar al bucle secuencial.
    Devuelve dict o None (pasa al LLM conversacional).
    """
    if not _es_agentico(texto):
        return None

    # Intentar orquestación paralela si hay múltiples tareas independientes
    subtareas = _detectar_subtareas(texto)
    if subtareas:
        mlog("AGENTE_V2", f"Orquestación paralela: {len(subtareas)} subtareas detectadas.")
        return _run_paralelo(subtareas)

    mlog("AGENTE_V2", f"Modo agéntico activado: {texto[:60]}")
    return _run_agentic_loop(texto)


def check_pending_agentico() -> dict | None:
    """Devuelve el estado pendiente de confirmación agéntica, si existe."""
    return _load_agentico_pending()


def continuar_agentico(respuesta_usuario: str, pending: dict) -> dict | None:
    """
    Reanuda el bucle agéntico tras la respuesta de confirmación del usuario.
    """
    _clear_agentico_pending()

    resp_lower = respuesta_usuario.lower().strip()

    # Cancelación explícita
    if any(w in resp_lower for w in CANCEL_WORDS):
        return {"handled": True, "reply": "Operación cancelada."}

    # Confirmación
    if any(w in resp_lower for w in CONFIRM_WORDS):
        from herramientas import ejecutar_herramienta
        pt        = pending.get("pending_tool", {})
        tool_name = pt.get("name", "")
        tool_args = pt.get("args", {})
        desc      = pt.get("descripcion", tool_name)

        mlog("AGENTE_V2", f"Confirmado. Ejecutando: {tool_name}")
        resultado = ejecutar_herramienta(tool_name, tool_args)
        mlog("AGENTE_V2", f"Resultado: {resultado[:80]}")

        messages = pending.get("messages", [])
        messages.append({"role": "tool", "content": resultado})

        return _run_agentic_loop(pending.get("texto_original", ""), messages=messages)

    # Respuesta ambigua: cancelar por seguridad
    return {"handled": True, "reply": "No he entendido. Operación cancelada por seguridad."}
