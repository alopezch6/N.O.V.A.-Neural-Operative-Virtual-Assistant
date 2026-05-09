"""
Alexa Remote Control — TTS via Echo físico.

Flujo:
  1. Primera vez: abre Chrome con Selenium, hace login en Amazon, guarda cookies.
  2. Siguientes veces: carga cookies guardadas (sin abrir navegador).
  3. Para hablar: POST a la API interna de Alexa con el texto.

REVERTIR: Poner USE_ALEXA_TTS = False en config.py. Este módulo no se carga.
"""

import json
import os
import time
import threading
import requests
from pathlib import Path

import sys as _sys
if _sys.platform == "win32":
    _SESSION_DIR = Path("B:/NOVA/alexa_session")
else:
    _SESSION_DIR = Path(__file__).parent / "alexa_session"

_COOKIES_FILE = _SESSION_DIR / "amazon_cookies.json"
_DEVICE_FILE  = _SESSION_DIR / "alexa_device.json"

_session   = None
_device    = None
_init_lock = threading.Lock()


def _selenium_login(email, password):
    """Abre Chrome, hace login en Amazon, retorna dict de cookies."""
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    print("NOVA: [Alexa] Abriendo Chrome para login en Amazon...")

    opts = uc.ChromeOptions()
    opts.add_argument("--start-maximized")
    driver = uc.Chrome(options=opts, version_main=147)

    try:
        signin_url = (
            "https://www.amazon.es/ap/signin"
            "?openid.return_to=https://alexa.amazon.es/spa/index.html"
            "&openid.identity=http://specs.openid.net/auth/2.0/identifier_select"
            "&openid.assoc_handle=amzn_dp_project_dee_es"
            "&openid.mode=checkid_setup"
            "&openid.claimed_id=http://specs.openid.net/auth/2.0/identifier_select"
            "&openid.ns=http://specs.openid.net/auth/2.0"
        )
        driver.get(signin_url)

        wait = WebDriverWait(driver, 30)
        from selenium.webdriver.common.action_chains import ActionChains

        def find_visible(driver, selectors):
            """Busca el primer elemento visible de una lista de selectores CSS."""
            for sel in selectors:
                try:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    for el in els:
                        if el.is_displayed() and el.is_enabled():
                            return el
                except Exception:
                    continue
            return None

        def fill_field(driver, selectors, value):
            el = None
            for _ in range(20):
                el = find_visible(driver, selectors)
                if el:
                    break
                time.sleep(0.5)
            if el is None:
                raise RuntimeError(f"Campo no encontrado: {selectors}")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.4)
            el.click()
            el.clear()
            for ch in value:
                el.send_keys(ch)
                time.sleep(0.03)

        def click_btn(driver, selectors):
            el = None
            for _ in range(20):
                el = find_visible(driver, selectors)
                if el:
                    break
                time.sleep(0.5)
            if el is None:
                raise RuntimeError(f"Botón no encontrado: {selectors}")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.3)
            el.click()

        time.sleep(2)  # Espera a que JS inicialice la página

        # Paso 1: email / teléfono
        fill_field(driver,
            ["#ap_email", "input[name='email']", "input[type='email']", "input[type='text']"],
            email)
        time.sleep(0.5)
        click_btn(driver,
            ["#continue", "input[id='continue']", "input[name='continue']",
             "span#continue input", "input[type='submit']"])

        # Paso 2: password
        fill_field(driver,
            ["#ap_password", "input[name='password']", "input[type='password']"],
            password)
        time.sleep(0.5)
        click_btn(driver,
            ["#signInSubmit", "input[id='signInSubmit']", "input[name='signIn']",
             "input[type='submit']"])

        # Espera: Alexa page o 2FA
        print("NOVA: [Alexa] Esperando redirección... (si hay 2FA, complétalo en el navegador)")
        WebDriverWait(driver, 30).until(
            lambda d: "alexa.amazon.es" in d.current_url
                      or "mfa" in d.current_url.lower()
                      or "approval" in d.current_url.lower()
                      or "ap/cvf" in d.current_url.lower()
        )

        # Si hay 2FA, espera hasta 120s a que el usuario lo complete
        if "alexa.amazon.es" not in driver.current_url:
            print("NOVA: [Alexa] Verifica la identidad en el navegador (máx 120s)...")
            WebDriverWait(driver, 120).until(
                lambda d: "alexa.amazon.es" in d.current_url
            )

        # Capturar cookies de amazon.es (incluye x-main y otras de autorizacion)
        driver.get("https://www.amazon.es")
        time.sleep(2)
        cookies = {c["name"]: c["value"] for c in driver.get_cookies()}

        # Capturar cookies de alexa.amazon.es (session-token, ubid-acbes, etc.)
        driver.get("https://alexa.amazon.es/spa/index.html")
        time.sleep(3)
        cookies.update({c["name"]: c["value"] for c in driver.get_cookies()})

        print(f"NOVA: [Alexa] Login exitoso — {len(cookies)} cookies guardadas.")
        print(f"NOVA: [Alexa] x-main presente: {'x-main' in cookies}")
        return cookies

    finally:
        try:
            driver.quit()
        except Exception:
            pass


