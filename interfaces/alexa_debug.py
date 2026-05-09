"""
Diagnóstico Alexa TTS — prueba 4 variantes y reporta cuál suena.
Ejecutar: python alexa_debug.py
"""
import json, time
from interfaces.alexa_voz import inicializar_alexa, _session, _device, _get_csrf

def test(nombre, seq_or_fn):
    global _session, _device
    # re-importar por si acaso
    import interfaces.alexa_voz as av
    s = av._session
    d = av._device
    if s is None or d is None:
        print("No inicializado")
        return

    csrf = av._get_csrf(s)
    headers = {
        "csrf": csrf,
        "Content-Type": "application/json; charset=UTF-8",
        "Referer": "https://alexa.amazon.es/spa/index.html",
    }

    if callable(seq_or_fn):
        seq_or_fn(s, d, csrf, headers, nombre)
        return

    payload = {
        "behaviorId":   "PREVIEW",
        "sequenceJson": json.dumps(seq_or_fn),
        "status":       "ENABLED",
    }
    r = s.post(
        "https://alexa.amazon.es/api/behaviors/preview",
        data=json.dumps(payload),
        headers=headers,
        timeout=10,
    )
    print(f"[{nombre}] HTTP {r.status_code} | {r.text[:120]}")


def main():
    print("Iniciando Alexa...")
    ok = inicializar_alexa()
    if not ok:
        print("ERROR: no se pudo inicializar")
        return

    import interfaces.alexa_voz as av
    d = av._device
    serial = d.get("serialNumber")
    dtype  = d.get("deviceType")
    cid    = d.get("deviceOwnerCustomerId")
    texto  = "Hola, soy NOVA"

    print(f"\nDevice: {serial} / {dtype} / {cid}\n")

    # ── Variante 1: Alexa.Speak con textToSpeak (en lugar de text) ──────────
    v1 = {
        "@type": "com.amazon.alexa.behaviors.model.Sequence",
        "startNode": {
            "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
            "type": "Alexa.Speak",
            "operationPayload": {
                "deviceType":         dtype,
                "deviceSerialNumber": serial,
                "customerId":         cid,
                "locale":             "es-ES",
                "textToSpeak":        texto,   # <-- clave distinta
            },
        },
    }
    test("Speak/textToSpeak", v1)
    time.sleep(4)

    # ── Variante 2: AlexaAnnouncement con expiry largo ───────────────────────
    v2 = {
        "@type": "com.amazon.alexa.behaviors.model.Sequence",
        "startNode": {
            "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
            "type": "AlexaAnnouncement",
            "operationPayload": {
                "customerId":   cid,
                "expireAfter":  "PT1H",   # <-- antes era PT5S, demasiado corto
                "content": [{
                    "locale": "es-ES",
                    "display": {"title": "NOVA", "body": texto},
                    "speak":   {"type": "text", "value": texto},
                }],
                "target": {
                    "customerId": cid,
                    "devices": [{"deviceSerialNumber": serial, "deviceTypeId": dtype}],
                },
            },
        },
    }
    test("Announcement/PT1H", v2)
    time.sleep(4)

    # ── Variante 3: Alexa.Speak SIN locale ──────────────────────────────────
    v3 = {
        "@type": "com.amazon.alexa.behaviors.model.Sequence",
        "startNode": {
            "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
            "type": "Alexa.Speak",
            "operationPayload": {
                "deviceType":         dtype,
                "deviceSerialNumber": serial,
                "customerId":         cid,
                "text":               texto,
                # locale omitido completamente
            },
        },
    }
    test("Speak/sin-locale", v3)
    time.sleep(4)

    # ── Variante 4: Speak en-US (mercado US — distinto servidor interno) ─────
    v4 = {
        "@type": "com.amazon.alexa.behaviors.model.Sequence",
        "startNode": {
            "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
            "type": "Alexa.Speak",
            "operationPayload": {
                "deviceType":         dtype,
                "deviceSerialNumber": serial,
                "customerId":         cid,
                "locale":             "en-US",
                "text":               texto,
            },
        },
    }
    test("Speak/en-US", v4)

    print("\nFin del test — cuéntame cuál (si alguna) sonó en el Echo.")

if __name__ == "__main__":
    main()
