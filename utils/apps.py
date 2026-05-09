"""
NOVA — Registro de aplicaciones
Busca apps instaladas en Windows, guarda los paths exactos y los reutiliza.
Soporta launchers con argumentos (Riot Games, Epic, etc.) via accesos directos .lnk.
"""

import ctypes
import glob
import json
import os
import re
import shutil
import subprocess
import winreg
from pathlib import Path

_BASE = Path(__file__).resolve().parents[1]
_REGISTRY_PATH = _BASE / "apps.json"

_SEARCH_ROOTS = [
    os.path.expandvars(r"%LOCALAPPDATA%"),
    os.path.expandvars(r"%APPDATA%"),
    os.path.expandvars(r"%PROGRAMFILES%"),
    os.path.expandvars(r"%PROGRAMFILES(X86)%"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps"),
    r"C:\Riot Games",
    r"C:\Games",
    r"D:\Games",
    r"D:\Juegos",
    r"D:\Programs",
    r"E:\Games",
]

_SHORTCUT_DIRS = [
    os.path.expanduser("~/Desktop"),
    os.path.expandvars(r"%PUBLIC%\Desktop"),
    os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs"),
]

_WIN_UNINSTALL_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]

_ALIASES = {
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
    "calculadora": "calc",
    "calc": "calc",
    "word": "winword",
    "microsoft word": "winword",
    "excel": "excel",
    "microsoft excel": "excel",
    "powerpoint": "powerpnt",
    "vscode": "code",
    "visual studio code": "code",
    "obs": "obs64",
    "obs studio": "obs64",
    "vlc": "vlc",
    "explorer": "explorer",
    "explorador": "explorer",
    "explorador de archivos": "explorer",
    "task manager": "taskmgr",
    "administrador de tareas": "taskmgr",
    "paint": "mspaint",
    "notepad++": "notepad++",
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

_SYSTEM_APPS = {
    "notepad", "calc", "mspaint", "explorer", "taskmgr",
    "winword", "excel", "powerpnt", "cmd", "powershell",
    "regedit", "msconfig", "devmgmt.msc", "services.msc",
}


# ── Registro persistente ───────────────────────────────────────────────────────

def _load() -> dict:
    if _REGISTRY_PATH.exists():
        try:
            return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save(registry: dict) -> None:
    _REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Accesos directos .lnk ─────────────────────────────────────────────────────

def _find_via_shortcuts(name: str) -> tuple[str, str] | None:
    """
    Busca en escritorio y Start Menu un .lnk cuyo nombre contenga 'name'.
    Devuelve (exe_path, args) o None.
    """
    name_lower = name.lower()
    candidates = []
    for d in _SHORTCUT_DIRS:
        if not os.path.isdir(d):
            continue
        for lnk in glob.glob(os.path.join(d, "**", "*.lnk"), recursive=True):
            if name_lower in os.path.basename(lnk).lower():
                candidates.append(lnk)

    for lnk in candidates:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"$s=(New-Object -COM WScript.Shell).CreateShortcut('{lnk}');"
                 "$s.TargetPath + '|' + $s.Arguments"],
                capture_output=True, text=True, timeout=5,
            )
            parts = result.stdout.strip().split("|", 1)
            target = parts[0].strip().strip('"')
            args = parts[1].strip() if len(parts) > 1 else ""
            if target and os.path.isfile(target):
                return target, args
        except Exception:
            continue

    return None


# ── Registro de Windows ────────────────────────────────────────────────────────

def _find_in_winregistry(name: str) -> str | None:
    name_lower = name.lower()

    def _is_valid_exe(path: str) -> bool:
        p = path.lower()
        return (p.endswith(".exe") and os.path.isfile(path)
                and "uninstall" not in p and "setup" not in p and "update" not in p)

    for hkey, subkey in _WIN_UNINSTALL_KEYS:
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        with winreg.OpenKey(key, winreg.EnumKey(key, i)) as app_key:
                            try:
                                display_name = winreg.QueryValueEx(app_key, "DisplayName")[0].lower()
                            except OSError:
                                continue
                            if name_lower not in display_name:
                                continue
                            try:
                                icon = winreg.QueryValueEx(app_key, "DisplayIcon")[0]
                                exe = icon.split(",")[0].strip().strip('"')
                                if _is_valid_exe(exe):
                                    return exe
                                icon_dir = os.path.dirname(exe)
                                if os.path.isdir(icon_dir):
                                    hits = [f for f in glob.glob(os.path.join(icon_dir, f"{name}.exe")) if _is_valid_exe(f)]
                                    if hits:
                                        return hits[0]
                            except OSError:
                                pass
                            try:
                                loc = winreg.QueryValueEx(app_key, "InstallLocation")[0].strip().strip('"')
                                if loc and os.path.isdir(loc):
                                    hits = [f for f in glob.glob(os.path.join(loc, "**", f"{name}.exe"), recursive=True) if _is_valid_exe(f)]
                                    if hits:
                                        return sorted(hits)[-1]
                            except OSError:
                                pass
                    except OSError:
                        continue
        except OSError:
            continue
    return None


