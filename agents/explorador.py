"""
NOVA — Explorador de código propio (solo lectura)
Permite al brain en Oracle leer B:\\NOVA desde el PC local via Tailscale.
El conocimiento se guarda en self_knowledge.json y el resumen en self_summary.json.
"""

import json
import requests
from datetime import datetime
from pathlib import Path

from groq import Groq
from config import PC_TAILSCALE_IP, GROQ_API_KEY, GROQ_MODEL

_BASE           = f"http://{PC_TAILSCALE_IP}:5000"
_TIMEOUT        = 4
_CACHE          = Path(__file__).resolve().parents[1] / "self_knowledge.json"
_SUMMARY        = Path(__file__).resolve().parents[1] / "self_summary.json"
_CACHE_MAX_DAYS = 7

_EXCLUIR = {"historial.json", "historial_telegram.json", "memoria.json", "notas.txt"}

_groq = Groq(api_key=GROQ_API_KEY)

_resumen_cache: str | None = None

# Mapeo: palabras clave → archivos relevantes
_KEYWORD_FILES: list[tuple[tuple[str, ...], list[str]]] = [
    (("voz", "audio", "tts", "stt", "whisper", "kokoro", "fish", "hablar", "escuchar", "microfono", "micrófono"),
     ["voz.py"]),
    (("brain", "llm", "modelo", "ollama", "routing", "deepseek", "qwen", "razonamiento"),
     ["nova.py"]),
    (("memoria", "recuerda", "aprende", "guardar", "olvida"),
     ["memoria.py"]),
    (("internet", "búsqueda", "busca", "buscar", "web", "duckduckgo", "noticias"),
     ["internet.py"]),
    (("telegram", "mensaje", "bot", "chat"),
     ["telegram_bot.py"]),
    (("reporte", "diario", "matutino", "mañana"),
     ["reporte_diario.py"]),
    (("accion", "acción", "acciones", "tarea", "ejecutar", "abrir", "nota", "alarma", "recordatorio"),
     ["acciones.py"]),
    (("servidor", "flask", "api", "hud", "estado", "puerto"),
     ["servidor.py"]),
    (("config", "configuracion", "configuración", "variable", "token", "clave"),
     ["config.py"]),
    (("telemetria", "telemetría", "métrica", "metrica", "monitor"),
     ["telemetria.py"]),
]

_TRIGGERS = (
    "tu código", "el código", "cómo funciona", "como funciona",
    "cómo estás hecha", "como estas hecha", "cómo estás hecho", "como estas hecho",
    "qué archivos", "que archivos", "muéstrame", "muestrame",
    "enséñame", "ensename", "tu infra", "la infra", "arquitectura",
    "qué puedes hacer", "que puedes hacer", "qué sabes hacer", "que sabes hacer",
    "qué capacidades", "que capacidades", "explícate", "explicarte",
    "stack", "cómo estás montada", "como estas montada",
    "tu sistema", "el sistema", "cómo te han hecho", "como te han hecho",
    "nova.py", "voz.py", "acciones.py", "memoria.py", "telegram_bot.py",
    "tus archivos", "tu código fuente", "source",
    # revisión y diagnóstico
    "revisa tu", "revisa el", "revisa los", "revisa mi",
    "encuentra errores", "busca errores", "hay errores", "tiene errores",
    "qué errores", "que errores", "errores en tu", "fallos en tu",
    "diagnostica", "autodiagnóstico", "autodiagnostico",
    "está bien el código", "esta bien el codigo",
    "funciona bien el", "algo mal en",
    "bugs en", "qué bugs", "que bugs",
    "mejora tu", "mejoras en tu", "optimiza tu",
    "qué módulos", "que modulos", "qué módulo", "que modulo",
    "cómo está hecho", "como esta hecho",
    # patrones de recursos y calidad de código
    "manejadores", "except genérico", "except generic", "fuga", "fugas",
    "recurso", "recursos", "descriptor", "descriptores", "memoria filtrada",
    "open sin with", "archivo abierto", "archivos abiertos",
    "todo", "fixme", "pendiente en el código",
    "problemas en el código", "problemas en tu código",
    "código tiene", "código hay", "qué hay en el código",
    "revisar el código", "revisión del código", "auditar", "auditoría",
    "código limpio", "código malo", "código roto", "código viejo",
    "qué falla", "que falla", "qué está mal", "que esta mal",
)


