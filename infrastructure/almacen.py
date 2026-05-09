"""
NOVA — Almacén centralizado
API REST que centraliza memoria.json e historiales en Oracle.
Puerto 9101. Arrancar con: python3 almacen.py
"""
from flask import Flask, jsonify, request
import json
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = Flask(__name__)

_NOVA_DIR = Path(__file__).resolve().parents[1]
_TOKEN = os.getenv("ALMACEN_TOKEN", "")
_ARCHIVOS = {
    "memoria":  _NOVA_DIR / "memoria.json",
    "voz":      _NOVA_DIR / "historial.json",
    "telegram": _NOVA_DIR / "historial_telegram.json",
}
_DEFAULTS = {
    "memoria": {
        "perfil": {
            "nombre": "Alex",
            "ciudad": "Zaragoza",
            "juegos": ["WoW", "Valorant", "League of Legends", "CS2", "Rust"],
            "navegador": "Opera GX",
            "intereses": ["tecnología", "videojuegos", "Twitch", "YouTube"]
        },
        "hechos": [],
        "preferencias": []
    },
    "voz": [],
    "telegram": [],
}

def _auth():
    return request.headers.get("X-Nova-Token") == _TOKEN

@app.route("/almacen/ping")
def ping():
    return jsonify({"ok": True})

@app.route("/almacen/<nombre>", methods=["GET"])
def leer(nombre):
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    p = _ARCHIVOS.get(nombre)
    if p is None:
        return jsonify({"error": "not found"}), 404
    if not p.exists():
        return jsonify(_DEFAULTS.get(nombre, {}))
    try:
        return jsonify(json.loads(p.read_text(encoding="utf-8")))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/almacen/<nombre>", methods=["PUT"])
def escribir(nombre):
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    p = _ARCHIVOS.get(nombre)
    if p is None:
        return jsonify({"error": "not found"}), 404
    try:
        p.write_text(json.dumps(request.get_json(), ensure_ascii=False, indent=2), encoding="utf-8")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Diagnóstico remoto — whitelist de comandos seguros ───────────────────────

_DIAG_CMDS: dict[str, list[str]] = {
    "status-almacen":  ["systemctl", "status", "nova-almacen",  "--no-pager", "-l"],
    "status-telegram": ["systemctl", "status", "nova-telegram", "--no-pager", "-l"],
    "logs-almacen":    ["journalctl", "-u", "nova-almacen",  "-n", "30", "--no-pager"],
    "logs-telegram":   ["journalctl", "-u", "nova-telegram", "-n", "30", "--no-pager"],
    "disco":           ["df", "-h"],
    "ram":             ["free", "-h"],
    "uptime":          ["uptime"],
    "procesos":        ["pgrep", "-fa", "python"],
}

@app.route("/diagnostico/exec", methods=["POST"])
def diag_exec():
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    cmd_key = (request.get_json() or {}).get("cmd", "")
    if cmd_key not in _DIAG_CMDS:
        return jsonify({"error": f"comando no permitido: {cmd_key}"}), 400
    try:
        r = subprocess.run(
            _DIAG_CMDS[cmd_key],
            capture_output=True, text=True, timeout=10,
        )
        return jsonify({"output": (r.stdout + r.stderr).strip(), "rc": r.returncode})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


_ALEXA_COOKIES = _NOVA_DIR / "alexa_session" / "amazon_cookies.json"

@app.route("/almacen/alexa_cookies", methods=["PUT"])
def escribir_cookies():
    if not _auth():
        return jsonify({"error": "unauthorized"}), 401
    try:
        _ALEXA_COOKIES.parent.mkdir(parents=True, exist_ok=True)
        _ALEXA_COOKIES.write_text(
            json.dumps(request.get_json(), ensure_ascii=False), encoding="utf-8"
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("NOVA Almacén — iniciando en puerto 9101...")
    app.run(host="0.0.0.0", port=9101, debug=False)
