"""
NOVA — Diagnóstico distribuido real + autoreparación.

Verifica: código local (AST), nodo local Ollama, nodo Oracle (SSH+HTTP),
Telegram bot (API oficial), OpenClaw (HTTP), Open Interpreter (which/import).
También verifica sintaxis de los .py en Oracle y puede repararlos remotamente.

REGLA: Toda DETECCIÓN es determinista — sin LLM, sin alucinaciones.
       El LLM solo se usa para PROPONER reparaciones de errores confirmados.
"""

import ast
import base64
import concurrent.futures
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import requests
from groq import Groq

from config import (
    OLLAMA_HOST_LOCAL, OLLAMA_HOST_ORACLE,
    TELEGRAM_BOT_TOKEN,
    GROQ_API_KEY, GROQ_MODEL,
    ALMACEN_TOKEN,
)

NOVA_DIR     = Path(__file__).resolve().parents[1]
SSH_KEY      = NOVA_DIR / "ssh-key-2026-04-18.key"
SSH_HOST     = "ubuntu@92.5.116.97"
ORACLE_NOVA  = "/home/ubuntu/nova"
SERVICIOS_ORACLE = ["nova-almacen", "nova-telegram"]

_EXCLUIR_SINTAXIS = {"setup.py", "conf.py"}

_groq = Groq(api_key=GROQ_API_KEY)


# ── SSH / SCP helpers ─────────────────────────────────────────────────────────