# ── Caché de código ────────────────────────────────────────────────────────────

def _cargar_cache() -> dict:
    if _CACHE.exists():
        try:
            return json.loads(_CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _guardar_cache(archivos: dict[str, str]) -> None:
    data = {"fecha": datetime.now().isoformat(timespec="seconds"), "archivos": archivos}
    _CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def cache_info() -> str:
    c = _cargar_cache()
    if not c:
        return "Sin caché guardado."
    n = len(c.get("archivos", {}))
    fecha = c.get("fecha", "?")
    resumen_ok = "✅" if _SUMMARY.exists() else "❌"
    return f"{n} archivos · guardado el {fecha} · resumen {resumen_ok}"


# ── Resumen en lenguaje natural ────────────────────────────────────────────────

def _generar_resumen(archivos: dict[str, str]) -> str:
    """Pide al LLM que genere un resumen de autoconocimiento a partir del código."""
    codigo_concat = ""
    for nombre, contenido in archivos.items():
        codigo_concat += f"\n\n### {nombre}\n{contenido}"
        if len(codigo_concat) > 20_000:
            codigo_concat += "\n...[resto omitido por longitud]"
            break

    prompt = (
        "Eres NOVA, una IA personal. Acabas de leer tu propio código fuente. "
        "Genera un resumen de autoconocimiento en español con estas secciones:\n"
        "1. Arquitectura general (cómo están conectados los módulos)\n"
        "2. Qué hace cada módulo principal (una línea por módulo)\n"
        "3. Capacidades actuales (qué puedo hacer)\n"
        "4. Limitaciones conocidas\n"
        "5. Stack tecnológico (modelos, librerías clave)\n\n"
        "Sé técnica y directa. Máximo 500 palabras. Habla en primera persona.\n\n"
        f"CÓDIGO FUENTE:{codigo_concat}"
    )

    try:
        resp = _groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.3,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[Error generando resumen: {e}]"


def _guardar_resumen(resumen: str) -> None:
    global _resumen_cache
    data = {"fecha": datetime.now().isoformat(timespec="seconds"), "resumen": resumen}
    _SUMMARY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _resumen_cache = resumen


def obtener_resumen_propio() -> str:
    """Devuelve el resumen en lenguaje natural si existe. Cachea en memoria."""
    global _resumen_cache
    if _resumen_cache is not None:
        return _resumen_cache
    if not _SUMMARY.exists():
        return ""
    try:
        data = json.loads(_SUMMARY.read_text(encoding="utf-8"))
        _resumen_cache = data.get("resumen", "")
        return _resumen_cache
    except Exception:
        return ""


# ── Llamadas al PC ─────────────────────────────────────────────────────────────

def _listar_nova_remoto() -> list[str]:
    try:
        r = requests.get(f"{_BASE}/nova/files", timeout=_TIMEOUT)
        data = r.json()
        if "error" in data:
            return []
        return [e["name"] for e in data["entries"] if e["type"] == "file"]
    except Exception:
        return []


def _leer_archivo_remoto(nombre: str) -> str | None:
    try:
        r = requests.get(f"{_BASE}/nova/read", params={"path": nombre}, timeout=_TIMEOUT)
        data = r.json()
        return data.get("content") if "error" not in data else None
    except Exception:
        return None


# ── Aprendizaje completo ───────────────────────────────────────────────────────

def aprender_todo() -> str:
    """
    Lee todos los .py de B:\\NOVA, los guarda en caché y genera un resumen
    en lenguaje natural que persiste en self_summary.json.
    """
    archivos_remotos = _listar_nova_remoto()
    if not archivos_remotos:
        return "PC offline o servidor no disponible. No se pudo aprender."

    py_files = [f for f in archivos_remotos if f.endswith(".py") and f not in _EXCLUIR]
    leidos: dict[str, str] = {}
    fallidos: list[str] = []

    for nombre in py_files:
        contenido = _leer_archivo_remoto(nombre)
        if contenido is not None:
            leidos[nombre] = contenido
        else:
            fallidos.append(nombre)

    if not leidos:
        return "No se pudo leer ningún archivo."

    _guardar_cache(leidos)

    print("[EXPLORADOR] Generando resumen de autoconocimiento...")
    resumen = _generar_resumen(leidos)
    _guardar_resumen(resumen)

    msg = f"Aprendizaje completado. {len(leidos)} archivos leídos y resumen generado."
    if fallidos:
        msg += f" Fallidos: {', '.join(fallidos)}."
    return msg


# ── Consulta contextual ────────────────────────────────────────────────────────

def necesita_explorar_nova(texto: str) -> bool:
    t = texto.lower()
    return any(trigger in t for trigger in _TRIGGERS)


def _seleccionar_archivos(texto: str) -> list[str]:
    t = texto.lower()
    seleccionados: list[str] = []
    for keywords, archivos in _KEYWORD_FILES:
        if any(kw in t for kw in keywords):
            for f in archivos:
                if f not in seleccionados:
                    seleccionados.append(f)
    if not seleccionados:
        # petición genérica (diagnóstico, revisión, arquitectura) → archivos principales
        t = texto.lower()
        if any(k in t for k in ("revisa", "diagnostica", "errores", "bugs", "mejora", "arquitectura", "todo")):
            seleccionados = ["nova.py", "voz.py", "acciones.py"]
        else:
            seleccionados = ["nova.py"]
    return seleccionados[:3]


def _cache_es_antiguo(cache: dict) -> bool:
    fecha_str = cache.get("fecha")
    if not fecha_str:
        return True
    try:
        fecha = datetime.fromisoformat(fecha_str)
        return (datetime.now() - fecha).days >= _CACHE_MAX_DAYS
    except Exception:
        return True


def obtener_contexto_nova(texto: str) -> str:
    """
    Devuelve el código fuente relevante como contexto para el brain.
    Si no hay caché o es antiguo y el PC está online, aprende sola.
    """
    cache = _cargar_cache()
    archivos_cache: dict[str, str] = cache.get("archivos", {})
    archivos_necesarios = _seleccionar_archivos(texto)
    pc_online = bool(_listar_nova_remoto())

    necesita_aprender = (
        not archivos_cache
        or _cache_es_antiguo(cache)
        or any(f not in archivos_cache for f in archivos_necesarios)
    )
    if necesita_aprender and pc_online:
        print("[EXPLORADOR] Auto-aprendizaje triggered")
        aprender_todo()
        cache = _cargar_cache()
        archivos_cache = cache.get("archivos", {})

    archivos_vivos: dict[str, str] = {}
    if pc_online:
        for nombre in archivos_necesarios:
            contenido = _leer_archivo_remoto(nombre)
            if contenido:
                archivos_vivos[nombre] = contenido
                archivos_cache[nombre] = contenido
        if archivos_vivos:
            _guardar_cache(archivos_cache)

    fuente = archivos_vivos if archivos_vivos else {
        k: v for k, v in archivos_cache.items() if k in archivos_necesarios
    }

    if not fuente:
        return ""

    origen = "en vivo" if archivos_vivos else f"caché del {cache.get('fecha', '?')}"
    partes = [f"Archivos disponibles en B:\\NOVA: {', '.join(archivos_cache.keys())} [{origen}]", ""]
    for nombre, contenido in fuente.items():
        partes.append(f"# {nombre}\n{contenido}\n")

    resultado = "\n".join(partes).strip()
    if len(resultado) > 12_000:
        resultado = resultado[:12_000] + "\n...[truncado]"
    return resultado
