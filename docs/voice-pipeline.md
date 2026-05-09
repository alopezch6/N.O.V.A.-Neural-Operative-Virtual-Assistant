# Pipeline de Voz

El pipeline de voz de NOVA está diseñado para sentirse como un asistente de voz nativo — detección de palabra de activación en menos de un segundo, transcripción precisa en español y una cadena TTS con fallback automático.

---

## Resumen del Pipeline

```
Entrada de micrófono (continua)
        │
        ▼
  Vosk — detección de palabra de activación offline
  Se activa con: "nova", "hey nova", "oye nova" (+ variantes fonéticas)
        │
        ▼
  faster-Whisper large-v3-turbo (CUDA float16)
  Transcripción en español — con control de silencio
        │
        ▼
  nova.py — enrutamiento + generación de respuesta
        │
        ▼
  Cadena TTS (por orden de prioridad):
    1. Kokoro TTS (voz neuronal local)
    2. Edge TTS — es-ES-AlvaroNeural (nube, gratuito)
    3. Alexa Remote Control (Amazon Echo Dot)
```

---

## Detección de Palabra de Activación (Vosk)

**Módulo:** `interfaces/voz.py` → `esperar_activacion()`  
**Modelo:** `vosk-model-small-es-0.42` (offline, ~40MB)

Corre continuamente en un hilo de fondo. Escucha las palabras de activación definidas en `config.py`:

```python
ACTIVACIONES = ["nova", "no va", "novo", "noba", "oye nova", "hey nova", "oye no va"]
```

Las variantes fonéticas cubren confusiones comunes del español al reconocer "nova". La detección ocurre completamente offline — sin llamada a API, sin latencia.

Al activarse, NOVA responde con una frase corta de confirmación ("Dime.", "Te escucho.", etc.) y abre la ventana de escucha.

---

## Reconocimiento de Voz (faster-Whisper)

**Modelo:** `large-v3-turbo`  
**Runtime:** CUDA float16  
**Módulo:** `interfaces/voz.py` → `nova_escucha()`

Grabación con control de silencio al estilo Alexa (configurable en `config.py`):

| Parámetro | Valor | Descripción |
|---|---|---|
| `ESCUCHA_TIMEOUT_INICIO` | 8,0s | Silencio antes del habla → tiempo de espera de sesión |
| `ESCUCHA_SILENCIO_FIN` | 1,5s | Silencio después del habla → fin del comando |
| `ESCUCHA_MAX_DURACION` | 10,0s | Duración máxima del habla activa |
| `ESCUCHA_UMBRAL_VOZ` | 300 | Amplitud mínima para contar como voz |

El tamaño de bloque de audio es fijo: 8000 muestras a 16kHz (0,5s/bloque) — adaptado al formato de entrada esperado por Vosk.

---

## Cadena TTS

**Módulo:** `interfaces/voz.py` → `nova_habla()`

Tres backends TTS por orden de prioridad:

### 1. Kokoro TTS (local)
TTS neuronal que corre localmente. Sin llamada a API, sin latencia de red. Se usa cuando está disponible.

### 2. Edge TTS (fallback en la nube)
Microsoft Edge TTS, voz en español `es-ES-AlvaroNeural`, velocidad `+15%`. Gratuito, sin clave requerida. Fallback cuando Kokoro no está disponible.

### 3. Alexa Remote Control (configurable como principal)
Envía el texto a un Amazon Echo Dot vía `alexa_voz.py`. El Echo Dot pronuncia la respuesta por su altavoz. Habilitado por defecto (`USE_ALEXA_TTS = True` en `config.py`). Útil cuando los altavoces del PC no son la salida de audio preferida.

Para volver al TTS local:
```python
# config.py
USE_ALEXA_TTS = False
```

---

## Widget Reactivo al Audio

El widget PySide6 (`interfaces/nova_widget_qt.py`) captura el audio del sistema vía loopback PyAudio (Stereo Mix / Mezcla Estéreo) y calcula 64 bandas de frecuencia mediante FFT. Las bandas se envían al renderizador WebGL vía JavaScript cada 50ms, haciendo que el orbe reaccione al audio del sistema en tiempo real.
