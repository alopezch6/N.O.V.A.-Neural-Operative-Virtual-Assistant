import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from mono import log as mlog


BASE_DIR = Path(__file__).resolve().parents[1]
STATE_PATH = BASE_DIR / "acciones_estado.json"
AUDIT_PATH = BASE_DIR / "acciones_auditoria.jsonl"
BOT_PATH = BASE_DIR / "interfaces" / "telegram_bot.py"
SSH_KEY_PATH = BASE_DIR / "ssh-key-2026-04-18.key"
SSH_HOST = "ubuntu@92.5.116.97"
BOT_LOG_CANDIDATES = (
    BASE_DIR / "telegram_bot.log",
    Path("/tmp/telegram_bot.log"),
)

ALLOWED_PIP_PACKAGES = {
    "apscheduler",
    "groq",
    "ollama",
    "psutil",
    "python-telegram-bot",
    "requests",
}

# ── Sistema de plugins dinámicos ──────────────────────────────────────────────
_PLUGINS_DIR = BASE_DIR / "plugins"
_plugins: list = []


def _cargar_plugins() -> None:
    global _plugins
    nuevos = []
    if not _PLUGINS_DIR.exists():
        _plugins = nuevos
        return
    for path in sorted(_PLUGINS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"nova_plugin_{path.stem}"
        sys.modules.pop(mod_name, None)  # Forzar recarga si ya estaba cargado
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "KEYWORDS") and hasattr(mod, "ejecutar"):
                nuevos.append(mod)
                mlog("PLUGINS", f"Plugin cargado: {path.name}")
            else:
                mlog("PLUGINS", f"Plugin ignorado (sin KEYWORDS o ejecutar): {path.name}")
        except Exception as e:
            mlog("PLUGINS", f"Error en plugin {path.name}: {e}")
    _plugins = nuevos


_cargar_plugins()

# ── Hot-reload: recarga plugins automáticamente si cambia plugins/ ────────────
_plugin_mtimes: dict[str, float] = {
    p.name: p.stat().st_mtime
    for p in _PLUGINS_DIR.glob("*.py")
    if _PLUGINS_DIR.exists() and not p.name.startswith("_")
} if _PLUGINS_DIR.exists() else {}


def _watch_plugins_loop() -> None:
    while True:
        time.sleep(30)
        try:
            if not _PLUGINS_DIR.exists():
                continue
            current = {
                p.name: p.stat().st_mtime
                for p in _PLUGINS_DIR.glob("*.py")
                if not p.name.startswith("_")
            }
            if current != _plugin_mtimes:
                _cargar_plugins()
                _plugin_mtimes.clear()
                _plugin_mtimes.update(current)
                mlog("PLUGINS", "Hot-reload: plugins recargados automáticamente")
        except Exception:
            pass


threading.Thread(target=_watch_plugins_loop, daemon=True, name="plugin-watcher").start()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pending": None}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_pending(action: str, params: dict, prompt: str) -> None:
    state = _load_state()
    state["pending"] = {
        "action": action,
        "params": params,
        "prompt": prompt,
        "created_at": _now_iso(),
    }
    _save_state(state)


def _clear_pending() -> None:
    state = _load_state()
    state["pending"] = None
    _save_state(state)


def _audit(kind: str, message: str, extra: dict | None = None) -> None:
    payload = {
        "ts": _now_iso(),
        "kind": kind,
        "message": message,
    }
    if extra:
        payload.update(extra)
    with AUDIT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _run_command(args: list[str], timeout: int = 30) -> tuple[int, str]:
    proc = subprocess.run(
        args,
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output.strip()


def _run_oracle_ssh(command: str, timeout: int = 30) -> tuple[int, str]:
    if not SSH_KEY_PATH.exists():
        return 1, f"No encuentro la clave SSH en {SSH_KEY_PATH}"
    return _run_command(
        ["ssh", "-i", str(SSH_KEY_PATH), SSH_HOST, command],
        timeout=timeout,
    )


def _tail_text(text: str, max_lines: int = 40, max_chars: int = 3500) -> str:
    lines = text.splitlines()
    trimmed = "\n".join(lines[-max_lines:])
    return trimmed[-max_chars:] if len(trimmed) > max_chars else trimmed


def _bot_log_path() -> Path | None:
    for candidate in BOT_LOG_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _restart_bot_async() -> None:
    def _worker():
        time.sleep(1.0)
        os.execv(sys.executable, [sys.executable, str(BOT_PATH)])

    threading.Thread(target=_worker, daemon=True).start()


def _match_install(text: str) -> str | None:
    lower = text.lower().strip()
    prefixes = (
        "instala ",
        "instalame ",
        "instálame ",
        "pip install ",
    )
    for prefix in prefixes:
        if lower.startswith(prefix):
            return shlex.split(text[len(prefix):].strip())[0].lower()
    return None


def _wants_logs(lower: str) -> bool:
    padded = f" {lower} "
    direct = (" log ", "logs", "errores recientes", "dame el log", "dame los logs",
              "muéstrame el log", "muestrame el log", "muéstrame los logs", "muestrame los logs",
              "ver log", "ver logs", "ver errores", "ultimos errores", "últimos errores",
              "que ha pasado", "qué ha pasado", "que fallo", "qué falló",
              "log del bot", "log de nova", "log de telegram")
    return any(k in padded or k in lower for k in direct)


def _wants_status(lower: str) -> bool:
    padded = f" {lower} "
    keys = (
        "estado oracle", "estado del oracle", "estado servidor", "estado del servidor",
        "como esta oracle", "cómo está oracle", "como esta el servidor", "cómo está el servidor",
        "como vas", "cómo vas",
        " cpu ", " ram ", " disco ", "uso de cpu", "uso de ram", "uso de disco",
        "memoria disponible", "espacio disponible", "cuanta ram", "cuánta ram",
        "metricas", "métricas", "rendimiento del servidor",
    )
    return any(key in padded or key in lower for key in keys)


def _wants_processes(lower: str) -> bool:
    keys = (
        "procesos nova", "procesos del bot", "procesos activos", "procesos en curso",
        "que esta corriendo", "qué está corriendo", "que procesos hay", "qué procesos hay",
        "que se esta ejecutando", "qué se está ejecutando",
        "esta corriendo nova", "está corriendo nova",
        "esta corriendo el bot", "está corriendo el bot",
    )
    return any(key in lower for key in keys)


def _wants_restart(lower: str) -> bool:
    keys = (
        "reinicia el bot", "reinicia telegram", "reinicia nova", "reinicia el telegram",
        "reinicia el servicio", "reinicia el proceso", "reinicia el telegram bot",
        "reiniciar el bot", "reiniciar nova", "reiniciar telegram",
        "restart bot", "restart nova", "restart telegram",
    )
    return any(key in lower for key in keys)


def _wants_tts_test(lower: str) -> bool:
    keys = ("prueba voz", "prueba de voz", "prueba tts", "test voz", "test tts")
    return any(key in lower for key in keys)


def _wants_diagnostico(lower: str) -> bool:
    keys = (
        "diagnostícate", "diagnosticate", "diagnóstico completo", "diagnostico completo",
        "revísate", "revisate", "revisa todos los sistemas", "revisa todos tus sistemas",
        "comprueba todos los sistemas", "comprueba tus sistemas",
        "haz un diagnóstico", "haz un diagnostico",
        "autodiagnóstico", "autodiagnostico",
        "todo funciona", "estás bien", "estas bien",
        "qué sistemas funcionan", "que sistemas funcionan",
        "cómo están los sistemas", "como estan los sistemas",
        "estado de todos los sistemas", "estado general",
        "revisa el código y", "revisa tu código y",
        "busca errores en tu código", "hay algún error", "hay algun error",
    )
    return any(k in lower for k in keys)


def _wants_reparar(lower: str) -> bool:
    keys = (
        "repárate", "reparate", "repara los errores", "repara el error",
        "corrígete", "corrigete", "corrige los errores", "aplica la reparación",
        "aplica la reparacion", "arréglate", "arreglate",
    )
    return any(k in lower for k in keys)


def _wants_exec_python(text: str) -> tuple[bool, str]:
    """Detecta petición de ejecutar código Python. Devuelve (quiere, código)."""
    lower = text.lower()
    triggers = (
        "ejecuta este código", "ejecuta este codigo",
        "corre este código", "corre este codigo",
        "ejecuta esto:", "ejecuta:", "corre:",
        "ejecuta este script", "corre este script",
        "run esto",
    )
    if not any(t in lower for t in triggers):
        return False, ""
    m = re.search(r"```(?:python)?\n?(.*?)```", text, re.DOTALL)
    if m:
        return True, m.group(1).strip()
    for t in triggers:
        idx = lower.find(t)
        if idx >= 0:
            rest = text[idx + len(t):].strip().lstrip(":\n ")
            if len(rest) > 3:
                return True, rest
    return False, ""


def _wants_recordatorio(lower: str) -> bool:
    keys = (
        "recuérdame", "recuerdame", "recordarme", "recordarme que",
        "ponme un recordatorio", "pon un recordatorio",
        "avísame", "avisame", "mándame un aviso", "mandame un aviso",
        "mándame un recordatorio", "mandame un recordatorio",
        "acuérdate de", "acuerdate de",
        "no me olvides", "no te olvides",
        "que no se me olvide", "no dejes que se me olvide",
        "dime que tengo que",
        "ponme una alarma", "pon una alarma",
        "ponme un aviso", "pon un aviso",
        "puedes recordarme", "puedes avisarme",
        "me puedes recordar", "me puedes avisar",
        # Variantes con "crear"
        "crea un recordatorio", "crear un recordatorio",
        "crees un recordatorio", "crea el recordatorio",
        "crea una alarma", "crear una alarma",
        "crea un aviso", "crear un aviso",
        "añade un recordatorio", "añadir un recordatorio",
        "agrega un recordatorio", "agregar un recordatorio",
        "pon el recordatorio", "configura un recordatorio",
        # Variantes con "hacer"
        "hagas un recordatorio", "hacer un recordatorio",
        "hazme un recordatorio", "haz un recordatorio",
        "hazme una alarma", "haz una alarma",
        "hazme un aviso", "haz un aviso",
        "puedes hacerme un recordatorio", "puedes hacer un recordatorio",
        "me puedes hacer un recordatorio",
        # Variantes con "espero/quiero/necesito que"
        "espero que crees", "espero que pongas", "espero que añadas", "espero que hagas",
        "quiero que crees un recordatorio", "quiero que pongas un recordatorio",
        "quiero que añadas un recordatorio", "quiero que hagas un recordatorio",
        "quiero que me hagas un recordatorio", "quiero que me pongas un recordatorio",
        "quiero que me crees un recordatorio",
        "necesito que crees", "necesito que pongas", "necesito que hagas",
        "necesito que me hagas", "necesito que me pongas",
    )
    if any(k in lower for k in keys):
        return True
    # "en X minutos / horas / días" (dígito o palabra)
    if re.search(r'\ben\s+\w+\s+(?:minutos?|horas?|d[ií]as?)\b', lower):
        return True
    return False


def _wants_listar_recordatorios(lower: str) -> bool:
    keys = (
        # Con sustantivo plural
        "qué recordatorios", "que recordatorios", "mis recordatorios",
        "recordatorios tengo", "recordatorios pendientes",
        "lista de recordatorios", "listar recordatorios",
        "cuáles son mis recordatorios", "cuales son mis recordatorios",
        "tienes recordatorios", "hay recordatorios",
        "ver recordatorios", "muéstrame los recordatorios", "muestrame los recordatorios",
        "dame mis recordatorios", "dame los recordatorios",
        "pon los recordatorios", "ponme los recordatorios",
        "cuántos recordatorios", "cuantos recordatorios",
        "los recordatorios que tengo",
        # Con sustantivo singular
        "algún recordatorio", "algun recordatorio",
        "tengo recordatorio", "tengo algún recordatorio", "tengo algun recordatorio",
        "hay algún recordatorio", "hay algun recordatorio",
        "si tengo recordatorio", "si hay recordatorio",
        "qué recordatorio", "que recordatorio",
        "ver mi recordatorio", "cuál es mi recordatorio", "cual es mi recordatorio",
        # Variantes con "aviso" / "alarma"
        "mis avisos", "mis alarmas", "qué avisos", "que avisos",
        "tengo algún aviso", "tengo algun aviso",
        "hay algún aviso", "hay algun aviso",
        "tengo alguna alarma", "hay alguna alarma",
    )
    return any(k in lower for k in keys)


def _wants_cancelar_recordatorio(lower: str) -> bool:
    # Formas con pronombre (plural) — no necesitan sustantivo
    pronoun_forms = (
        # borrar
        "borrarlos", "bórralos", "borralos",
        "bórralo", "borralo",
        # eliminar
        "eliminarlos", "elimínalos", "eliminalos",
        "elimínalo", "eliminalo",
        # cancelar
        "cancelarlos", "cancélalos", "cancelalos",
        "cancélalo", "cancelalo",
        # quitar
        "quitarlos", "quítalos", "quitalos",
        "quítalo", "quitalo",
        # borrar / quitar + "los" separado
        "borrar los", "eliminar los", "cancelar los", "quitar los",
        # limpiar
        "limpiarlos", "límpialos", "limpialos",
        "límpialos", "limpíalos",
        # suprimir / desactivar / deshacer
        "suprimirlos", "suprímelos", "suprimelos",
        "desactivarlos", "desactívalos", "desactivalos",
        "deshacerlos",
        # borrar todo
        "borrar todo", "eliminar todo", "cancelar todo", "quitar todo",
        "borrar todos", "eliminar todos", "cancelar todos", "quitar todos",
    )
    if any(p in lower for p in pronoun_forms):
        return True
    # "borra todos", "elimínalos todos", "quita todos"
    if re.search(r'\b(borra|elimina|cancela|quita|limpia|suprime|desactiva)\s+(todo|todos|todo\s+eso|los\s+que\s+hay)\b', lower):
        return True
    # "bórralos todos", "cáncelalos todos"
    if re.search(r'\b(borr|elimin|cancel|quit)[aá]\w*\s+(todo|todos)\b', lower):
        return True
    # Forma estándar: verbo + sustantivo
    cancel_verbs = (
        "cancela", "cancelas", "cancelar",
        "borra", "borrar",
        "elimina", "eliminar",
        "quita", "quitar",
        "borralo", "bórralo",
        "suprime", "suprimir",
        "desactiva", "desactivar",
        "limpia", "limpiar",
        "borra el", "elimina el", "cancela el", "quita el",
    )
    record_words = (
        "recordatorio", "recordatorios",
        "alarma", "alarmas",
        "aviso", "avisos",
        "reminder", "reminders",
        "notificación", "notificaciones",
    )
    has_verb = any(v in lower for v in cancel_verbs)
    has_noun = any(n in lower for n in record_words)
    return has_verb and has_noun


# Alias app → clave interna (espejado de apps.py pero sin importar winreg)
_WEB_ALIASES: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "twitch": "https://www.twitch.tv",
    "netflix": "https://www.netflix.com",
    "twitter": "https://www.twitter.com",
    "x": "https://www.x.com",
    "reddit": "https://www.reddit.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "github": "https://www.github.com",
    "gmail": "https://mail.google.com",
    "amazon": "https://www.amazon.es",
    "wikipedia": "https://www.wikipedia.org",
    "chatgpt": "https://chat.openai.com",
    "claude": "https://claude.ai",
    "spotify web": "https://open.spotify.com",
    "primevideo": "https://www.primevideo.com",
    "prime video": "https://www.primevideo.com",
    "hbo": "https://www.max.com",
    "max": "https://www.max.com",
    "crunchyroll": "https://www.crunchyroll.com",
    "pornhub": "https://www.pornhub.com",
    "xvideos": "https://www.xvideos.com",
}

