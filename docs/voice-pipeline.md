# Voice Pipeline

NOVA's voice pipeline is designed to feel like a native voice assistant — sub-second wake-word detection, accurate Spanish transcription, and a layered TTS chain with automatic fallback.

---

## Pipeline Overview

```
Microphone input (continuous)
        │
        ▼
  Vosk — offline wake-word detection
  Triggers on: "nova", "hey nova", "oye nova" (+ phonetic variants)
        │
        ▼
  faster-Whisper large-v3-turbo (CUDA float16)
  Spanish transcription — silence-gated
        │
        ▼
  nova.py — routing + response generation
        │
        ▼
  TTS chain (priority order):
    1. Kokoro TTS (local neural voice)
    2. Edge TTS — es-ES-AlvaroNeural (cloud, free)
    3. Amazon Alexa Remote Control (Echo Dot)
```

---

## Wake Word Detection (Vosk)

**Module:** `interfaces/voz.py` → `esperar_activacion()`  
**Model:** `vosk-model-small-es-0.42` (offline, ~40MB)

Runs continuously in a background thread. Listens for activation words defined in `config.py`:

```python
ACTIVACIONES = ["nova", "no va", "novo", "noba", "oye nova", "hey nova", "oye no va"]
```

Phonetic variants cover common Spanish misrecognitions of "nova". Detection happens entirely offline — no API call, no latency.

On trigger, NOVA responds with a short activation phrase ("Dime.", "Te escucho.", etc.) and opens the listening window.

---

## Speech Recognition (faster-Whisper)

**Model:** `large-v3-turbo`  
**Runtime:** CUDA float16  
**Module:** `interfaces/voz.py` → `nova_escucha()`

Silence-gated recording with Alexa-style timing (configurable in `config.py`):

| Parameter | Value | Description |
|---|---|---|
| `ESCUCHA_TIMEOUT_INICIO` | 8.0s | Silence before speech → session timeout |
| `ESCUCHA_SILENCIO_FIN` | 1.5s | Silence after speech → end of command |
| `ESCUCHA_MAX_DURACION` | 10.0s | Maximum active speech duration |
| `ESCUCHA_UMBRAL_VOZ` | 300 | Minimum amplitude to count as speech |

The audio block size is fixed at 8000 samples @ 16kHz (0.5s/block) — matched to Vosk's expected input format.

---

## TTS Chain

**Module:** `interfaces/voz.py` → `nova_habla()`

Three TTS backends in priority order:

### 1. Kokoro TTS (local)
Neural TTS running locally. No API call, no latency from network. Used when available.

### 2. Edge TTS (cloud fallback)
Microsoft Edge TTS, Spanish voice `es-ES-AlvaroNeural`, rate `+15%`. Free, no key required. Fallback when Kokoro is unavailable.

### 3. Alexa Remote Control (primary, configurable)
Sends text to an Amazon Echo Dot via `alexa_voz.py`. The Echo Dot speaks the response through its speaker. Enabled by default (`USE_ALEXA_TTS = True` in `config.py`). Useful when the PC speakers are not the preferred audio output.

To switch back to local TTS:
```python
# config.py
USE_ALEXA_TTS = False
```

---

## Audio Reactive Widget

The PySide6 orb widget (`interfaces/nova_widget_qt.py`) captures system audio via PyAudio loopback (Stereo Mix / Mezcla Estéreo) and computes 64 frequency bands using FFT. The bands are pushed to the WebGL renderer via JavaScript every 50ms, making the orb react to any system audio in real time.
