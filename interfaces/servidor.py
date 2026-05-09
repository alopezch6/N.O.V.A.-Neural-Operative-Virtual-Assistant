import io
import os
import json
import time
import wave
import threading
import requests
import psutil
import numpy as np
from flask import Flask, jsonify, send_from_directory, request, send_file
from flask_cors import CORS
from flask_sock import Sock
from mono import get_buffer as mono_get_buffer

app = Flask(__name__)
CORS(app)
sock = Sock(app)

estado_actual = {
    "estado":   "idle",
    "local":    False,
    "oracle":   False,
    "memorias": 0,
    "historial": 0,
}

_NOVA_DIR       = os.path.dirname(os.path.abspath(__file__))
_MEMORIA_PATH   = os.path.join(_NOVA_DIR, "memoria.json")
_HISTORIAL_PATH = os.path.join(_NOVA_DIR, "historial.json")

# ── Telemetría PC local (actualizada cada 5s en background) ──────────────────
_pc_telem = {"cpu": None, "ram": None, "temp": None,
             "gpu": None, "gpu_temp": None, "vram_used": None, "vram_total": None,
             "net_up": None, "net_down": None}
_pc_lock  = threading.Lock()
_net_prev = {"bytes_sent": 0, "bytes_recv": 0, "ts": 0.0}

def _update_pc_telem():
    import time as _time
    cpu  = round(psutil.cpu_percent(interval=1))
    ram  = round(psutil.virtual_memory().percent)
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for vals in temps.values():
                if vals:
                    temp = round(vals[0].current, 1)
                    break
    except Exception:
        pass

    # GPU via pynvml
    gpu = gpu_temp = vram_used = vram_total = None
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        util  = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem   = pynvml.nvmlDeviceGetMemoryInfo(h)
        gtmp  = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        gpu        = util.gpu
        gpu_temp   = gtmp
        vram_used  = round(mem.used / 1024**3, 1)
        vram_total = round(mem.total / 1024**3, 1)
    except Exception:
        pass

    # Red MB/s
    net_up = net_down = None
    try:
        now = _time.time()
        counters = psutil.net_io_counters()
        prev = _net_prev
        dt = now - prev["ts"]
        if dt > 0 and prev["ts"] > 0:
            net_up   = round((counters.bytes_sent - prev["bytes_sent"]) / dt / 1024**2, 2)
            net_down = round((counters.bytes_recv - prev["bytes_recv"]) / dt / 1024**2, 2)
        _net_prev.update({"bytes_sent": counters.bytes_sent,
                          "bytes_recv": counters.bytes_recv, "ts": now})
    except Exception:
        pass

    with _pc_lock:
        _pc_telem.update({"cpu": cpu, "ram": ram, "temp": temp,
                          "gpu": gpu, "gpu_temp": gpu_temp,
                          "vram_used": vram_used, "vram_total": vram_total,
                          "net_up": net_up, "net_down": net_down})
    threading.Timer(5, _update_pc_telem).start()

# ── Telemetría Oracle (fetch cada 10s en background) ─────────────────────────
_oracle_telem = {"cpu": None, "ram": None, "temp": None, "latency_ms": None}
_oracle_lock  = threading.Lock()

def _update_oracle_telem():
    import time as _time
    try:
        t0 = _time.time()
        r  = requests.get("http://100.111.223.84:9100/telemetria", timeout=4)
        latency = round(((_time.time() - t0) * 1000))
        data = r.json()
        data["latency_ms"] = latency
        with _oracle_lock:
            _oracle_telem.update(data)
    except Exception:
        with _oracle_lock:
            _oracle_telem["latency_ms"] = None
    threading.Timer(10, _update_oracle_telem).start()

# ── Estado ────────────────────────────────────────────────────────────────────
def actualizar_estado(nuevo_estado, **kwargs):
    estado_actual["estado"] = nuevo_estado
    for k, v in kwargs.items():
        estado_actual[k] = v
    try:
        if os.path.exists(_MEMORIA_PATH):
            with open(_MEMORIA_PATH, "r", encoding="utf-8") as f:
                mem = json.load(f)
            estado_actual["memorias"] = len(mem) if isinstance(mem, list) else len(mem.get("memorias", []))
    except Exception:
        pass
    try:
        if os.path.exists(_HISTORIAL_PATH):
            with open(_HISTORIAL_PATH, "r", encoding="utf-8") as f:
                hist = json.load(f)
            estado_actual["historial"] = len(hist) if isinstance(hist, list) else 0
    except Exception:
        pass