_APP_ALIASES: dict[str, str] = {
    "discord": "discord",
    "spotify": "spotify",
    "steam": "steam",
    "chrome": "chrome",
    "google chrome": "chrome",
    "opera": "opera",
    "opera gx": "opera",
    "firefox": "firefox",
    "mozilla firefox": "firefox",
    "mozilla": "firefox",
    "telegram": "telegram",
    "whatsapp": "whatsapp",
    "notepad": "notepad",
    "bloc de notas": "notepad",
    "notepad++": "notepad++",
    "calculadora": "calc",
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "vscode": "code",
    "visual studio code": "code",
    "vs code": "code",
    "obs": "obs64",
    "obs studio": "obs64",
    "vlc": "vlc",
    "explorador": "explorer",
    "explorador de archivos": "explorer",
    "administrador de tareas": "taskmgr",
    "task manager": "taskmgr",
    "paint": "mspaint",
    "valorant": "valorant",
    "league of legends": "league of legends",
    "lol": "league of legends",
    "riot client": "riot client",
    "epic games": "epicgameslauncher",
    "epic": "epicgameslauncher",
    "battle.net": "battle.net",
    "battlenet": "battle.net",
    "minecraft": "minecraft",
    "origin": "origin",
    "ea app": "eadesktop",
}

_OPEN_VERBS = ("abre", "abrir", "lanza", "lanzar", "pon", "inicia", "arranca", "ejecuta", "abriste")
_CLOSE_VERBS = ("cierra", "cerrar", "mata", "para", "detén", "deten", "apaga", "cerrar el", "cerrar la")


def _norm(text: str) -> str:
    """Elimina acentos/diacríticos para matching robusto."""
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("ascii")


def _wants_pc_comando(lower: str) -> tuple[bool, dict]:
    """Detecta comandos de control del PC. Devuelve (quiere, params_dict)."""
    lower = _norm(lower)

    # Captura de pantalla
    if any(k in lower for k in ("captura de pantalla", "toma una captura", "haz un screenshot",
                                 "haz una captura", "screenshot del pc", "captura del pc",
                                 "screenshot", "captura del escritorio")):
        return True, {"type": "screenshot"}

    # Bloquear pantalla
    if any(k in lower for k in ("bloquea el pc", "bloquea mi pc", "bloquea la pantalla",
                                  "bloquear el pc", "bloquear la pantalla", "cierra sesión",
                                  "cierra la sesion")):
        return True, {"type": "lock"}

    # Minimizar / mostrar escritorio
    if any(k in lower for k in ("minimiza todo", "minimizar todo", "muestra el escritorio",
                                  "enseña el escritorio", "escritorio limpio",
                                  "mostrar el escritorio", "ir al escritorio")):
        return True, {"type": "desktop"}

    # Volumen — subir
    if any(k in lower for k in ("sube el volumen", "sube el audio", "más volumen", "mas volumen",
                                  "aumenta el volumen", "sube el son", "más alto el volumen",
                                  "sube volumen", "subir el volumen", "más alto", "mas alto")):
        return True, {"type": "volume", "action": "up"}

    # Volumen — bajar
    if any(k in lower for k in ("baja el volumen", "baja el audio", "menos volumen",
                                  "reduce el volumen", "baja el son", "baja volumen",
                                  "bajar el volumen", "más bajo", "mas bajo")):
        return True, {"type": "volume", "action": "down"}

    # Silenciar
    if any(k in lower for k in ("silencia", "silenciar", "quita el sonido", "quita el volumen",
                                  "mutea", "mute", "sin sonido", "modo silencio",
                                  "quita el audio", "silencio total")):
        return True, {"type": "volume", "action": "mute"}

    # Volumen al X%
    m = re.search(
        r'(?:pon|sube|baja|deja|ajusta|poner|pone|col[oó]ca)\s+'
        r'(?:el\s+)?(?:volumen|audio|sonido)\s+(?:al|a|en)\s+(\d+)\s*%?', lower
    )
    if m:
        return True, {"type": "volume", "action": "set", "level": int(m.group(1))}
    m2 = re.search(r'(?:volumen|audio|sonido)\s+(?:al|a|en)\s+(\d+)\s*%?', lower)
    if m2:
        return True, {"type": "volume", "action": "set", "level": int(m2.group(1))}

    # Cerrar app — busca alias en el texto
    _close_pats = (
        "cierra el ", "cierra la ", "cierra ", "mata el proceso de ",
        "mata el ", "mata la ", "mata ", "para el ", "para la ",
        "detén el ", "deten el ", "apaga el ", "apaga la ",
    )
    for pat in _close_pats:
        if pat in lower:
            idx = lower.find(pat)
            rest = lower[idx + len(pat):]
            for alias, app_key in _APP_ALIASES.items():
                if alias in rest or alias in lower[max(0, idx - 2):]:
                    return True, {"type": "close", "app": app_key, "display": alias}
            first = rest.strip().split()[0] if rest.strip() else ""
            if first and len(first) > 2 and first not in ("el", "la", "los", "las"):
                return True, {"type": "close", "app": first, "display": first}

    # Abrir web/URL
    for alias, url in _WEB_ALIASES.items():
        for verb in _OPEN_VERBS:
            if (f"{verb} {alias}" in lower
                    or f"{verb} el {alias}" in lower
                    or f"{verb} la {alias}" in lower):
                return True, {"type": "open_url", "url": url, "display": alias}

    # Abrir app
    for alias, app_key in _APP_ALIASES.items():
        for verb in _OPEN_VERBS:
            if (f"{verb} {alias}" in lower
                    or f"{verb} el {alias}" in lower
                    or f"{verb} la {alias}" in lower):
                return True, {"type": "open", "app": app_key, "display": alias}

    return False, {}


# ── Diccionario base: palabras simples → entero ───────────────────────────────
_SIMPLES_ES: dict[str, int] = {
    "cero": 0, "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "trece": 13, "catorce": 14, "quince": 15,
    "dieciséis": 16, "dieciseis": 16,
    "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20,
    "veintiún": 21, "veintiuno": 21, "veintiuna": 21,
    "veintidós": 22, "veintidos": 22,
    "veintitrés": 23, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25,
    "veintiséis": 26, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50,
    # especiales para minutos
    "cuarto": 15, "media": 30,
}

_DECENAS_ES: dict[str, int] = {"treinta": 30, "cuarenta": 40, "cincuenta": 50}

def _parse_num_es(s: str) -> int | None:
    """Parsea cualquier número español 0-59 (dígito, palabra simple o compuesto)."""
    s = s.strip().lower()
    if not s:
        return None
    # Dígito directo
    if re.match(r'^\d+$', s):
        return int(s)
    # Palabra simple
    v = _SIMPLES_ES.get(s)
    if v is not None:
        return v
    # Compuesto: "treinta y dos", "cuarenta y cinco", "cincuenta y nueve"
    m = re.match(r'^(treinta|cuarenta|cincuenta)\s+y\s+(.+)$', s)
    if m:
        decena = _DECENAS_ES[m.group(1)]
        unidad = _SIMPLES_ES.get(m.group(2).strip())
        if unidad is not None and 1 <= unidad <= 9:
            return decena + unidad
    # Viejo estilo sin contraer: "veinte y uno", "veinte y dos"…
    m = re.match(r'^veinte\s+y\s+(.+)$', s)
    if m:
        unidad = _SIMPLES_ES.get(m.group(1).strip())
        if unidad is not None and 1 <= unidad <= 9:
            return 20 + unidad
    return None

def _num_es(s: str) -> int | None:
    """Alias público de _parse_num_es."""
    return _parse_num_es(s)

def _mins_es(s: str) -> int | None:
    """Convierte a minutos (0-59). Devuelve None si el valor no es un minuto válido."""
    v = _parse_num_es(s)
    return v if v is not None and 0 <= v < 60 else None

def _ajustar_hora_española(h: int, lower: str) -> int:
    """Aplica convenio horario español: sin calificador, 1-7 → PM (13-19)."""
    if "de la mañana" in lower or "de la madrugada" in lower:
        return h
    if "de la tarde" in lower or "de la noche" in lower:
        return h + 12 if h < 12 else h
    if 1 <= h <= 7:
        return h + 12
    return h

# Preposiciones de tiempo que preceden a la hora ("a las", "para las", "hacia las"…)
_PREP_HORA = r'(?:a\s+las?|para\s+las?|hacia\s+las?|sobre\s+las?)'