def _sync_cookies_to_oracle(cookies: dict) -> None:
    """Sube las cookies al almacén de Oracle para que pueda usarlas sin el PC."""
    try:
        from config import ALMACEN_URL, ALMACEN_TOKEN
        requests.put(
            f"{ALMACEN_URL}/almacen/alexa_cookies",
            json=cookies,
            headers={"X-Nova-Token": ALMACEN_TOKEN},
            timeout=6,
        )
        print("NOVA: [Alexa] Cookies sincronizadas a Oracle.")
    except Exception as e:
        print(f"NOVA: [Alexa] Sync Oracle fallido (no critico): {e}")


def _build_session(cookies: dict) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Origin":          "https://alexa.amazon.es",
        "Referer":         "https://alexa.amazon.es/",
    })
    s.cookies.update(cookies)
    return s


def _session_valid(s: requests.Session) -> bool:
    try:
        r = s.get(
            "https://alexa.amazon.es/api/users/me?platform=ios&version=2.2.556530.0",
            timeout=8,
        )
        return r.status_code == 200
    except Exception:
        return False


def _get_device(s: requests.Session, device_name: str) -> dict:
    r = s.get(
        "https://alexa.amazon.es/api/devices-v2/device?cached=false",
        headers={"Content-Type": "application/json"},
        timeout=10,
    )
    devices = r.json().get("devices", [])
    device = next(
        (d for d in devices if device_name.lower() in d.get("accountName", "").lower()),
        None,
    )
    if device is None:
        nombres = [d.get("accountName") for d in devices]
        raise RuntimeError(
            f"Dispositivo '{device_name}' no encontrado. Disponibles: {nombres}"
        )
    return device


def _get_csrf(s: requests.Session) -> str:
    csrf = s.cookies.get("csrf", "")
    if not csrf:
        s.get("https://alexa.amazon.es/spa/index.html", timeout=8)
        csrf = s.cookies.get("csrf", "")
    return csrf


def inicializar_alexa() -> bool:
    """
    Conecta con Amazon y localiza el Echo configurado.
    Primera vez: abre Chrome para login. Siguientes: usa cookies guardadas.
    """
    global _session, _device
    from config import USE_ALEXA_TTS, ALEXA_EMAIL, ALEXA_PASSWORD, ALEXA_DEVICE_NAME, ALEXA_VOLUME

    if not USE_ALEXA_TTS:
        return False

    with _init_lock:
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)

        # Intenta reutilizar cookies guardadas
        if _COOKIES_FILE.exists():
            try:
                with open(_COOKIES_FILE) as f:
                    saved = json.load(f)
                s = _build_session(saved)
                if _session_valid(s):
                    print("NOVA: [Alexa] Sesión recuperada desde cookies guardadas.")
                    device = _get_device(s, ALEXA_DEVICE_NAME)
                    _session = s
                    _device  = device
                    print(f"NOVA: [Alexa] Conectado -> '{device.get('accountName')}'")
                    _sync_cookies_to_oracle(saved)
                    alexa_volumen(ALEXA_VOLUME)
                    return True
                print("NOVA: [Alexa] Cookies caducadas — rehaciendo login.")
            except Exception as e:
                print(f"NOVA: [Alexa] Error con cookies guardadas: {e}")

        # Login fresco con Selenium
        try:
            cookies = _selenium_login(ALEXA_EMAIL, ALEXA_PASSWORD)
            s = _build_session(cookies)
            with open(_COOKIES_FILE, "w") as f:
                json.dump(dict(s.cookies), f)
            _sync_cookies_to_oracle(dict(s.cookies))
        except Exception as e:
            print(f"NOVA: [Alexa] Error en login Selenium: {e}")
            _session = None
            _device  = None
            return False

        try:
            device = _get_device(s, ALEXA_DEVICE_NAME)
            with open(_DEVICE_FILE, "w") as f:
                json.dump(device, f)
            _session = s
            _device  = device
            print(f"NOVA: [Alexa] Conectado -> '{device.get('accountName')}'")
            alexa_volumen(ALEXA_VOLUME)
            return True
        except Exception as e:
            print(f"NOVA: [Alexa] Error obteniendo dispositivo: {e}")
            _session = None
            _device  = None
            return False