@app.route('/estado')
def get_estado():
    data = dict(estado_actual)
    with _pc_lock:
        data['pc'] = dict(_pc_telem)
    with _oracle_lock:
        data['oracle_telem'] = dict(_oracle_telem)
    data['monolog'] = mono_get_buffer()
    return jsonify(data)

# ── TTS endpoint (Kokoro) ─────────────────────────────────────────────────────
_kokoro_pipeline = None
_kokoro_lock     = threading.Lock()

def _get_kokoro():
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        with _kokoro_lock:
            if _kokoro_pipeline is None:
                import torch
                from kokoro import KPipeline
                os.environ.setdefault("KOKORO_DEVICE", "cpu")
                _kokoro_pipeline = KPipeline(
                    lang_code="e", repo_id="hexgrad/Kokoro-82M",
                    device=torch.device("cpu")
                )
    return _kokoro_pipeline

@app.route('/tts', methods=['POST'])
def tts_endpoint():
    texto = (request.json or {}).get('texto', '').strip()
    if not texto:
        return jsonify({"error": "texto vacío"}), 400
    try:
        pipeline = _get_kokoro()
        chunks = [audio for _, _, audio in pipeline(texto, voice="ef_dora", speed=0.88)]
        if not chunks:
            return jsonify({"error": "sin audio generado"}), 500
        audio_np    = np.concatenate(chunks)
        audio_int16 = (audio_np * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(audio_int16.tobytes())
        buf.seek(0)
        return send_file(buf, mimetype='audio/wav')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def hud():
    return send_from_directory(_NOVA_DIR, 'hud.html')

@app.route('/v2')
def hud_v2():
    return send_from_directory(_NOVA_DIR, 'hud-v2.html')

# ── Explorador NOVA (solo lectura, restringido a B:\NOVA) ────────────────────
_NOVA_ROOT = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
_MAX_FILE_BYTES = 80_000  # 80 KB por archivo


def _nova_path(rel: str) -> str | None:
    """Resuelve y valida que el path esté dentro de _NOVA_ROOT."""
    target = os.path.realpath(os.path.join(_NOVA_ROOT, rel)) if rel else _NOVA_ROOT
    if not target.startswith(_NOVA_ROOT):
        return None
    return target


@app.route('/nova/files')
def nova_files():
    rel = request.args.get('path', '')
    target = _nova_path(rel)
    if target is None:
        return jsonify({"error": "acceso denegado"}), 403
    if not os.path.isdir(target):
        return jsonify({"error": "no es un directorio"}), 404
    try:
        entries = []
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            entries.append({
                "name": name,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else None,
            })
        return jsonify({"path": target, "entries": entries})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/nova/read')
def nova_read():
    rel = request.args.get('path', '')
    if not rel:
        return jsonify({"error": "path requerido"}), 400
    target = _nova_path(rel)
    if target is None:
        return jsonify({"error": "acceso denegado"}), 403
    if not os.path.isfile(target):
        return jsonify({"error": "archivo no encontrado"}), 404
    if os.path.getsize(target) > _MAX_FILE_BYTES:
        return jsonify({"error": "archivo demasiado grande"}), 413
    try:
        with open(target, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        return jsonify({"path": target, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/deploy', methods=['POST'])
def deploy_endpoint():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        from deploy import ejecutar_deploy
        resultado = ejecutar_deploy()
        return jsonify({'resultado': resultado})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/nova/write', methods=['POST'])
def nova_write():
    """Permite escribir un archivo dentro de B:\\NOVA (requiere token). Usado por autoreparación."""
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.json or {}
    rel  = data.get('path', '')
    content = data.get('content', '')
    if not rel or not content:
        return jsonify({'error': 'path y content requeridos'}), 400
    target = _nova_path(rel)
    if target is None:
        return jsonify({'error': 'acceso denegado'}), 403
    # Solo .py y .json editables
    if not (target.endswith('.py') or target.endswith('.json')):
        return jsonify({'error': 'solo se permiten .py y .json'}), 400
    try:
        with open(target, 'w', encoding='utf-8') as f:
            f.write(content)
        return jsonify({'ok': True, 'path': target})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Control PC remoto (llamado desde Oracle via Tailscale) ───────────────────
_PC_COMMANDS: dict[str, list[str]] = {
    "spotify": ["cmd", "/c", "start", "spotify:"],
    "discord": ["cmd", "/c", "start", "discord:"],
    "chrome":  ["cmd", "/c", "start", "chrome"],
    "opera":   ["cmd", "/c", "start", "opera"],
    "notepad": ["notepad.exe"],
    "lock":    ["rundll32.exe", "user32.dll,LockWorkStation"],
}

# Mapa proceso → nombre exe para taskkill
_CLOSE_MAP: dict[str, str] = {
    "discord": "discord.exe",
    "spotify": "spotify.exe",
    "chrome": "chrome.exe",
    "opera": "opera.exe",
    "firefox": "firefox.exe",
    "vlc": "vlc.exe",
    "obs64": "obs64.exe",
    "obs": "obs64.exe",
    "steam": "steam.exe",
    "telegram": "telegram.exe",
    "notepad": "notepad.exe",
    "notepad++": "notepad++.exe",
    "winword": "winword.exe",
    "excel": "excel.exe",
    "powerpnt": "powerpnt.exe",
    "code": "code.exe",
    "calc": "calc.exe",
    "mspaint": "mspaint.exe",
    "taskmgr": "taskmgr.exe",
    "explorer": "explorer.exe",
}


@app.route('/pc/exec', methods=['POST'])
def pc_exec():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    cmd_key = (request.json or {}).get('cmd', '').strip().lower()
    if cmd_key not in _PC_COMMANDS:
        return jsonify({'error': f"Comando '{cmd_key}' no permitido. Disponibles: {', '.join(_PC_COMMANDS)}"}), 400
    try:
        subprocess.Popen(_PC_COMMANDS[cmd_key], shell=False)
        return jsonify({'ok': True, 'resultado': f"{cmd_key} lanzado en el PC."})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/pc/screenshot', methods=['POST'])
def pc_screenshot():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        import mss
        import mss.tools
        ruta = os.path.join(_NOVA_DIR, "capturas", "screenshot_nova.png")
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[0])
            mss.tools.to_png(img.rgb, img.size, output=ruta)
        return send_file(ruta, mimetype='image/png')
    except ImportError:
        # fallback: PIL
        try:
            from PIL import ImageGrab
            ruta = os.path.join(_NOVA_DIR, "capturas", "screenshot_nova.png")
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            ImageGrab.grab().save(ruta)
            return send_file(ruta, mimetype='image/png')
        except Exception as e:
            return jsonify({'error': f'Sin librería de captura disponible: {e}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/pc/open', methods=['POST'])
def pc_open():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    app_name = (request.json or {}).get('app', '').strip()
    if not app_name:
        return jsonify({'error': 'app requerido'}), 400
    try:
        from apps import open_app
        ok, result = open_app(app_name)
        if ok:
            return jsonify({'ok': True, 'resultado': f"{result} abierto."})
        return jsonify({'ok': False, 'resultado': result}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/pc/url', methods=['POST'])
def pc_url():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    url = (request.json or {}).get('url', '').strip()
    if not url or not url.startswith('http'):
        return jsonify({'error': 'url inválida'}), 400
    try:
        import webbrowser
        webbrowser.open(url)
        return jsonify({'ok': True, 'resultado': f"Abriendo {url} en el navegador."})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/pc/close', methods=['POST'])
def pc_close():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    app_name = (request.json or {}).get('app', '').strip().lower()
    process = _CLOSE_MAP.get(app_name, f"{app_name}.exe")
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", process],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return jsonify({'ok': True, 'resultado': f"{app_name} cerrado."})
        return jsonify({'ok': False, 'resultado': f"No encontré proceso de {app_name} en ejecución."})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/pc/volume', methods=['POST'])
def pc_volume():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.json or {}
    vol_action = data.get('action', 'up')
    level = data.get('level')
    try:
        if vol_action == 'up':
            ps = "$wsh=New-Object -ComObject WScript.Shell; 1..5|%{$wsh.SendKeys([char]175)}"
            msg = "Volumen subido."
        elif vol_action == 'down':
            ps = "$wsh=New-Object -ComObject WScript.Shell; 1..5|%{$wsh.SendKeys([char]174)}"
            msg = "Volumen bajado."
        elif vol_action == 'mute':
            ps = "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"
            msg = "Silenciado."
        elif vol_action == 'set' and level is not None:
            lvl = max(0, min(100, int(level)))
            try:
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = cast(interface, POINTER(IAudioEndpointVolume))
                vol.SetMasterVolumeLevelScalar(lvl / 100.0, None)
                return jsonify({'ok': True, 'resultado': f"Volumen al {lvl}%."})
            except ImportError:
                # Fallback: aproximar con teclas (cada keypress ≈ 2%)
                presses = max(1, round(abs(lvl - 50) / 2))
                key = 175 if lvl > 50 else 174
                ps = f"$wsh=New-Object -ComObject WScript.Shell; 1..{presses}|%{{$wsh.SendKeys([char]{key})}}"
                msg = f"Volumen ajustado hacia {'máximo' if lvl > 50 else 'mínimo'} ({presses} pasos)."
        else:
            return jsonify({'error': 'acción inválida'}), 400

        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-c", ps],
            shell=False,
        )
        return jsonify({'ok': True, 'resultado': msg})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/pc/desktop', methods=['POST'])
def pc_desktop():
    from config import ALMACEN_TOKEN
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-c",
             "(New-Object -ComObject Shell.Application).MinimizeAll()"],
            shell=False,
        )
        return jsonify({'ok': True, 'resultado': "Escritorio mostrado, todas las ventanas minimizadas."})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/alexa/speak', methods=['POST'])
def alexa_speak_endpoint():
    from config import ALMACEN_TOKEN, USE_ALEXA_TTS
    if request.headers.get('X-Nova-Token') != ALMACEN_TOKEN:
        return jsonify({'error': 'unauthorized'}), 401
    if not USE_ALEXA_TTS:
        return jsonify({'error': 'Alexa TTS desactivado'}), 503
    texto = (request.json or {}).get('texto', '').strip()
    if not texto:
        return jsonify({'error': 'texto vacío'}), 400
    try:
        from alexa_voz import alexa_habla
        ok = alexa_habla(texto)
        return jsonify({'ok': ok})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_ws_payload():
    data = dict(estado_actual)
    with _pc_lock:
        data['pc'] = dict(_pc_telem)
    with _oracle_lock:
        ot = dict(_oracle_telem)
        data['oracle_telem'] = ot
        data['oracle'] = ot.get('latency_ms') is not None  # real status, not the stale default False
    data['monolog'] = mono_get_buffer()
    return data

@sock.route('/ws')
def ws_nova(ws):
    """WebSocket push: envía estado completo cada segundo al cliente."""
    while True:
        try:
            ws.send(json.dumps(_build_ws_payload()))
            time.sleep(1)
        except Exception:
            break

@app.route('/status')
def get_status():
    """Endpoint aplanado para Electron gaming-mode detection (d.cpu en raíz)."""
    with _pc_lock:
        cpu = _pc_telem.get('cpu')
        ram = _pc_telem.get('ram')
    with _oracle_lock:
        oracle_ok = _oracle_telem.get('latency_ms') is not None
    return jsonify({
        'cpu':    cpu,
        'ram':    ram,
        'oracle': oracle_ok,
        'state':  estado_actual.get('estado', 'idle'),
    })

@app.route('/health')
def health():
    """Endpoint para watchdog: Oracle y local pueden verificar que el PC está vivo."""
    nova_running = False
    try:
        for proc in psutil.process_iter(['cmdline']):
            cmd = proc.info.get('cmdline') or []
            if any('nova.py' in c for c in cmd):
                nova_running = True
                break
    except Exception:
        pass

    ollama_ok = False
    try:
        import requests as _req
        ollama_ok = _req.get("http://127.0.0.1:11434/api/tags", timeout=2).status_code == 200
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "nova": nova_running,
        "ollama": ollama_ok,
        "ts": time.time(),
    })


def iniciar_servidor():
    _update_pc_telem()
    _update_oracle_telem()
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