def _parse_recordatorio_regex(text: str) -> tuple[datetime | None, str]:
    """Parsea hora y mensaje del recordatorio con regex, sin usar LLM."""
    now = datetime.now()
    lower = text.lower()
    cuando = None

    # ── Tiempos relativos ──────────────────────────────────────────────────────

    # "en X minutos" / "en veinte minutos"
    m = re.search(r'\ben\s+(\w+)\s+minutos?\b', lower)
    if m:
        mins = _num_es(m.group(1))
        if mins:
            cuando = now + timedelta(minutes=mins)

    # "en X horas" / "en dos horas"
    if not cuando:
        m = re.search(r'\ben\s+(\w+)\s+horas?\b', lower)
        if m:
            hrs = _num_es(m.group(1))
            if hrs:
                cuando = now + timedelta(hours=hrs)

    # "en media hora"
    if not cuando and re.search(r'\ben\s+media\s+hora\b', lower):
        cuando = now + timedelta(minutes=30)

    # "en un cuarto de hora"
    if not cuando and re.search(r'\ben\s+un\s+cuarto\s+de\s+hora\b', lower):
        cuando = now + timedelta(minutes=15)

    # ── Horas absolutas ────────────────────────────────────────────────────────

    # "al mediodía"
    if not cuando and re.search(r'\bal?\s*mediod[ií]a\b', lower):
        cuando = now.replace(hour=12, minute=0, second=0, microsecond=0)

    # "a la medianoche"
    if not cuando and re.search(r'\ba\s+la\s+medianoche\b', lower):
        cuando = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # "a las 14:21" / "a las 3:30" (formato con dos puntos)
    if not cuando:
        m = re.search(_PREP_HORA + r'\s+(\d{1,2}):(\d{2})\b', lower)
        if m:
            h, mins = int(m.group(1)), int(m.group(2))
            if 0 <= h <= 23 and 0 <= mins < 60:
                cuando = now.replace(hour=h, minute=mins, second=0, microsecond=0)

    # "a las X y M" — M puede ser dígito, palabra simple o compuesto ("treinta y dos")
    if not cuando:
        m = re.search(_PREP_HORA + r'\s+(\w+)\s+y\s+(\w+(?:\s+y\s+\w+)?)(?:\s+minutos?)?\b', lower)
        if m:
            h = _num_es(m.group(1))
            mins = _mins_es(m.group(2))
            if h and mins is not None and 0 <= mins < 60:
                cuando = now.replace(hour=_ajustar_hora_española(h, lower), minute=mins, second=0, microsecond=0)

    # "a las X menos cuarto / veinte / [palabra o dígito]"
    if not cuando:
        m = re.search(_PREP_HORA + r'\s+(\w+)\s+menos\s+(\w+(?:\s+y\s+\w+)?)\b', lower)
        if m:
            h = _num_es(m.group(1))
            mins = _mins_es(m.group(2))
            if h and mins:
                h_adj = _ajustar_hora_española(h, lower)
                total = h_adj * 60 - mins
                cuando = now.replace(hour=(total // 60) % 24, minute=total % 60, second=0, microsecond=0)

    # "a las X en punto" / "a las X"
    if not cuando:
        m = re.search(_PREP_HORA + r'\s+(\w+)(?:\s+en\s+punto)?\b', lower)
        if m:
            h = _num_es(m.group(1))
            if h and 0 < h <= 23:
                cuando = now.replace(hour=_ajustar_hora_española(h, lower), minute=0, second=0, microsecond=0)

    if not cuando:
        return None, ""

    # Ajuste de día
    if re.search(r'\bma[ñn]ana\b', lower):
        cuando = cuando + timedelta(days=1)
    elif cuando <= now:
        cuando = cuando + timedelta(days=1)

    # ── Limpiar mensaje ────────────────────────────────────────────────────────
    msg = text

    # Quitar meta-frases del usuario (de más específica a más general)
    _TRIGGERS = [
        # "quiero/necesito/espero que me recuerdes/hagas/pongas..."
        r'(?:quiero|necesito|espero)\s+que\s+me\s+(?:recuerdes|hagas|pongas|crees|digas)\s+(?:un\s+recordatorio\s+)?(?:que\b)?',
        r'(?:quiero|necesito|espero)\s+que\s+(?:me\s+)?(?:hagas|pongas|crees)\s+un\s+(?:recordatorio|aviso|alarma)\b',
        r'(?:quiero|necesito)\s+que\s+(?:recuerdes?|avises?)\s+(?:que\b)?',
        # "puedes recordarme / avisarme..."
        r'puedes?\s+recordarme\s+que\b', r'puedes?\s+recordarme\b',
        r'me\s+puedes?\s+recordar\s+que\b', r'me\s+puedes?\s+recordar\b',
        r'puedes?\s+avisarme\s+que\b', r'puedes?\s+avisarme\b',
        r'me\s+puedes?\s+avisar\s+que\b', r'me\s+puedes?\s+avisar\b',
        r'puedes?\s+ponerme\s+un\s+recordatorio\b',
        r'puedes?\s+hacerme\s+un\s+recordatorio\b',
        # "recuérdame / ponme / avísame..."
        r'recuérdame\s+que\b', r'recuérdame\b', r'recuerdame\s+que\b', r'recuerdame\b',
        r'ponme\s+un\s+recordatorio\s+de\b', r'ponme\s+un\s+recordatorio\b',
        r'pon\s+un\s+recordatorio\b',
        r'avísame\s+que\b', r'avísame\b', r'avisame\s+que\b', r'avisame\b',
        r'acuérdate\s+de\b', r'acuerdate\s+de\b',
        r'no\s+(?:me|te)\s+olvides\s+(?:que|de)\b',
        r'que\s+no\s+se\s+me\s+olvide\b',
        r'dime\s+que\s+tengo\s+que\b',
        r'haz(?:me)?\s+un\s+(?:recordatorio|aviso|alarma)\b',
        r'crea(?:me)?\s+un\s+(?:recordatorio|aviso|alarma)\b',
        r'pon(?:me)?\s+un(?:a)?\s+(?:recordatorio|aviso|alarma)\b',
    ]
    for t in _TRIGGERS:
        msg = re.sub(t, '', msg, flags=re.IGNORECASE)

    # Conversión de primera a segunda persona para que el recordatorio suene natural
    _PRONOMBRES = [
        (r'\btengo que\b', 'tienes que'),
        (r'\btengo\b', 'tienes'),
        (r'\bdebo\b', 'debes'),
        (r'\bnecesito\b', 'necesitas'),
        (r'\bquiero\b', 'quieres'),
        (r'\bvoy a\b', 'vas a'),
        (r'\bmi\b', 'tu'),
        (r'\bmis\b', 'tus'),
        (r'\bme\b', 'te'),
        (r'\byo\b', ''),
    ]
    for patron, reemplazo in _PRONOMBRES:
        msg = re.sub(patron, reemplazo, msg, flags=re.IGNORECASE)

    # Quitar expresiones de tiempo (de más específico a más general)
    _PREP = r'(?:a\s+las?|para\s+las?|hacia\s+las?|sobre\s+las?)'
    _HORA_ES = r'(?:\d{1,2}:\d{2}|\w+(?:\s+y\s+\w+(?:\s+y\s+\w+)?)?(?:\s+(?:en\s+punto|minutos?))?)'
    _TIME_PATS = [
        r'ma[ñn]ana\b',
        r'al?\s*mediod[ií]a\b',
        r'a\s+la\s+medianoche\b',
        _PREP + r'\s+\d{1,2}:\d{2}\b',
        _PREP + r'\s+\w+\s+y\s+\w+(?:\s+y\s+\w+)?(?:\s+minutos?)?\b',
        _PREP + r'\s+\w+\s+menos\s+\w+(?:\s+y\s+\w+)?\b',
        _PREP + r'\s+\w+(?:\s+en\s+punto)?\b',
        r'en\s+\w+\s+(?:minutos?|horas?)\b',
        r'en\s+media\s+hora\b',
        r'en\s+un\s+cuarto\s+de\s+hora\b',
        r'de\s+la\s+(?:mañana|tarde|noche|madrugada)\b',
        r'\bhoras?\b',
        r'\bminutos?\b',
        # Residuos de número+conector que quedan tras quitar la hora ("y veintiocho", "y dos")
        r'^\s*y\s+\w+\b',
        r'\by\s+\w+\s*$',
        # Números sueltos de hora/minuto al inicio (catorce, veintiocho…)
        r'^\s*(?:cero|uno?|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce|trece|catorce|quince|dieciséis|dieciseis|diecisiete|dieciocho|diecinueve|veinte|veintiuno?|veintidós|veintidos|veintitrés|veintitres|veinticuatro|veinticinco|veintiséis|veintiseis|veintisiete|veintiocho|veintinueve|treinta|cuarenta|cincuenta)\b\s*',
    ]
    for p in _TIME_PATS:
        msg = re.sub(p, '', msg, flags=re.IGNORECASE)

    # Quitar conectores/preposiciones sueltos al principio o al final (varias pasadas)
    for _ in range(3):
        msg = re.sub(r'^\s*(?:que|a|de|el|la|los|las|por|para|y)\b\s*', '', msg, flags=re.IGNORECASE)
        msg = re.sub(r'\s*\b(?:que|a|de|y)\s*$', '', msg, flags=re.IGNORECASE)
    msg = re.sub(r'\s+', ' ', msg).strip(" ,.'¿?¡!")

    if not msg:
        msg = text.strip()

    return cuando, msg


def _parse_recordatorio_llm(text: str) -> tuple[datetime | None, str]:
    """Extrae fecha/hora y mensaje del recordatorio. Primero regex, luego LLM como fallback."""
    # Intentar primero con regex (más fiable para español)
    cuando, mensaje = _parse_recordatorio_regex(text)
    if cuando is not None:
        return cuando, mensaje

    # Fallback: usar Groq
    from groq import Groq
    from config import GROQ_API_KEY, GROQ_MODEL
    ahora = datetime.now().strftime("%Y-%m-%dT%H:%M")
    prompt = (
        f"Fecha/hora actual: {ahora}.\n"
        f"Texto: '{text}'\n"
        "Extrae el momento exacto y el texto del recordatorio. "
        "Devuelve SOLO JSON válido sin explicaciones: "
        '{"cuando": "YYYY-MM-DDTHH:MM:00", "mensaje": "texto sin incluir la hora ni el trigger"}. '
        "Si no puedes determinar la hora exacta, devuelve {\"cuando\": null, \"mensaje\": \"\"}."
    )
    try:
        groq = Groq(api_key=GROQ_API_KEY)
        resp = groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        m = re.search(r"\{.*?\}", raw, re.DOTALL)
        if m:
            data = json.loads(m.group())
            if data.get("cuando"):
                return datetime.fromisoformat(data["cuando"]), data.get("mensaje", text)
    except Exception:
        pass
    return None, ""


NOVA_CAPACIDADES = """Capacidades de NOVA
===================

INFORMACIÓN DEL SISTEMA
- Estado de Oracle (CPU, RAM, disco)
- Logs recientes del bot de Telegram
- Errores de Python en Oracle
- Procesos activos de NOVA
- Verificar si el bot está caído o activo
- Inventario de software instalado en Oracle

GESTIÓN DEL BOT
- Reiniciar telegram_bot.py
- Instalar paquetes pip (whitelist: apscheduler, groq, ollama, psutil, python-telegram-bot, requests)
- Actualizar paquetes pip en Oracle
- Desplegar código del PC a Oracle (deploy/sync)

EJECUCIÓN DE CÓDIGO
- Ejecutar scripts Python arbitrarios en Oracle (con confirmación previa)

RECORDATORIOS
- Programar recordatorios: "recuérdame el viernes a las 19:00 que...", "en 30 minutos avísame de...", "avísame mañana a las 9..."

CONTROL DEL PC LOCAL
- Abrir cualquier app instalada: Spotify, Discord, Steam, Chrome, Firefox, Opera, Word, Excel, PowerPoint, VS Code, VLC, OBS, Telegram, WhatsApp, Notepad, Valorant, LoL, Minecraft, y más
- Cerrar apps: "cierra el Discord", "mata el Chrome"
- Captura de pantalla del PC
- Bloquear la pantalla del PC
- Control de volumen: subir, bajar, silenciar, poner al X%
- Mostrar escritorio / minimizar todo

DIAGNÓSTICO Y AUTOREPARACIÓN
- Diagnóstico completo de todos los sistemas
- Reparar errores de sintaxis automáticamente y propagar a Oracle

PLUGINS DINÁMICOS
- Ejecutar plugins instalados en /plugins
- Generar e instalar nuevos plugins con lenguaje natural
- Hot-reload automático de plugins cada 30 segundos

ARCHIVOS
- Crear archivos: .txt, .md, .docx (Word), .xlsx (Excel), .pptx (PowerPoint), .pdf, .py, .html, .csv, y más
- Generar contenido con IA sobre cualquier tema

BÚSQUEDA EN INTERNET
- Búsqueda explícita: "búscame en internet...", "dime el tiempo en...", "busca y dime..."
- Tiempo, fútbol, criptomonedas, noticias, Wikipedia, tipos de cambio, Twitch, películas
"""


def _wants_crear_archivo(lower: str) -> bool:
    keys = (
        # crea
        "crea un archivo", "crea el archivo", "crea un fichero", "crea el fichero",
        "crea un documento", "crea el documento",
        "crea un txt", "crea un .txt", "crea un md", "crea un .md",
        # escribe
        "escribe un archivo", "escribe el archivo",
        "escríbeme un archivo", "escribeme un archivo",
        "escribe en un archivo", "escribe en un fichero",
        "escríbeme un fichero", "escribeme un fichero",
        # genera
        "genera un archivo", "genera el archivo",
        "genera un fichero", "genera el fichero",
        "genera un documento", "genera el documento",
        # haz / hazme
        "haz un archivo", "hazme un archivo",
        "haz un fichero", "hazme un fichero",
        "haz un documento", "hazme un documento",
        # guarda
        "guarda en un archivo", "guarda en un fichero",
        "guárdalo en un archivo", "guardalo en un archivo",
        # necesito / quiero / dame / ponme / prepárame
        "necesito un archivo", "necesito un fichero", "necesito un documento",
        "quiero un archivo", "quiero un fichero", "quiero un documento",
        "dame un archivo", "dame un fichero", "dame un documento",
        "ponme un archivo", "ponme un fichero",
        "prepárame un archivo", "preparame un archivo",
        "prepárame un fichero", "preparame un fichero",
        # redacta / elabora
        "redacta un archivo", "redáctame un archivo", "redactame un archivo",
        "elabora un archivo", "elabórame un archivo", "elaborame un archivo",
        # formas con "crees" (subjuntivo)
        "crees un archivo", "crees el archivo", "crees un fichero", "crees el fichero",
        "crees un documento", "crees el documento",
        # formatos de office nombrados directamente
        "un documento de word", "un documento word",
        "un archivo de word", "un archivo word",
        "un excel", "un archivo excel", "un documento excel",
        "un powerpoint", "una presentación de powerpoint", "una presentacion de powerpoint",
        "un word", "un .docx", "un docx",
        "un worf", "un wor", "crear worf", "crea worf",
        # con "que" intermedio (con o sin pronombre reflexivo "me")
        "necesito que generes", "necesito que crees", "necesito que escribas",
        "necesito que me generes", "necesito que me crees", "necesito que me escribas",
        "quiero que generes", "quiero que crees", "quiero que escribas",
        "quiero que me generes", "quiero que me crees", "quiero que me escribas",
        "podrías crearme", "podrias crearme", "podrías generarme", "podrias generarme",
        "puedes crearme", "puedes generarme", "puedes hacerme",
        "me haces un", "me haces una", "me haces el",
        "prepara un informe", "prepárame un informe", "preparame un informe",
        "prepara una presentación", "prepara una presentacion",
        # hoja de cálculo
        "hoja de cálculo", "hoja de calculo", "una hoja excel",
        "hazme una hoja", "crea una hoja", "necesito una hoja",
        # readme / changelog / markdown
        "crea un readme", "hazme un readme", "crea un changelog",
        # genérico "informe"
        "haz un informe", "hazme un informe", "crea un informe",
        "genera un informe", "redacta un informe",
    )
    return any(k in lower for k in keys)


_EXTENSIONES_TEXTO = {
    "txt", "md", "log", "csv", "json", "xml", "yaml", "yml",
    "html", "htm", "css", "js", "ts", "py", "bat", "sh",
    "ini", "cfg", "toml", "sql", "rst",
}
_EXTENSIONES_OFFICE = {"docx", "xlsx", "pptx"}
_EXTENSIONES_PDF = {"pdf"}
_EXTENSIONES_SOPORTADAS = _EXTENSIONES_TEXTO | _EXTENSIONES_OFFICE | _EXTENSIONES_PDF

_PROMPTS_POR_EXTENSION = {
    "py":   "Escribe un script Python completo y funcional sobre: {tema}. Incluye docstring y comentarios clave.",
    "html": "Escribe una página HTML5 completa con CSS embebido sobre: {tema}. Incluye cabecera, cuerpo y pie.",
    "css":  "Escribe una hoja de estilos CSS completa y bien comentada sobre: {tema}.",
    "js":   "Escribe un script JavaScript completo y funcional sobre: {tema}. Incluye comentarios.",
    "ts":   "Escribe un módulo TypeScript completo sobre: {tema}. Incluye tipos y comentarios.",
    "sql":  "Escribe un script SQL completo sobre: {tema}. Incluye CREATE, INSERT y SELECT relevantes.",
    "sh":   "Escribe un script Bash completo sobre: {tema}. Incluye cabecera shebang y comentarios.",
    "bat":  "Escribe un script batch de Windows completo sobre: {tema}. Incluye cabecera y comentarios.",
    "xml":  "Escribe un documento XML bien formado sobre: {tema}. Incluye declaración y estructura lógica.",
    "json": "Escribe un JSON válido y bien estructurado sobre: {tema}. Solo el JSON, sin texto extra.",
    "yaml": "Escribe un archivo YAML bien estructurado sobre: {tema}. Solo el YAML, sin texto extra.",
    "csv":  "Escribe un CSV con cabecera y al menos 10 filas de datos realistas sobre: {tema}. Solo el CSV.",
    "md":   "Escribe un documento Markdown completo y estructurado sobre: {tema}. Usa headers, listas y énfasis.",
    "ini":  "Escribe un archivo de configuración INI completo sobre: {tema}. Incluye secciones y claves.",
    "toml": "Escribe un archivo TOML de configuración completo sobre: {tema}.",
    "sql":  "Escribe un script SQL completo sobre: {tema}.",
}
_PROMPT_DEFAULT = (
    "Escribe un trabajo completo y bien estructurado en español sobre: {tema}. "
    "Incluye introducción, desarrollo y conclusión. Extensión: 400-600 palabras."
)


def _generar_contenido_llm(tema: str, ext: str = "txt") -> str:
    """Llama a Groq para generar contenido adaptado al tipo de archivo."""
    try:
        from groq import Groq
        from config import GROQ_API_KEY, GROQ_MODEL
        plantilla = _PROMPTS_POR_EXTENSION.get(ext.lower(), _PROMPT_DEFAULT)
        prompt = plantilla.format(tema=tema)
        groq = Groq(api_key=GROQ_API_KEY)
        resp = groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1800,
            temperature=0.7,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"(Error generando contenido: {e})"


def _crear_docx(dest: Path, contenido: str) -> None:
    from docx import Document
    doc = Document()
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if linea.startswith("# "):
            doc.add_heading(linea[2:], level=1)
        elif linea.startswith("## "):
            doc.add_heading(linea[3:], level=2)
        elif linea.startswith("### "):
            doc.add_heading(linea[4:], level=3)
        else:
            doc.add_paragraph(linea)
    doc.save(str(dest))


def _crear_xlsx(dest: Path, contenido: str) -> None:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for i, linea in enumerate(contenido.splitlines(), start=1):
        celdas = [c.strip() for c in linea.split(",")]
        for j, valor in enumerate(celdas, start=1):
            ws.cell(row=i, column=j, value=valor)
    wb.save(str(dest))


def _crear_pptx(dest: Path, contenido: str) -> None:
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    layout = prs.slide_layouts[1]
    lineas = [l.strip() for l in contenido.splitlines() if l.strip()]
    titulo_global = lineas[0] if lineas else "Presentación"
    slide0 = prs.slides.add_slide(prs.slide_layouts[0])
    slide0.shapes.title.text = titulo_global
    bloque: list[str] = []
    titulo_slide = ""
    for linea in lineas[1:]:
        if linea.startswith("#"):
            if bloque or titulo_slide:
                s = prs.slides.add_slide(layout)
                s.shapes.title.text = titulo_slide
                s.placeholders[1].text = "\n".join(bloque)
            titulo_slide = linea.lstrip("#").strip()
            bloque = []
        else:
            bloque.append(linea)
    if titulo_slide or bloque:
        s = prs.slides.add_slide(layout)
        s.shapes.title.text = titulo_slide or titulo_global
        s.placeholders[1].text = "\n".join(bloque)
    prs.save(str(dest))


def _crear_pdf(dest: Path, contenido: str) -> None:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            pdf.ln(4)
            continue
        if linea.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 10, linea[2:])
            pdf.set_font("Helvetica", size=12)
        elif linea.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.multi_cell(0, 8, linea[3:])
            pdf.set_font("Helvetica", size=12)
        else:
            pdf.multi_cell(0, 7, linea)
    pdf.output(str(dest))


def _wants_mostrar(lower: str) -> bool:
    keys = (
        # abrir
        "ábrelo", "abrelo", "abre el archivo", "abre el fichero",
        "y lo abres", "y ábrelo", "y abrelo",
        # mostrar
        "muéstramelo", "muestramelo", "muéstralo", "muestralo",
        "y muéstramelo", "y muestramelo", "y muéstralo", "y muestralo",
        # enseñar
        "enséñamelo", "enseñamelo", "enséñame el", "enseñame el",
        "y enséñamelo", "y enseñamelo",
        # ver
        "quiero verlo", "para verlo", "y lo veo", "y lo pueda ver",
        "y quiero verlo", "quiero ver el resultado",
        # pantalla
        "en pantalla", "en la pantalla",
        # abrir con app
        "y lo abres", "ábremelo", "abremelo",
    )
    return any(k in lower for k in keys)


_TAIL_MOSTRAR = (
    "y muéstramelo", "y muestramelo", "y ábrelo", "y abrelo",
    "en pantalla", "en la pantalla", "y muéstralo", "y muestralo",
    "y enséñamelo", "y enseñamelo", "quiero verlo", "para verlo",
    "y lo abres", "ábremelo", "abremelo",
)

_EXT_PATTERN = r'[\w\-áéíóúüñ]+\.(' + '|'.join(_EXTENSIONES_SOPORTADAS) + r')'

_CONTENIDO_KEYS = (
    # trabajo / ensayo / redacción
    "trabajo sobre", "trabajo acerca de", "trabajo de",
    "ensayo sobre", "ensayo acerca de",
    "redacción sobre", "redaccion sobre",
    # texto / documento
    "texto sobre", "texto acerca de", "texto de",
    "documento sobre", "documento acerca de",
    # escribe / genera / hazme
    "escribe sobre", "escribe acerca de", "escribe un", "escríbeme",
    "escríbeme sobre", "escribeme sobre",
    "genera un", "genera sobre",
    "hazme un", "hazme una",
    # código / script
    "crea un script", "crea un programa", "crea un código", "crea un codigo",
    # página / hoja / presentación
    "crea una página", "crea una pagina",
    "crea una hoja", "crea una presentación", "crea una presentacion",
    # necesito / quiero / dame / ponme
    "necesito un archivo con", "necesito un fichero con",
    "quiero un archivo con", "quiero un fichero con",
    "dame un archivo con", "dame un fichero con",
    "ponme un archivo con", "ponme un fichero con",
    "prepárame un archivo con", "preparame un archivo con",
    # que hable / que trate / acerca de / relacionado
    "que hable de", "que hable sobre",
    "que trate de", "que trate sobre",
    "acerca de", "relacionado con",
    "con información sobre", "con informacion sobre",
    "con contenido sobre",
    # un trabajo (genérico)
    "un trabajo",
)


def _parse_crear_archivo(text: str) -> tuple[str, str, bool]:
    """Extrae (nombre_archivo, contenido, mostrar_en_pantalla) del mensaje del usuario."""
    import re as _re
    lower = text.lower()

    mostrar = _wants_mostrar(lower)

    # Buscar nombre de archivo con extensión soportada
    m = _re.search(_EXT_PATTERN, text, _re.IGNORECASE)
    filename = m.group(0) if m else None

    # Si no hay nombre explícito, inferir extensión por formato coloquial
    if not filename:
        _FORMAT_MAP = (
            (("de word", "en word", " word", "docx", "documento word", "worf", " wor "), "nova_output.docx"),
            (("de excel", "en excel", " excel", "xlsx",
              "hoja de cálculo", "hoja de calculo", "hoja excel"), "nova_output.xlsx"),
            (("de powerpoint", "en powerpoint", " pptx", "presentación",
              "presentacion", "diapositivas", "slides"), "nova_output.pptx"),
            (("pdf",), "nova_output.pdf"),
            (("readme", "read me"), "README.md"),
            (("changelog",), "CHANGELOG.md"),
            (("markdown", " .md", "en md"), "nova_output.md"),
            (("informe", "reporte"), "nova_output.docx"),
        )
        for claves, nombre_default in _FORMAT_MAP:
            if any(c in lower for c in claves):
                filename = nombre_default
                break
        if not filename:
            filename = "nova_output.txt"

    ext = Path(filename).suffix.lstrip(".").lower()

    # Si pide las funciones/capacidades de NOVA → contenido automático
    capacidades_keys = (
        "funciones", "capacidades", "que puedes", "qué puedes",
        "que sabes", "qué sabes", "que haces", "qué haces",
        "que hace nova", "qué hace nova", "comandos",
    )
    if any(k in lower for k in capacidades_keys):
        return filename, NOVA_CAPACIDADES, mostrar

    # Si pide contenido generado por IA → llamar al LLM
    for key in _CONTENIDO_KEYS:
        idx = lower.find(key)
        if idx >= 0:
            tema = text[idx + len(key):].strip().rstrip(".,!?")
            for tail in _TAIL_MOSTRAR:
                if tail in tema.lower():
                    tema = tema[:tema.lower().find(tail)].strip().rstrip(".,")
            # Quitar el nombre del archivo del tema si aparece ahí
            if m and m.group(0).lower() in tema.lower():
                tema = tema[:tema.lower().find(m.group(0).lower())].strip().rstrip(".,")
            if tema:
                contenido = _generar_contenido_llm(tema, ext)
                return filename, contenido, mostrar

    # Intentar extraer contenido literal tras separadores
    for sep in (" con el contenido ", " con contenido ", " con texto ", " que diga ", " que ponga ", ": "):
        idx = lower.find(sep)
        if idx >= 0:
            contenido = text[idx + len(sep):].strip().strip('"').strip("'")
            if contenido:
                return filename, contenido, mostrar

    # Sin contenido especificado → señalizar para pedir aclaración
    return filename, "", mostrar


def _wants_buscar(lower: str) -> bool:
    keys = (
        "busca en internet", "busca en google", "busca en bing",
        "búscame en internet", "buscame en internet",
        "busca y dime", "busca esto",
        "encuentra en internet", "investiga en internet",
        "dime el tiempo en", "cómo está el tiempo en", "como esta el tiempo en",
        "qué tiempo hace en", "que tiempo hace en",
        "noticias de hoy", "últimas noticias de", "ultimas noticias de",
        "precio actual del", "precio actual de",
        "búscame", "buscame",
    )
    return any(k in lower for k in keys)


def _wants_bot_status(lower: str) -> bool:
    keys = (
        "está caído el bot", "esta caido el bot",
        "funciona el bot", "está funcionando el bot", "esta funcionando el bot",
        "el bot está vivo", "el bot esta vivo",
        "está activo el bot", "esta activo el bot",
        "comprueba el bot", "verifica el bot",
        "ping al bot", "estado del telegram bot",
        "está respondiendo telegram", "esta respondiendo telegram",
        "está corriendo el bot", "esta corriendo el bot",
        "el bot responde", "está el bot activo", "esta el bot activo",
    )
    return any(k in lower for k in keys)


def _wants_python_errors(lower: str) -> bool:
    keys = (
        "errores de python", "errores python",
        "últimos errores del servidor", "ultimos errores del servidor",
        "errores en oracle", "errores en el servidor",
        "traceback en oracle", "errores recientes de python",
        "qué ha fallado", "que ha fallado",
        "qué falló en python", "que fallo en python",
        "log de python", "logs de python",
        "qué está petando", "que esta petando",
        "qué está fallando", "que esta fallando",
        "excepciones recientes", "errores de la app",
    )
    return any(k in lower for k in keys)


def _wants_actualizar_oracle(lower: str) -> bool:
    keys = (
        "actualiza los paquetes", "actualiza paquetes",
        "actualiza oracle", "actualiza el servidor",
        "pip upgrade", "actualiza las dependencias",
        "upgrade de paquetes", "actualiza los módulos",
        "actualiza los modulos", "pip update",
    )
    return any(k in lower for k in keys)


def _wants_deploy(lower: str) -> bool:
    keys = (
        "despliega", "deploy", "sincroniza el código", "sincroniza el codigo",
        "actualiza oracle", "sube los cambios", "replica los cambios",
        "push a oracle", "manda los cambios",
    )
    return any(key in lower for key in keys)


def _wants_nueva_capacidad(lower: str) -> bool:
    keys = (
        # ── Imperativo reflexivo ───────────────────────────────────────────────
        "añádete", "añadate",
        "implementate", "impleméntate",
        "instálate", "instalate",
        "créate una función", "create una funcion", "créate una acción", "créate una accion",
        "créate un plugin", "create un plugin",
        "créate un comando", "create un comando",
        "créate una herramienta", "create una herramienta",
        "créate la capacidad", "create la capacidad",
        "dotate de", "dótate de",
        # ── "añadir" ──────────────────────────────────────────────────────────
        "añade una función", "añade una funcion",
        "añade una accion", "añade una acción",
        "añade un plugin", "añade un comando",
        "añade una capacidad", "añade una herramienta",
        "añade la capacidad", "añade la función", "añade la funcion",
        "añadir una función", "añadir una funcion",
        "añadir un plugin", "añadir una capacidad",
        # ── "crear" ──────────────────────────────────────────────────────────
        "crea una función para", "crea una funcion para",
        "crea un plugin para", "crea una capacidad para",
        "crea un comando para", "crea una herramienta para",
        "crea un script para", "crea un programa para",
        "crea la función", "crea la funcion",
        "crea el plugin", "crea el comando",
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
        # ── "hacer" ──────────────────────────────────────────────────────────
        "puedes hacer una función", "puedes hacer una funcion",
        "puedes hacer un plugin", "puedes hacer un comando",
        "puedes hacer una herramienta", "puedes hacer un script",
        "puedes hacer algo para",
        "haz una función para", "haz una funcion para",
        "haz un plugin para", "haz un comando para",
        "haz un script para", "haz una herramienta para",
        "hacer algo para que puedas",
        "hagas algo para que puedas",
        "haz algo para que puedas",
        "podrías hacer algo para",
        "podrias hacer algo para",
        # ── "implementar" ─────────────────────────────────────────────────────
        "puedes implementar",
        "implementa una función", "implementa una funcion",
        "implementa un plugin", "implementa un comando",
        "implementa la función", "implementa la funcion",
        "implementa la accion", "implementa la acción",
        "implementar una función", "implementar una funcion",
        "implementar un plugin", "implementar una capacidad",
        # ── "programar / desarrollar / escribir" ──────────────────────────────
        "puedes programar", "programa una función", "programa un plugin",
        "puedes desarrollar", "desarrolla una función", "desarrolla un plugin",
        "puedes escribir una función", "escribe una función para",
        "escribe un script para", "escribe un plugin para",
        # ── "aprender / enseñar" ──────────────────────────────────────────────
        "aprende a ",
        "puedes aprender a", "podrías aprender a", "podrias aprender a",
        "quiero que aprendas a", "quiero que te aprendas",
        "aprende el comando", "aprende este comando",
        "aprende esta función", "aprende esta funcion",
        "aprende esto", "aprende eso",
        "te enseño a", "te enseñaré a", "voy a enseñarte a",
        "enséñate a", "ensenate a",
        # ── "guardar / memorizar" ─────────────────────────────────────────────
        "guárdate la función", "guardate la función",
        "guárdate esto como", "guardate esto como",
        "guárdalo como capacidad", "guardalo como capacidad",
        "guarda esto como capacidad", "guarda esto como función",
        "memoriza esta función", "memoriza este comando",
        "memoriza esto", "memoriza eso",
        # ── "capacidad / nueva función" ───────────────────────────────────────
        "nueva capacidad",
        "nueva función para", "nueva funcion para",
        "nueva accion para", "nueva acción para",
        "nueva herramienta para",
        "dar la capacidad", "darte la capacidad",
        "tener la capacidad de", "tener capacidad para",
        "puedes añadir esa capacidad", "añadir esa capacidad",
        "necesitas poder",
        # ── "solucionar / arreglar / resolver" ────────────────────────────────
        "puedes solucionar eso", "puedes solucionar esto",
        "puedes arreglar eso", "puedes arreglar esto",
        "puedes resolver eso", "puedes resolver esto",
        "soluciona eso", "soluciona esto",
        "arregla eso para que puedas", "resuelve eso",
        # ── "poder hacer / ser capaz" ─────────────────────────────────────────
        "para que puedas", "para que seas capaz",
        "que seas capaz de", "que puedas hacer",
        "que puedas decirme", "que puedas obtener",
        "que puedas ver", "que puedas leer",
        "quiero que puedas", "quiero que seas capaz",
        "necesito que puedas",
        # ── "configurar / dotar" ──────────────────────────────────────────────
        "configúrate para", "configurate para",
        "configúrate con", "configurate con",
        "dótate de", "dotate de",
        "equípate con", "equipate con",
    )
    return any(k in lower for k in keys)


_PRONOMBRES_REF = (
    "eso", "esto", "lo anterior", "lo de antes",
    "esa función", "esa funcion", "esa capacidad", "ese plugin",
    "ese comando", "esa herramienta", "ese script",
    "lo que dijiste", "lo que pedí antes", "lo que pedí",
    "lo que acabas de decir", "lo que mencionaste",
    "la solución", "el problema", "lo que falta",
    "lo que no puedes", "lo que no sabes", "lo que no tienes",
    "esa tarea", "esa función que", "esa acción",
)


def _resolver_ref_historial(texto: str, historial: list | None) -> str:
    """Sustituye referencias vagas ('eso', 'esto'...) por el mensaje anterior del usuario."""
    lower = texto.lower()
    if not any(p in lower for p in _PRONOMBRES_REF):
        return texto
    if not historial:
        return texto
    for entry in reversed(historial[:-1] if len(historial) > 1 else historial):
        if entry.get("role") == "user":
            contenido = entry["content"]
            if "Alex dice:" in contenido:
                contenido = contenido.split("Alex dice:")[-1].strip()
            if len(contenido) > 5:
                mlog("ACCIONES", f"Ref resuelta: '{texto[:40]}' → '{contenido[:60]}'")
                return contenido
    return texto


def _maybe_handle_plugin(text: str) -> dict | None:
    lower = text.lower()
    for plugin in _plugins:
        keywords = getattr(plugin, "KEYWORDS", [])
        if any(kw.lower() in lower for kw in keywords):
            needs_confirm = getattr(plugin, "NEEDS_CONFIRM", False)
            desc = getattr(plugin, "DESCRIPTION", getattr(plugin, "__name__", "plugin"))
            if needs_confirm:
                prompt = f"Voy a ejecutar: {desc}. Responde `SI` para confirmar."
                _set_pending("run_plugin", {"plugin_stem": plugin.__name__, "text": text}, prompt)
                _audit("pending", text, {"action": "run_plugin", "plugin": plugin.__name__})
                return {"handled": True, "reply": prompt}
            try:
                result = plugin.ejecutar({"text": text})
                _audit("executed", text, {"action": "run_plugin", "plugin": plugin.__name__})
                return {"handled": True, "reply": str(result)}
            except Exception as e:
                return {"handled": True, "reply": f"Error en plugin `{plugin.__name__}`: {e}"}
    return None


def _wants_oracle_inventory_match(lower: str) -> bool:
    oracle_refs = ("oracle", "maquina de oracle", "servidor oracle")
    install_refs = (
        "que tiene instalado",
        "que hay instalado",
        "que tiene dentro",
        "que lleva instalado",
        "dime lo que tiene instalado",
        "ver que tiene instalado",
    )
    return any(ref in lower for ref in oracle_refs) and any(ref in lower for ref in install_refs)


def maybe_handle_action_request(text: str, historial: list | None = None) -> dict | None:
    stripped = text.strip()
    # Resolver referencias vagas antes de cualquier matcher
    stripped = _resolver_ref_historial(stripped, historial)
    lower = stripped.lower()

    pending = _load_state().get("pending")
    if pending:
        # Flujo especial: esperando query de búsqueda
        if pending.get("params", {}).get("esperando_query"):
            _clear_pending()
            return _execute_action("buscar_internet", {"query": stripped}, stripped)

        # Flujo especial: esperando detalles del recordatorio
        if pending.get("params", {}).get("esperando_recordatorio"):
            # Solo tratar como recordatorio si la respuesta tiene sentido como tal.
            # Si parece un comando nuevo independiente, cancelar el pending.
            _RECORDATORIO_WORDS = (
                "recordar", "recuérda", "recuerda", "avisa", "aviso",
                "a las", "mañana", "hoy", "esta noche", "esta tarde",
                "en una hora", "en dos horas", "en media hora",
                "minuto", "hora", "día", "semana",
                "que tengo", "que debo", "que hay que",
                "no olvides", "no me olvides",
                "comer", "tomar", "llamar", "ir a", "reunión",
            )
            _NUEVA_PETICION_STARTS = (
                "¿puedes", "puedes", "¿sabes", "sabes",
                "¿qué", "qué", "¿cómo", "cómo", "¿cuál", "cuál",
                "dime", "muéstrame", "muestrame", "abre", "cierra",
                "busca", "encuentra", "pon", "quita",
            )
            lower_resp = stripped.lower()
            parece_recordatorio = any(w in lower_resp for w in _RECORDATORIO_WORDS)
            parece_nueva_peticion = any(lower_resp.startswith(p) for p in _NUEVA_PETICION_STARTS)
            if not parece_recordatorio or parece_nueva_peticion:
                _clear_pending()
                # Continuar procesamiento normal (no return aquí)
            else:
                _clear_pending()
                return _execute_action("nueva_recordatorio", {"text": stripped, "is_retry": True}, stripped)

        # Flujo especial: esperando app a abrir
        if pending.get("params", {}).get("esperando_app"):
            _clear_pending()
            pc_type = pending["params"].get("pc_type", "open")
            app_key = stripped.lower().strip()
            app_name = _APP_ALIASES.get(app_key, app_key)
            return _execute_action("pc_command", {"type": pc_type, "app": app_name, "display": app_key}, stripped)

        # Flujo especial: esperando que el usuario diga el tema del archivo
        if pending.get("params", {}).get("esperando_tema"):
            params = pending["params"]
            filename = params.get("filename") or "nova_output.docx"
            mostrar = params.get("mostrar", False)
            ext = Path(filename).suffix.lstrip(".").lower()
            tema = stripped.strip()
            contenido = _generar_contenido_llm(tema, ext)
            preview = contenido[:400] + ("\n...[truncado]" if len(contenido) > 400 else "")
            extra = " Luego lo abriré en pantalla." if mostrar else ""
            prompt = (
                f"Voy a crear el archivo `{filename}` con este contenido:\n"
                f"```\n{preview}\n```\n{extra}\nResponde `SI` para confirmar."
            )
            _set_pending("crear_archivo", {"filename": filename, "contenido": contenido, "mostrar": mostrar}, prompt)
            _audit("pending", stripped, {"action": "crear_archivo", "filename": filename})
            return {"handled": True, "reply": prompt}

        clean = lower.replace(",", "").replace(".", "").replace("¡", "").replace("!", "").replace("¿", "").replace("?", "")
        words = set(clean.split())
        _CONFIRM = {
            "si", "sí", "yes", "ok", "okay", "okey", "vale", "venga", "dale",
            "claro", "perfecto", "correcto", "exacto", "afirmativo", "confirmo",
            "de acuerdo", "por supuesto", "adelante", "procede", "continua", "continúa",
            "hazlo", "haz", "ejecuta", "ejecutalo", "sigue", "anda", "va",
            "sin problema", "sin problemas", "eso es", "así es", "asi es",
            "venga va", "vamos", "a por ello",
        }
        _CANCEL = {
            "no", "nope", "nel", "para nada", "cancela", "cancelar", "cancelado",
            "abort", "abortar", "para", "detente", "detener", "stop",
            "olvida", "olvídalo", "olvidalo", "dejalo", "déjalo",
            "mejor no", "al final no", "que no", "no lo hagas",
            "no hace falta", "no importa", "no pasa nada",
        }
        _STT_CONFIRM = ["script", "ok", "dale", "haz", "ejecuta", "venga", "adelante"]
        if words & _CONFIRM or any(s in clean for s in _STT_CONFIRM):
            _clear_pending()
            return _execute_action(pending["action"], pending.get("params", {}), stripped)
        if words & _CANCEL or any(p in lower for p in ("mejor no", "al final no", "que no", "no lo hagas", "no hace falta")):
            prompt = pending.get("prompt", "Acción cancelada.")
            _clear_pending()
            _audit("cancelled", stripped, {"pending": pending})
            return {"handled": True, "reply": "Cancelado."}

    if _wants_crear_archivo(lower):
        filename, contenido, mostrar = _parse_crear_archivo(stripped)
        if not contenido:
            ext = Path(filename).suffix.lstrip(".").lower() if filename else "docx"
            _set_pending("crear_archivo", {"filename": filename, "contenido": None, "mostrar": mostrar, "esperando_tema": True}, "")
            return {"handled": True, "reply": f"¿Sobre qué quieres que sea el {ext.upper()}?"}
        preview = contenido[:400] + ("\n...[truncado]" if len(contenido) > 400 else "")
        extra = " Luego lo abriré en pantalla." if mostrar else ""
        prompt = (
            f"Voy a crear el archivo `{filename}` con este contenido:\n"
            f"```\n{preview}\n```\n{extra}\nResponde `SI` para confirmar."
        )
        _set_pending("crear_archivo", {"filename": filename, "contenido": contenido, "mostrar": mostrar}, prompt)
        _audit("pending", stripped, {"action": "crear_archivo", "filename": filename})
        return {"handled": True, "reply": prompt}

    if _wants_nueva_capacidad(lower):
        # Extraer la parte descriptiva quitando el trigger
        _NC_TRIGGERS = (
            "añádete una función para", "añadate una función para",
            "añade una función para", "añade una funcion para",
            "crea una función para", "crea una funcion para",
            "crea un plugin para", "crea una capacidad para",
            "crea un comando para", "crea una herramienta para",
            "crea un script para", "puedes crear una función",
            "puedes crear una funcion", "puedes crear un plugin",
            "puedes crear una capacidad", "puedes hacer una función",
            "puedes hacer una funcion", "puedes hacer algo para",
            "puedes implementar", "implementa una función para",
            "implementa una funcion para", "aprende a ",
            "puedes aprender a", "quiero que aprendas a",
            "créate una función para", "create una funcion para",
            "haz una función para", "haz un script para",
            "hacer algo para que puedas", "hagas algo para que puedas",
            "para que puedas", "quiero que puedas", "necesito que puedas",
            "instálate", "instalate",
        )
        desc = stripped
        for trigger in _NC_TRIGGERS:
            if lower.startswith(trigger.lower()):
                desc = stripped[len(trigger):].strip(" .?¿¡!")
                break
        # Si la descripción resultante es vaga o vacía, usar el historial
        _VAGUE = {"la función", "la funcion", "el plugin", "la capacidad",
                  "la solución", "la solucion", "la acción", "la accion",
                  "la herramienta", "el comando", "el script", "eso", "esto",
                  "lo anterior", ""}
        if not desc or desc.lower() in _VAGUE or len(desc) < 8:
            resolved = _resolver_ref_historial(stripped, historial)
            if resolved != stripped and len(resolved) > len(desc):
                desc = resolved
            elif historial:
                # Buscar el último mensaje de usuario que NOVA no pudo responder
                for entry in reversed(historial[:-1] if len(historial) > 1 else historial):
                    if entry.get("role") == "user":
                        contenido = entry.get("content", "")
                        if "Alex dice:" in contenido:
                            contenido = contenido.split("Alex dice:")[-1].strip()
                        if len(contenido) > 8 and not _wants_nueva_capacidad(contenido.lower()):
                            desc = contenido
                            break
        if not desc:
            desc = stripped
        return _execute_action("nueva_capacidad", {"descripcion": desc}, stripped)

    wants_exec, py_code = _wants_exec_python(stripped)
    if wants_exec and py_code:
        preview = py_code[:600] + ("\n...[truncado]" if len(py_code) > 600 else "")
        prompt = f"Voy a ejecutar este código Python en Oracle:\n```python\n{preview}\n```\nResponde `SI` para confirmar."
        _set_pending("exec_python", {"code": py_code}, prompt)
        _audit("pending", stripped, {"action": "exec_python"})
        return {"handled": True, "reply": prompt}

    if _wants_cancelar_recordatorio(lower):
        return _execute_action("cancelar_recordatorio", {"text": stripped}, stripped)

    if _wants_listar_recordatorios(lower):
        return _execute_action("listar_recordatorios", {}, stripped)

    if _wants_recordatorio(lower):
        return _execute_action("nueva_recordatorio", {"text": stripped}, stripped)

    wants_pc, pc_params = _wants_pc_comando(lower)
    if wants_pc:
        pc_type = pc_params.get("type", "")
        if pc_type in ("open", "close") and not pc_params.get("app"):
            verb = "abrir" if pc_type == "open" else "cerrar"
            _set_pending("pc_command", {"esperando_app": True, "pc_type": pc_type}, "")
            return {"handled": True, "reply": f"¿Qué aplicación quieres {verb}?"}
        if pc_type == "screenshot":
            prompt = "Voy a tomar una captura de pantalla de tu PC. Responde `SI` para confirmar."
            _set_pending("pc_command", pc_params, prompt)
            _audit("pending", stripped, {"action": "pc_command", "type": "screenshot"})
            return {"handled": True, "reply": prompt}
        if pc_type == "lock":
            prompt = "Voy a bloquear la pantalla del PC. Responde `SI` para confirmar."
            _set_pending("pc_command", pc_params, prompt)
            _audit("pending", stripped, {"action": "pc_command", "type": "lock"})
            return {"handled": True, "reply": prompt}
        if pc_type == "close":
            display = pc_params.get("display", pc_params.get("app", "la app"))
            prompt = f"Voy a cerrar `{display}`. Responde `SI` para confirmar."
            _set_pending("pc_command", pc_params, prompt)
            _audit("pending", stripped, {"action": "pc_command", "type": "close", "app": display})
            return {"handled": True, "reply": prompt}
        return _execute_action("pc_command", pc_params, stripped)

    # Los plugins tienen prioridad sobre los matchers built-in
    plugin_result = _maybe_handle_plugin(stripped)
    if plugin_result:
        return plugin_result

    package = _match_install(stripped)
    if package:
        if package not in ALLOWED_PIP_PACKAGES:
            return {
                "handled": True,
                "reply": (
                    f"`{package}` no está en la whitelist de instalación automática.\n"
                    f"Permitidos: {', '.join(sorted(ALLOWED_PIP_PACKAGES))}"
                ),
            }
        prompt = f"Voy a instalar `{package}` en Oracle. Responde `SI` para confirmar."
        _set_pending("install_pip", {"package": package}, prompt)
        _audit("pending", stripped, {"action": "install_pip", "package": package})
        return {"handled": True, "reply": prompt}

    if _wants_restart(lower):
        prompt = "Voy a reiniciar `telegram_bot.py` en Oracle. Responde `SI` para confirmar."
        _set_pending("restart_bot", {}, prompt)
        _audit("pending", stripped, {"action": "restart_bot"})
        return {"handled": True, "reply": prompt}

    if _wants_logs(lower):
        return _execute_action("show_logs", {}, stripped)
    if _wants_status(lower):
        return _execute_action("show_status", {}, stripped)
    if _wants_processes(lower):
        return _execute_action("show_processes", {}, stripped)
    if _wants_oracle_inventory_match(lower):
        return _execute_action("oracle_inventory", {}, stripped)
    if _wants_tts_test(lower):
        return _execute_action("tts_test", {}, stripped)

    if _wants_diagnostico(lower):
        return _execute_action("diagnosticar", {}, stripped)

    if _wants_reparar(lower):
        return _execute_action("reparar_errores", {}, stripped)

    if _wants_deploy(lower):
        prompt = "Voy a sincronizar el código del PC a Oracle y reiniciar los servicios. Responde `SI` para confirmar."
        _set_pending("deploy", {}, prompt)
        _audit("pending", stripped, {"action": "deploy"})
        return {"handled": True, "reply": prompt}

    if _wants_buscar(lower):
        _BUSCAR_PREFIXES = (
            "busca en internet", "busca en google", "busca en bing",
            "búscame en internet", "buscame en internet",
            "busca y dime", "busca esto", "encuentra en internet",
            "investiga en internet", "búscame", "buscame",
        )
        topic = lower
        for pfx in sorted(_BUSCAR_PREFIXES, key=len, reverse=True):
            if topic.startswith(pfx):
                topic = stripped[len(pfx):].strip().lstrip(",:").strip()
                break
        if not topic or topic == stripped:
            _set_pending("buscar_internet", {"query": None, "esperando_query": True}, "")
            return {"handled": True, "reply": "¿Qué quieres que busque?"}
        return _execute_action("buscar_internet", {"query": topic}, stripped)

    if _wants_bot_status(lower):
        return _execute_action("bot_status", {}, stripped)

    if _wants_python_errors(lower):
        return _execute_action("python_errors", {}, stripped)

    if _wants_actualizar_oracle(lower):
        prompt = "Voy a actualizar los paquetes pip en Oracle. Responde `SI` para confirmar."
        _set_pending("actualizar_oracle", {}, prompt)
        _audit("pending", stripped, {"action": "actualizar_oracle"})
        return {"handled": True, "reply": prompt}

    return None


def _replicar_plugin(filename: str, code: str) -> str:
    """Replica el plugin al otro nodo. Windows→Oracle via SCP; Oracle→Windows via /nova/write."""
    import sys
    import requests as _req
    from config import PC_TAILSCALE_IP, ALMACEN_TOKEN

    if sys.platform == "win32":
        # Estamos en Windows: SCP solo este plugin a Oracle
        plugin_path = BASE_DIR / "plugins" / filename
        try:
            r = subprocess.run(
                ["scp", "-i", str(SSH_KEY_PATH), "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=8", str(plugin_path),
                 f"{SSH_HOST}:/home/ubuntu/nova/plugins/{filename}"],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                return "Replicado a Oracle."
            return f"Oracle no alcanzable: {(r.stdout + r.stderr).strip()[:120]}"
        except Exception as e:
            return f"Error replicando a Oracle: {e}"
    else:
        # Estamos en Oracle: push al PC Windows via servidor.py /nova/write
        try:
            resp = _req.post(
                f"http://{PC_TAILSCALE_IP}:5000/nova/write",
                json={"path": f"plugins/{filename}", "content": code},
                headers={"X-Nova-Token": ALMACEN_TOKEN},
                timeout=10,
            )
            if resp.status_code == 200:
                return "Replicado al PC local."
            return f"PC no alcanzable (HTTP {resp.status_code})."
        except Exception as e:
            return f"PC offline o sin respuesta: {e}"


def _execute_action(action: str, params: dict, original_message: str) -> dict:
    if action == "show_logs":
        mlog("MOTOR", "Accediendo al sistema de archivos → telegram_bot.log")
        path = _bot_log_path()
        if not path:
            reply = "No encuentro `telegram_bot.log` todavía."
        else:
            try:
                reply = f"Últimas líneas de `{path}`:\n```text\n{_tail_text(path.read_text(encoding='utf-8', errors='replace'))}\n```"
            except Exception as exc:
                reply = f"No pude leer el log: {exc}"

    elif action == "show_status":
        mlog("MOTOR", "Consultando métricas de sistema: CPU, RAM, disco...")
        code, output = _run_command([sys.executable, "-c", "import psutil; d=psutil.disk_usage('/'); print(f'CPU: {psutil.cpu_percent(interval=0.4)}%\\nRAM: {psutil.virtual_memory().percent}%\\nDISCO: {d.percent}% usado, {round(d.free/1e9,1)} GB libres')"], timeout=10)
        reply = output if code == 0 else f"Error sacando estado:\n```text\n{output}\n```"

    elif action == "show_processes":
        mlog("MOTOR", "Inspeccionando tabla de procesos del sistema...")
        code, output = _run_command(["ps", "-ef"], timeout=10)
        if code == 0:
            filtered = [line for line in output.splitlines() if "nova" in line.lower() or "telegram_bot.py" in line.lower()]
            body = "\n".join(filtered[-20:]) if filtered else "No veo procesos de NOVA ahora mismo."
            reply = f"```text\n{body}\n```"
        else:
            reply = f"Error leyendo procesos:\n```text\n{output}\n```"

    elif action == "oracle_inventory":
        mlog("MOTOR", "Conectando por SSH a Oracle para inspeccionar software instalado...")
        remote_cmd = (
            "python3 -c \"import importlib.util, shutil; "
            "mods=['ollama','groq','telegram','apscheduler','psutil','requests']; "
            "bins=['python3','pip','ollama','tailscale','ffmpeg']; "
            "present=[m for m in mods if importlib.util.find_spec(m) is not None]; "
            "missing=[m for m in mods if m not in present]; "
            "found=[b for b in bins if shutil.which(b)]; "
            "print('PYTHON=' + ', '.join(present)); "
            "print('BINARIOS=' + ', '.join(found)); "
            "print('FALTAN=' + (', '.join(missing) if missing else 'ninguno'))\""
        )
        code, output = _run_oracle_ssh(remote_cmd, timeout=25)
        if code == 0:
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            summary = ". ".join(line.replace("=", ": ") for line in lines[:3])
            reply = f"En Oracle veo esto instalado. {summary}."
        else:
            reply = f"No pude inspeccionar Oracle por SSH:\n```text\n{_tail_text(output, max_lines=25)}\n```"

    elif action == "install_pip":
        package = params["package"]
        mlog("MOTOR", f"Ejecutando instalación de paquete: {package}")
        code, output = _run_command([sys.executable, "-m", "pip", "install", package], timeout=120)
        if code == 0:
            mlog("MOTOR", f"Paquete '{package}' instalado correctamente.")
            reply = f"`{package}` instalado correctamente."
        else:
            mlog("ERROR", f"Fallo en instalación de '{package}'.")
            reply = f"Falló la instalación de `{package}`:\n```text\n{_tail_text(output, max_lines=25)}\n```"

    elif action == "restart_bot":
        mlog("MOTOR", "Ejecutando reinicio del proceso telegram_bot.py...")
        _restart_bot_async()
        reply = "Reiniciando `telegram_bot.py`."

    elif action == "tts_test":
        reply = "Escríbeme algo como `hola, respóndeme en voz` y te mando la nota de voz."

    elif action == "diagnosticar":
        mlog("DIAGNÓSTICO", "Lanzando diagnóstico distribuido completo...")
        try:
            from diagnostico import diagnosticar_todo, resumen_voz
            reporte = diagnosticar_todo()
            resumen = resumen_voz(reporte)
            errores_local  = reporte["sintaxis"].get("errores", {})
            errores_oracle = reporte.get("sintaxis_oracle", {}).get("errores", {})
            hay_errores = errores_local or errores_oracle
            if hay_errores:
                partes_err = []
                if errores_local:
                    partes_err.append(f"locales: {', '.join(errores_local.keys())}")
                if errores_oracle:
                    partes_err.append(f"Oracle: {', '.join(errores_oracle.keys())}")
                desc = "; ".join(partes_err)
                prompt_rep = (
                    f"He encontrado errores de sintaxis ({desc}). "
                    "Responde SI para que los repare automáticamente y los despliegue."
                )
                _set_pending("reparar_errores", {"reporte": reporte}, prompt_rep)
                reply = f"{resumen} {prompt_rep}"
            else:
                reply = resumen
        except Exception as e:
            reply = f"Error ejecutando diagnóstico: {e}"

    elif action == "reparar_errores":
        mlog("DIAGNÓSTICO", "Iniciando autoreparación + propagación de errores de sintaxis...")
        try:
            from diagnostico import diagnosticar_todo, reparar_errores_sintaxis
            reporte = params.get("reporte") or diagnosticar_todo()
            resultados = reparar_errores_sintaxis(reporte, propagar=True)
            if not resultados:
                reply = "No había errores de sintaxis que reparar."
            else:
                reparados_local  = [r["archivo"] for r in resultados if r.get("ok") and r.get("nodo") == "local"]
                reparados_oracle = [r["archivo"] for r in resultados if r.get("ok") and r.get("nodo") == "oracle"]
                deploy_r         = next((r for r in resultados if r.get("accion") == "deploy"), None)
                reinicio_r       = next((r for r in resultados if r.get("accion") == "reinicio_oracle"), None)
                fallos           = [
                    f"{r.get('archivo', r.get('accion', '?'))}: {r.get('motivo', '?')}"
                    for r in resultados if not r.get("ok")
                ]
                partes = []
                if reparados_local:
                    partes.append(f"Reparados local: {', '.join(reparados_local)}")
                if reparados_oracle:
                    partes.append(f"Reparados en Oracle: {', '.join(reparados_oracle)}")
                if deploy_r and deploy_r.get("ok"):
                    partes.append("Deploy completado — Oracle actualizado y reiniciado")
                elif reinicio_r and reinicio_r.get("ok"):
                    partes.append("Servicios de Oracle reiniciados")
                if fallos:
                    partes.append(f"No pude reparar: {'; '.join(fallos)}")
                reply = ". ".join(partes) + "." if partes else "Proceso completado sin cambios."
        except Exception as e:
            reply = f"Error en autoreparación: {e}"

    elif action == "deploy":
        mlog("MOTOR", "Iniciando despliegue de código local → Oracle...")
        try:
            from deploy import ejecutar_deploy
            reply = ejecutar_deploy()
        except Exception as e:
            reply = f"Error en deploy: {e}"

    elif action == "nueva_capacidad":
        descripcion = params.get("descripcion", original_message)
        # Quitar el trigger del inicio para quedarnos solo con "qué hacer"
        for prefix in (
            "añádete una función para", "añadate una función para",
            "añade una función para", "aprende a", "implementate para",
            "créate una función para", "nueva función para", "nueva capacidad para",
            "quiero que aprendas a", "puedes aprender a", "instálate",
        ):
            if descripcion.lower().startswith(prefix):
                descripcion = descripcion[len(prefix):].strip()
                break
        mlog("PLUGINS", f"Generando plugin: {descripcion[:60]}")
        try:
            from plugin_generator import generar_plugin, guardar_plugin
            code, resultado = generar_plugin(descripcion)
            if code is None:
                reply = f"No pude generar el plugin: {resultado}"
            else:
                guardar_plugin(code, resultado)
                _cargar_plugins()
                sync_msg = _replicar_plugin(resultado, code)
                nombre_limpio = resultado.replace("_", " ").replace(".py", "").strip()
                reply = f"Listo. Plugin '{nombre_limpio}' instalado. {sync_msg}"
        except Exception as e:
            reply = f"Error generando capacidad: {e}"

    elif action == "install_plugin":
        code = params.get("code", "")
        filename = params.get("filename", "plugin_nuevo.py")
        try:
            from plugin_generator import guardar_plugin
            guardar_plugin(code, filename)
            _cargar_plugins()
            n = len(_plugins)
            sync_msg = _replicar_plugin(filename, code)
            reply = f"Plugin `{filename}` instalado ({n} activos). {sync_msg}"
        except Exception as e:
            reply = f"Error instalando plugin: {e}"

    elif action == "run_plugin":
        plugin_stem = params.get("plugin_stem", "")
        text_orig = params.get("text", original_message)
        plugin = next((p for p in _plugins if p.__name__ == plugin_stem), None)
        if plugin is None:
            reply = f"Plugin `{plugin_stem}` no encontrado. Puede que no esté cargado."
        else:
            try:
                result = plugin.ejecutar({"text": text_orig})
                reply = str(result)
            except Exception as e:
                reply = f"Error ejecutando plugin: {e}"

    elif action == "exec_python":
        code = params.get("code", "")
        mlog("EXEC", f"Ejecutando código Python ({len(code)} chars) en Oracle...")
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True,
                timeout=15, encoding="utf-8", errors="replace",
            )
            output = (result.stdout + result.stderr).strip()
            if not output:
                output = f"(sin output — código de salida {result.returncode})"
            reply = f"```\n{output[:2000]}\n```"
        except subprocess.TimeoutExpired:
            reply = "Timeout: el código tardó más de 15 segundos."
        except Exception as e:
            reply = f"Error ejecutando código: {e}"

    elif action == "listar_recordatorios":
        from recordatorios import listar_pendientes
        pendientes = listar_pendientes()
        if not pendientes:
            reply = "No tienes recordatorios pendientes."
        else:
            lineas = []
            for r in pendientes:
                dt = datetime.fromisoformat(r["cuando"]).strftime("%d/%m a las %H:%M")
                lineas.append(f"[{r['id']}] {dt} — {r['mensaje']}")
            reply = "Recordatorios pendientes:\n" + "\n".join(lineas)

    elif action == "cancelar_recordatorio":
        from recordatorios import listar_pendientes, cancelar
        text_orig = params.get("text", original_message).lower()
        pendientes = listar_pendientes()
        if not pendientes:
            reply = "No tienes recordatorios pendientes que borrar."
        else:
            # "cancela todos" / "borrarlos" / cualquier pronombre de masa
            _all_triggers = (
                "todos", "todo", "todos los", "todo eso", "los que hay",
                "borralos", "bórralos", "borrarlos", "borralo", "bórralo",
                "eliminarlos", "elimínalos", "eliminalos", "elimínalo", "eliminalo",
                "cancelarlos", "cancélalos", "cancelalos", "cancélalo", "cancelalo",
                "quitarlos", "quítalos", "quitalos", "quítalo", "quitalo",
                "limpiarlos", "límpialos", "limpialos",
                "suprimirlos", "suprímelos", "suprimelos",
                "borrar todos", "eliminar todos", "cancelar todos", "quitar todos",
                "borrar todo", "eliminar todo", "cancelar todo", "quitar todo",
                "borrar los", "eliminar los", "cancelar los", "quitar los",
            )
            if any(p in text_orig for p in _all_triggers) or re.search(r'\b(borr|elimin|cancel|quit)[aá]\w*\s+(todo|todos)\b', text_orig):
                for r in pendientes:
                    cancelar(r["id"])
                reply = f"Borrados {len(pendientes)} recordatorio{'s' if len(pendientes) != 1 else ''}."
            else:
                # Buscar ID mencionado en el texto
                m = re.search(r'\b([0-9a-f]{8})\b', text_orig)
                if m:
                    rid = m.group(1)
                    if cancelar(rid):
                        reply = f"Recordatorio [{rid}] eliminado."
                    else:
                        reply = f"No encontré el recordatorio [{rid}]."
                elif len(pendientes) == 1:
                    # Solo hay uno, borrarlo directamente
                    cancelar(pendientes[0]["id"])
                    dt = datetime.fromisoformat(pendientes[0]["cuando"]).strftime("%d/%m a las %H:%M")
                    reply = f"Recordatorio eliminado: '{pendientes[0]['mensaje']}' ({dt})."
                else:
                    # Listarlos para que elija
                    lineas = []
                    for r in pendientes:
                        dt = datetime.fromisoformat(r["cuando"]).strftime("%d/%m a las %H:%M")
                        lineas.append(f"[{r['id']}] {dt} — {r['mensaje']}")
                    reply = "¿Cuál quieres borrar?\n" + "\n".join(lineas)

    elif action == "nueva_recordatorio":
        text_orig = params.get("text", original_message)
        mlog("RECORDATORIO", f"Parseando recordatorio: {text_orig[:60]}")
        cuando, mensaje = _parse_recordatorio_llm(text_orig)
        if cuando is None:
            if params.get("is_retry"):
                return {"handled": True, "reply": "No entendí la hora o el mensaje. Dime algo como: 'Recuérdame comer a las 12:15'."}
            _set_pending("nueva_recordatorio", {"esperando_recordatorio": True}, "")
            return {"handled": True, "reply": "¿Qué quieres que te recuerde y cuándo?"}
        else:
            try:
                from recordatorios import añadir
                rid = añadir(cuando, mensaje)
                fecha_fmt = cuando.strftime("%d/%m/%Y a las %H:%M")
                reply = f"Recordatorio [{rid}] guardado: '{mensaje}' — {fecha_fmt}."
            except Exception as e:
                reply = f"Error guardando recordatorio: {e}"

    elif action == "crear_archivo":
        filename = params.get("filename", "nova_output.txt")
        contenido = params.get("contenido", "")
        mostrar = params.get("mostrar", False)
        safe_name = Path(filename).name  # evita path traversal
        dest = BASE_DIR / safe_name
        ext = dest.suffix.lstrip(".").lower()
        mlog("MOTOR", f"Creando archivo: {dest} (tipo: {ext})")
        try:
            if ext == "docx":
                _crear_docx(dest, contenido)
            elif ext == "xlsx":
                _crear_xlsx(dest, contenido)
            elif ext == "pptx":
                _crear_pptx(dest, contenido)
            elif ext == "pdf":
                _crear_pdf(dest, contenido)
            else:
                dest.write_text(contenido, encoding="utf-8")
            reply = f"Archivo `{safe_name}` creado ({len(contenido)} caracteres)."
            if mostrar:
                try:
                    os.startfile(str(dest))
                    reply += f" Abriéndolo con la app por defecto de `.{ext}`."
                except Exception as e:
                    reply += f" No pude abrirlo en pantalla: {e}"
        except Exception as e:
            reply = f"No pude crear el archivo `{safe_name}`: {e}"

    elif action == "pc_command":
        pc_type = params.get("type", params.get("cmd", ""))
        mlog("PC", f"Ejecutando comando PC: {pc_type}")
        try:
            from config import PC_TAILSCALE_IP, ALMACEN_TOKEN
            import requests as _req
            base = f"http://{PC_TAILSCALE_IP}:5000"
            hdrs = {"X-Nova-Token": ALMACEN_TOKEN}

            if pc_type == "screenshot":
                r = _req.post(f"{base}/pc/screenshot", headers=hdrs, timeout=12)
                reply = "__SCREENSHOT__" if r.status_code == 200 else f"Error captura: HTTP {r.status_code}"

            elif pc_type == "lock":
                r = _req.post(f"{base}/pc/exec", json={"cmd": "lock"}, headers=hdrs, timeout=10)
                reply = r.json().get("resultado", "Pantalla bloqueada.") if r.status_code == 200 else f"Error HTTP {r.status_code}"

            elif pc_type == "desktop":
                r = _req.post(f"{base}/pc/desktop", headers=hdrs, timeout=10)
                reply = r.json().get("resultado", "Escritorio mostrado.") if r.status_code == 200 else f"Error HTTP {r.status_code}"

            elif pc_type == "volume":
                vol_action = params.get("action", "up")
                payload = {"action": vol_action}
                if vol_action == "set":
                    payload["level"] = params.get("level", 50)
                r = _req.post(f"{base}/pc/volume", json=payload, headers=hdrs, timeout=10)
                reply = r.json().get("resultado", "Volumen ajustado.") if r.status_code == 200 else f"Error HTTP {r.status_code}"

            elif pc_type == "open_url":
                url = params.get("url", "")
                display = params.get("display", url)
                r = _req.post(f"{base}/pc/url", json={"url": url}, headers=hdrs, timeout=10)
                reply = f"Abriendo {display}." if r.status_code == 200 else f"No pude abrir {display}."

            elif pc_type == "open":
                app_name = params.get("app", "")
                display = params.get("display", app_name)
                r = _req.post(f"{base}/pc/open", json={"app": app_name}, headers=hdrs, timeout=10)
                reply = f"Abriendo {display}." if r.status_code == 200 else f"No pude abrir {display}."

            elif pc_type == "close":
                app_name = params.get("app", "")
                display = params.get("display", app_name)
                r = _req.post(f"{base}/pc/close", json={"app": app_name}, headers=hdrs, timeout=10)
                reply = f"{display.capitalize()} cerrado." if r.status_code == 200 else f"No pude cerrar {display}."

            else:
                # Compatibilidad con cmd keys legacy
                cmd_key = params.get("cmd", pc_type)
                r = _req.post(f"{base}/pc/exec", json={"cmd": cmd_key}, headers=hdrs, timeout=10)
                reply = r.json().get("resultado", f"{cmd_key} ejecutado.") if r.status_code == 200 else f"Error HTTP {r.status_code}"

        except Exception as e:
            reply = f"No pude conectar con el PC: {e}"

    elif action == "buscar_internet":
        query = params.get("query", original_message)
        mlog("RED", f"Búsqueda explícita: {query[:60]}")
        try:
            from internet import obtener_info_internet
            resultado = obtener_info_internet(query)
            reply = resultado if resultado else "No encontré información relevante sobre eso."
        except Exception as e:
            reply = f"Error accediendo a internet: {e}"

    elif action == "bot_status":
        mlog("MOTOR", "Verificando estado del bot de Telegram en Oracle...")
        code, output = _run_oracle_ssh(
            "pgrep -fl telegram_bot.py | head -5; echo '---'; "
            "systemctl is-active nova-telegram 2>/dev/null || echo 'no-systemd'",
            timeout=15,
        )
        if code == 0:
            lines = [l.strip() for l in output.splitlines() if l.strip() and l.strip() != "---"]
            proc_lines = [l for l in lines if l not in ("active", "inactive", "no-systemd", "failed")]
            svc_line = next((l for l in lines if l in ("active", "inactive", "failed")), None)
            if proc_lines:
                pid = proc_lines[0].split()[0]
                reply = f"El bot está corriendo. PID {pid}."
                if svc_line:
                    reply += f" Servicio systemd: {svc_line}."
            elif svc_line == "active":
                reply = "El servicio nova-telegram está activo aunque no veo el proceso directo."
            else:
                reply = "No veo el proceso del bot en Oracle. Puede que esté caído."
        else:
            reply = "No pude conectar con Oracle para verificar el bot."

    elif action == "python_errors":
        mlog("MOTOR", "Buscando errores de Python en logs de Oracle...")
        cmd = (
            "( journalctl -u nova-telegram -n 80 --no-pager 2>/dev/null "
            "|| tail -n 80 /tmp/telegram_bot.log 2>/dev/null ) "
            "| grep -E '(Traceback|Error|Exception|CRITICAL|WARNING)' | tail -20"
        )
        code, output = _run_oracle_ssh(cmd, timeout=20)
        if code == 0 and output.strip():
            reply = f"Errores recientes en Oracle:\n```text\n{_tail_text(output, max_lines=20, max_chars=2000)}\n```"
        elif code == 0:
            reply = "No veo errores de Python recientes en los logs de Oracle."
        else:
            reply = f"No pude acceder a los logs:\n```text\n{_tail_text(output)}\n```"

    elif action == "actualizar_oracle":
        mlog("MOTOR", "Actualizando paquetes pip en Oracle...")
        pkgs = "groq requests apscheduler psutil python-telegram-bot ollama"
        code, output = _run_oracle_ssh(
            f"pip install --upgrade {pkgs} 2>&1 | tail -15",
            timeout=180,
        )
        if code == 0:
            reply = f"Paquetes actualizados en Oracle.\n```text\n{_tail_text(output, max_lines=15)}\n```"
        else:
            reply = f"Error actualizando paquetes:\n```text\n{_tail_text(output)}\n```"

    else:
        mlog("ERROR", f"Directiva desconocida recibida: '{action}'")
        reply = f"Acción desconocida: `{action}`"

    _audit("executed", original_message, {"action": action, "params": params, "reply": reply[:500]})
    return {"handled": True, "reply": reply}