def alexa_parar() -> bool:
    """Detiene lo que el Echo esté reproduciendo en ese momento."""
    if _session is None or _device is None:
        return False
    try:
        csrf = _get_csrf(_session)
        seq = {
            "@type": "com.amazon.alexa.behaviors.model.Sequence",
            "startNode": {
                "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
                "type": "Alexa.DeviceControls.Stop",
                "operationPayload": {
                    "deviceType":         _device.get("deviceType"),
                    "deviceSerialNumber": _device.get("serialNumber"),
                    "customerId":         _device.get("deviceOwnerCustomerId"),
                },
            },
        }
        payload = {"behaviorId": "PREVIEW", "sequenceJson": json.dumps(seq), "status": "ENABLED"}
        r = _session.post(
            "https://alexa.amazon.es/api/behaviors/preview",
            data=json.dumps(payload),
            headers={"csrf": csrf, "Content-Type": "application/json; charset=UTF-8",
                     "Referer": "https://alexa.amazon.es/spa/index.html"},
            timeout=8,
        )
        ok = r.status_code in (200, 204)
        if ok:
            print("NOVA: [Alexa] Stop enviado al Echo.")
        return ok
    except Exception as e:
        print(f"NOVA: [Alexa] Error enviando Stop: {e}")
        return False


def alexa_volumen(nivel: int) -> bool:
    """Ajusta el volumen del Echo (0-10)."""
    if _session is None or _device is None:
        return False
    try:
        csrf = _get_csrf(_session)
        seq = {
            "@type": "com.amazon.alexa.behaviors.model.Sequence",
            "startNode": {
                "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
                "type": "Alexa.DeviceControls.Volume",
                "operationPayload": {
                    "deviceType":         _device.get("deviceType"),
                    "deviceSerialNumber": _device.get("serialNumber"),
                    "customerId":         _device.get("deviceOwnerCustomerId"),
                    "value":              str(nivel),
                },
            },
        }
        payload = {"behaviorId": "PREVIEW", "sequenceJson": json.dumps(seq), "status": "ENABLED"}
        r = _session.post(
            "https://alexa.amazon.es/api/behaviors/preview",
            data=json.dumps(payload),
            headers={"csrf": csrf, "Content-Type": "application/json; charset=UTF-8",
                     "Referer": "https://alexa.amazon.es/spa/index.html"},
            timeout=10,
        )
        ok = r.status_code in (200, 204)
        if ok:
            print(f"NOVA: [Alexa] Volumen ajustado a {nivel}.")
        return ok
    except Exception as e:
        print(f"NOVA: [Alexa] Error ajustando volumen: {e}")
        return False


_ALEXA_MAX_CHARS = 250


def _partir_texto(texto: str, max_chars: int = _ALEXA_MAX_CHARS) -> list[str]:
    """
    Divide texto en trozos de max_chars respetando límites de frase.
    La API de Alexa.Speak corta silenciosamente por encima de ~250 caracteres.
    """
    if len(texto) <= max_chars:
        return [texto]

    chunks = []
    while len(texto) > max_chars:
        # Buscar el último punto, coma o espacio antes del límite
        corte = max_chars
        for sep in (". ", ", ", " "):
            pos = texto.rfind(sep, 0, max_chars)
            if pos != -1:
                corte = pos + len(sep)
                break
        chunks.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    if texto:
        chunks.append(texto)
    return chunks


def _nodo_speak(chunk: str) -> dict:
    return {
        "@type": "com.amazon.alexa.behaviors.model.OpaquePayloadOperationNode",
        "type":  "Alexa.Speak",
        "operationPayload": {
            "deviceType":         _device.get("deviceType"),
            "deviceSerialNumber": _device.get("serialNumber"),
            "customerId":         _device.get("deviceOwnerCustomerId"),
            "locale":             "es-ES",
            "textToSpeak":        chunk,
        },
    }


def alexa_habla(texto: str) -> bool:
    """
    Envía texto al Echo para que Alexa lo pronuncie.
    Parte automáticamente textos >250 chars en nodos seriales para evitar cortes.
    Retorna True si el envío fue exitoso, False si falló.
    """
    if _session is None or _device is None:
        print("NOVA: [Alexa] No inicializado — ignorando llamada.")
        return False

    try:
        csrf = _get_csrf(_session)
        chunks = _partir_texto(texto)

        if len(chunks) == 1:
            start_node = _nodo_speak(chunks[0])
        else:
            print(f"NOVA: [Alexa TTS] Texto partido en {len(chunks)} trozos ({len(texto)} chars).")
            start_node = {
                "@type": "com.amazon.alexa.behaviors.model.SerialNode",
                "nodesToExecute": [_nodo_speak(c) for c in chunks],
            }

        seq = {
            "@type":     "com.amazon.alexa.behaviors.model.Sequence",
            "startNode": start_node,
        }

        payload = {
            "behaviorId":   "PREVIEW",
            "sequenceJson": json.dumps(seq),
            "status":       "ENABLED",
        }

        r = _session.post(
            "https://alexa.amazon.es/api/behaviors/preview",
            data=json.dumps(payload),
            headers={
                "csrf":         csrf,
                "Content-Type": "application/json; charset=UTF-8",
                "Referer":      "https://alexa.amazon.es/spa/index.html",
            },
            timeout=10,
        )

        if r.status_code in (200, 204):
            print("NOVA: [Alexa TTS] Enviado al Echo.")
            return True

        print(f"NOVA: [Alexa TTS] HTTP {r.status_code}: {r.text[:200]}")
        return False

    except Exception as e:
        print(f"NOVA: [Alexa TTS] Error: {e}")
        return False