# ── Busqueda en sistema de archivos ───────────────────────────────────────────

def _find_exe(name: str) -> str | None:
    name_lower = name.lower()

    found = shutil.which(name)
    if found:
        return found

    if name_lower in _SYSTEM_APPS:
        return name

    found = _find_in_winregistry(name_lower)
    if found:
        return found

    patterns = [
        f"{name}\\{name}.exe",
        f"{name}*\\{name}.exe",
        f"{name}*\\app-*\\{name}.exe",
        f"*{name}*\\{name}.exe",
        f"*\\{name}.exe",
    ]
    for root in _SEARCH_ROOTS:
        if not os.path.isdir(root):
            continue
        for pattern in patterns:
            try:
                matches = glob.glob(os.path.join(root, pattern), recursive=False)
                if matches:
                    return sorted(matches)[-1]
            except Exception:
                pass

    all_roots = list(dict.fromkeys(_SEARCH_ROOTS + [
        r"C:\Program Files", r"C:\Program Files (x86)",
    ]))
    for root in all_roots:
        if not os.path.isdir(root):
            continue
        try:
            matches = glob.glob(os.path.join(root, "**", f"{name}.exe"), recursive=True)
            if matches:
                return sorted(matches)[-1]
        except Exception:
            pass

    return None


# ── Lanzador ──────────────────────────────────────────────────────────────────

def _launch(exe_path: str, args: str = "") -> tuple[bool, str]:
    if not (os.path.isabs(exe_path) and os.path.isfile(exe_path)):
        try:
            subprocess.Popen(exe_path, shell=True)
            return True, ""
        except Exception as e:
            return False, str(e)

    # ShellExecuteW gestiona UAC y manifiestos correctamente
    params = args if args else None
    ret = ctypes.windll.shell32.ShellExecuteW(0, "open", exe_path, params, None, 1)
    if ret > 32:
        return True, ""

    # Fallback: subprocess con shell
    try:
        cmd = f'"{exe_path}"'
        if args:
            cmd += f" {args}"
        subprocess.Popen(cmd, shell=True)
        return True, ""
    except Exception as e:
        return False, str(e)


# ── API publica ────────────────────────────────────────────────────────────────

def normalize_app_name(texto: str) -> str | None:
    t = texto.lower().strip()
    for alias, name in _ALIASES.items():
        if alias in t:
            return name
    match = re.search(
        r"(?:abre|abrir|abrirme|lanza|ejecuta|inicia|arranca|pon)\s+"
        r"(?:el|la|los|las|un|una)?\s*"
        r"(\w[\w\s\+\#\.]*?)(?:\s*$|\.|\?|,)",
        t
    )
    if match:
        return match.group(1).strip()
    return None


def open_app(app_name: str) -> tuple[bool, str]:
    key = app_name.lower().strip()
    registry = _load()

    # 1. Path guardado con args opcionales
    if key in registry:
        entry = registry[key]
        exe = entry["path"]
        args = entry.get("args", "")
        if os.path.isfile(exe) or exe in _SYSTEM_APPS:
            ok, err = _launch(exe, args)
            if ok:
                entry["uses"] = entry.get("uses", 0) + 1
                _save(registry)
                return True, entry.get("display", app_name)
        del registry[key]
        _save(registry)

    # 2. Acceso directo .lnk (mejor fuente para apps con launchers propios)
    shortcut = _find_via_shortcuts(key)
    if shortcut:
        exe, args = shortcut
        exe = str(Path(exe))
        ok, err = _launch(exe, args)
        if ok:
            registry[key] = {"path": exe, "args": args, "display": app_name, "uses": 1}
            _save(registry)
            return True, app_name

    # 3. Busqueda por exe en el sistema
    exe = _find_exe(key)
    if not exe:
        exe = _find_exe(app_name)
    if not exe:
        return False, f"No he encontrado '{app_name}' instalado en este equipo."

    exe = str(Path(exe))
    ok, err = _launch(exe)
    if ok:
        registry[key] = {"path": exe, "args": "", "display": app_name, "uses": 1}
        _save(registry)
        return True, app_name

    return False, f"Encontre '{app_name}' pero no pude abrirlo: {err}"


def list_known_apps() -> list[str]:
    return list(_load().keys())