def _ssh(cmd: str, timeout: int = 20) -> tuple[int, str]:
    if not SSH_KEY.exists():
        return 1, f"SSH key no encontrada en {SSH_KEY}"
    proc = subprocess.run(
        ["ssh", "-i", str(SSH_KEY),
         "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=8",
         SSH_HOST, cmd],
        capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _scp_a_oracle(local_path: str, remote_path: str, timeout: int = 30) -> tuple[int, str]:
    if not SSH_KEY.exists():
        return 1, f"SSH key no encontrada en {SSH_KEY}"
    proc = subprocess.run(
        ["scp", "-i", str(SSH_KEY),
         "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=8",
         local_path, f"{SSH_HOST}:{remote_path}"],
        capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _reiniciar_oracle() -> tuple[bool, str]:
    """Reinicia los servicios de Oracle via SSH."""
    restart_cmd = " && ".join(f"sudo systemctl restart {s}" for s in SERVICIOS_ORACLE)
    code, out = _ssh(restart_cmd, timeout=30)
    return code == 0, out


# ── Checks individuales ───────────────────────────────────────────────────────

def _check_sintaxis() -> dict:
    """AST parse de todos los .py en NOVA_DIR. 100% determinista."""
    errores: dict[str, str] = {}
    ok: list[str] = []
    for py in sorted(NOVA_DIR.glob("*.py")):
        if py.name in _EXCLUIR_SINTAXIS:
            continue
        try:
            ast.parse(py.read_text(encoding="utf-8", errors="replace"))
            ok.append(py.name)
        except SyntaxError as e:
            errores[py.name] = f"línea {e.lineno}: {e.msg}"
        except Exception as e:
            errores[py.name] = str(e)
    return {"ok": ok, "errores": errores}


def _check_sintaxis_oracle() -> dict:
    """
    AST parse de los .py en Oracle via SSH.
    Ejecuta python3 en Oracle codificado en base64 para evitar escaping de shell.
    100% determinista — sin LLM.
    """
    script = (
        "import ast, pathlib, json\n"
        "errors = {}\n"
        "ok = []\n"
        "excluir = {'setup.py', 'conf.py'}\n"
        f"for p in sorted(pathlib.Path('{ORACLE_NOVA}').glob('*.py')):\n"
        "    if p.name in excluir:\n"
        "        continue\n"
        "    try:\n"
        "        ast.parse(p.read_text(encoding='utf-8', errors='replace'))\n"
        "        ok.append(p.name)\n"
        "    except SyntaxError as e:\n"
        "        errors[p.name] = f'linea {e.lineno}: {e.msg}'\n"
        "    except Exception as e:\n"
        "        errors[p.name] = str(e)\n"
        "print(json.dumps({'ok': ok, 'errores': errors}))\n"
    )
    b64 = base64.b64encode(script.encode()).decode()
    code, out = _ssh(
        f"python3 -c \"import base64; exec(base64.b64decode('{b64}').decode())\"",
        timeout=25,
    )
    if code != 0:
        return {"ok": [], "errores": {}, "error_ssh": out[:300]}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except Exception:
                pass
    return {"ok": [], "errores": {}, "error_parse": out[:200]}


def _check_nodo_local() -> dict:
    """Verifica Ollama local y si nova.py está en ejecución."""
    import psutil
    result: dict = {"ollama_online": False, "nova_proceso": False}
    try:
        t0 = time.time()
        r = requests.get(f"{OLLAMA_HOST_LOCAL}/api/tags", timeout=3)
        result["ollama_online"] = r.status_code == 200
        result["latency_ms"] = round((time.time() - t0) * 1000)
        if result["ollama_online"]:
            result["modelos"] = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        result["error"] = str(e)
    try:
        for proc in psutil.process_iter(["cmdline"]):
            cmd = proc.info.get("cmdline") or []
            if any("nova.py" in c for c in cmd):
                result["nova_proceso"] = True
                break
    except Exception:
        pass
    return result


def _check_nodo_oracle() -> dict:
    """Verifica Oracle: Ollama HTTP + modelos + disco + procesos via SSH."""
    result: dict = {"online": False}

    # Ollama HTTP (Tailscale)
    try:
        t0 = time.time()
        r = requests.get(f"{OLLAMA_HOST_ORACLE}/api/tags", timeout=6)
        result["online"] = r.status_code == 200
        result["latency_ms"] = round((time.time() - t0) * 1000)
        if result["online"]:
            modelos = [m["name"] for m in r.json().get("models", [])]
            result["modelos_ollama"] = modelos
            result["deepseek"] = any("deepseek" in m for m in modelos)
            result["hermes"]   = any("hermes"   in m for m in modelos)
    except Exception as e:
        result["error_ollama"] = str(e)

    # Disco y procesos via SSH
    code, out = _ssh(
        "df -h / | awk 'NR==2{print $4\" libres de \"$2\" (\"$5\" usado)\"}' ; "
        "ps aux | grep -E 'telegram_bot|watchdog|nova' | grep -v grep | awk '{print $11}' | sort -u",
        timeout=15,
    )
    if code == 0:
        lines = [l for l in out.splitlines() if l.strip()]
        if lines:
            result["disco"]    = lines[0]
            result["procesos"] = lines[1:]

    return result


def _check_telegram() -> dict:
    """Verifica el bot de Telegram con la API oficial de Telegram. Sin LLM."""
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getMe",
            timeout=6,
        )
        data = r.json()
        if data.get("ok"):
            bot = data["result"]
            return {"online": True, "username": bot.get("username"), "id": bot.get("id")}
        return {"online": False, "error": data.get("description", "respuesta inválida")}
    except Exception as e:
        return {"online": False, "error": str(e)}


def _check_openclaw() -> dict:
    """Verifica el gateway de OpenClaw (WSL, puerto 18789)."""
    for url in ("http://localhost:18789/", "http://127.0.0.1:18789/"):
        try:
            r = requests.get(url, timeout=3)
            return {"online": True, "status_code": r.status_code, "url": url}
        except requests.ConnectionError:
            continue
        except Exception as e:
            return {"online": False, "error": str(e)}
    return {"online": False, "error": "puerto 18789 no responde"}


def _check_open_interpreter() -> dict:
    """Verifica si Open Interpreter está instalado."""
    path = shutil.which("interpreter")
    if path:
        return {"instalado": True, "via": "which", "path": path}
    spec = importlib.util.find_spec("interpreter")
    if spec:
        return {"instalado": True, "via": "import", "path": str(spec.origin or "?")}
    return {"instalado": False}


# ── Diagnóstico completo ──────────────────────────────────────────────────────

def diagnosticar_todo() -> dict:
    """
    Lanza todos los checks en paralelo y devuelve un informe estructurado.
    Incluye sintaxis de Oracle. Completamente determinista — el LLM no interviene.
    """
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        fut_sintaxis        = ex.submit(_check_sintaxis)
        fut_sintaxis_oracle = ex.submit(_check_sintaxis_oracle)
        fut_local           = ex.submit(_check_nodo_local)
        fut_oracle          = ex.submit(_check_nodo_oracle)
        fut_telegram        = ex.submit(_check_telegram)
        fut_openclaw        = ex.submit(_check_openclaw)
        fut_interpreter     = ex.submit(_check_open_interpreter)

        reporte = {
            "ts":               datetime.now().isoformat(timespec="seconds"),
            "duracion_s":       round(time.time() - t0, 1),
            "sintaxis":         fut_sintaxis.result(),
            "sintaxis_oracle":  fut_sintaxis_oracle.result(),
            "nodo_local":       fut_local.result(),
            "nodo_oracle":      fut_oracle.result(),
            "telegram_bot":     fut_telegram.result(),
            "openclaw":         fut_openclaw.result(),
            "open_interpreter": fut_interpreter.result(),
        }

    # Guardar último informe
    try:
        (NOVA_DIR / "diagnostico_ultimo.json").write_text(
            json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

    return reporte


def resumen_voz(reporte: dict) -> str:
    """Convierte el informe en frases concisas para TTS."""
    partes = []

    # Sintaxis local
    errores_sint = reporte["sintaxis"].get("errores", {})
    if errores_sint:
        archivos = ", ".join(errores_sint.keys())
        partes.append(f"encontré errores de sintaxis locales en {archivos}")
    else:
        n = len(reporte["sintaxis"].get("ok", []))
        partes.append(f"{n} archivos locales sin errores de sintaxis")

    # Sintaxis Oracle
    sint_oracle = reporte.get("sintaxis_oracle", {})
    if "error_ssh" in sint_oracle:
        partes.append("no pude verificar sintaxis de Oracle por SSH")
    elif sint_oracle.get("errores"):
        archivos_o = ", ".join(sint_oracle["errores"].keys())
        partes.append(f"errores de sintaxis en Oracle en {archivos_o}")
    else:
        n_o = len(sint_oracle.get("ok", []))
        if n_o:
            partes.append(f"{n_o} archivos de Oracle sin errores")

    # Oracle
    oracle = reporte["nodo_oracle"]
    if oracle.get("online"):
        lat  = oracle.get("latency_ms", "?")
        mods = oracle.get("modelos_ollama", [])
        extras = []
        if oracle.get("deepseek"): extras.append("DeepSeek")
        if oracle.get("hermes"):   extras.append("Hermes")
        mod_str = f" con {', '.join(extras)}" if extras else f" con {len(mods)} modelos"
        disco = oracle.get("disco", "")
        disco_str = f", disco {disco}" if disco else ""
        partes.append(f"Oracle online en {lat}ms{mod_str}{disco_str}")
    else:
        err = oracle.get("error_ollama", "sin respuesta")
        partes.append(f"Oracle no responde: {err}")

    # Telegram
    tg = reporte["telegram_bot"]
    if tg.get("online"):
        partes.append(f"bot de Telegram activo como @{tg.get('username', '?')}")
    else:
        partes.append(f"bot de Telegram caído: {tg.get('error', '?')}")

    # OpenClaw
    oc = reporte["openclaw"]
    partes.append("OpenClaw online" if oc.get("online") else "OpenClaw no responde en el puerto 18789")

    # Open Interpreter
    oi = reporte["open_interpreter"]
    partes.append(
        "Open Interpreter disponible" if oi.get("instalado")
        else "Open Interpreter no instalado"
    )

    return ". ".join(partes) + "."


# ── Autoreparación local ──────────────────────────────────────────────────────

def _proponer_fix_groq(archivo: str, error: str, codigo: str) -> str | None:
    """Pide a Groq que corrija el error. Devuelve el código corregido o None."""
    prompt = (
        f"Eres un experto en Python. El archivo `{archivo}` tiene este error de sintaxis:\n\n"
        f"  {error}\n\n"
        f"Código completo del archivo:\n\n```python\n{codigo[:8000]}\n```\n\n"
        "Devuelve ÚNICAMENTE el archivo Python completo y corregido. "
        "Sin explicaciones, sin markdown, sin bloques de código. Solo el Python puro."
    )
    try:
        resp = _groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.1,
        )
        codigo_nuevo = resp.choices[0].message.content.strip()
        # Quitar bloques markdown si el LLM los añadió
        if codigo_nuevo.startswith("```"):
            lineas = codigo_nuevo.splitlines()
            fin = len(lineas) - 1 if lineas[-1].strip() == "```" else len(lineas)
            codigo_nuevo = "\n".join(lineas[1:fin])
        return codigo_nuevo
    except Exception as e:
        return None


def reparar_archivo(archivo: str, error: str) -> dict:
    """
    Repara un error de sintaxis en un archivo local.
    Flujo: lee código real → LLM propone fix → verifica AST → backup → aplica.
    """
    ruta = NOVA_DIR / archivo
    if not ruta.exists():
        return {"ok": False, "motivo": f"{archivo} no encontrado en {NOVA_DIR}"}

    codigo_original = ruta.read_text(encoding="utf-8", errors="replace")
    codigo_nuevo = _proponer_fix_groq(archivo, error, codigo_original)

    if codigo_nuevo is None:
        return {"ok": False, "motivo": "Groq no devolvió respuesta"}

    try:
        ast.parse(codigo_nuevo)
    except SyntaxError as e:
        return {
            "ok": False,
            "motivo": f"El LLM devolvió código con error de sintaxis en línea {e.lineno}: {e.msg}. No se aplicó.",
        }

    backup = ruta.with_suffix(".py.bak")
    backup.write_text(codigo_original, encoding="utf-8")
    ruta.write_text(codigo_nuevo, encoding="utf-8")
    return {"ok": True, "archivo": archivo, "nodo": "local", "backup": backup.name}


# ── Autoreparación Oracle ─────────────────────────────────────────────────────

def reparar_en_oracle(archivo: str, error: str) -> dict:
    """
    Repara un error de sintaxis en un archivo de Oracle.
    Flujo: cat via SSH → LLM propone fix (local) → verifica AST → SCP → reiniciar.
    """
    code, content = _ssh(f"cat {ORACLE_NOVA}/{archivo}", timeout=15)
    if code != 0 or not content.strip():
        return {"ok": False, "motivo": f"No pude leer {archivo} de Oracle: {content[:200]}"}

    codigo_nuevo = _proponer_fix_groq(archivo, error, content)
    if codigo_nuevo is None:
        return {"ok": False, "motivo": "Groq no devolvió respuesta"}

    try:
        ast.parse(codigo_nuevo)
    except SyntaxError as e:
        return {
            "ok": False,
            "motivo": f"El LLM devolvió código con error en línea {e.lineno}: {e.msg}. No se aplicó.",
        }

    # Escribir a temp local y SCP a Oracle
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tf:
        tf.write(codigo_nuevo)
        tmp_path = tf.name

    try:
        scp_code, scp_out = _scp_a_oracle(tmp_path, f"{ORACLE_NOVA}/{archivo}")
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    if scp_code != 0:
        return {"ok": False, "motivo": f"SCP falló: {scp_out[:200]}"}

    return {"ok": True, "archivo": archivo, "nodo": "oracle"}


# ── Reparación combinada + propagación ────────────────────────────────────────

def reparar_errores_sintaxis(reporte: dict, propagar: bool = True) -> list[dict]:
    """
    Repara todos los errores de sintaxis del informe: locales y de Oracle.
    Si propagar=True y hay reparaciones locales, hace deploy automático a Oracle.
    Si hay reparaciones en Oracle, reinicia sus servicios.
    """
    errores_local  = reporte.get("sintaxis",        {}).get("errores", {})
    errores_oracle = reporte.get("sintaxis_oracle",  {}).get("errores", {})

    resultados: list[dict] = []
    hubo_local  = False
    hubo_oracle = False

    # Reparar archivos locales
    for archivo, error in errores_local.items():
        r = reparar_archivo(archivo, error)
        r["archivo"] = archivo
        resultados.append(r)
        if r.get("ok"):
            hubo_local = True

    # Reparar archivos en Oracle
    for archivo, error in errores_oracle.items():
        r = reparar_en_oracle(archivo, error)
        r["archivo"] = archivo
        resultados.append(r)
        if r.get("ok"):
            hubo_oracle = True

    # Si hubo reparaciones locales → deploy completo a Oracle
    if propagar and hubo_local:
        try:
            from deploy import ejecutar_deploy
            deploy_out = ejecutar_deploy()
            resultados.append({"ok": True, "accion": "deploy", "resultado": deploy_out})
        except Exception as e:
            resultados.append({"ok": False, "accion": "deploy", "motivo": str(e)})

    # Si se repararon archivos de Oracle directamente → reiniciar servicios
    elif hubo_oracle:
        ok_restart, msg = _reiniciar_oracle()
        resultados.append({
            "ok": ok_restart,
            "accion": "reinicio_oracle",
            "resultado": msg[:200] if not ok_restart else "servicios reiniciados",
        })

    # Invalidar caché de autoconocimiento en Oracle
    if hubo_local or hubo_oracle:
        _ssh("rm -f /home/ubuntu/nova/self_knowledge.json /home/ubuntu/nova/self_summary.json")

    return resultados
