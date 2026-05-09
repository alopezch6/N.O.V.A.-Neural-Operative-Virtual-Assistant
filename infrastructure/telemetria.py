"""
NOVA — Telemetría Oracle
Expone CPU, RAM y temperatura del nodo Oracle.
Puerto 9100. Arrancar con: python3 telemetria.py
"""
from flask import Flask, jsonify
import psutil

app = Flask(__name__)

def _get_temp():
    # Linux ARM: leer thermal_zone
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass
    try:
        temps = psutil.sensors_temperatures()
        for vals in temps.values():
            if vals:
                return round(vals[0].current, 1)
    except Exception:
        pass
    return None

@app.route('/telemetria')
def telemetria():
    return jsonify({
        'cpu':  round(psutil.cpu_percent(interval=0.5)),
        'ram':  round(psutil.virtual_memory().percent),
        'temp': _get_temp(),
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9100, debug=False)
