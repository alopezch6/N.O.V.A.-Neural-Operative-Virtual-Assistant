import asyncio
import re
import time
# import pygame
import queue
import json
import numpy as np
import math
import threading
import wave
import io
import soundfile as sf
import sounddevice as sd
from vosk import Model, KaldiRecognizer
from faster_whisper import WhisperModel
from kokoro import KPipeline
from config import (
    VOSK_MODEL_PATH, ACTIVACIONES, VOICE, VOICE_RATE, USE_ALEXA_TTS,
    ESCUCHA_UMBRAL_VOZ, ESCUCHA_TIMEOUT_INICIO, ESCUCHA_SILENCIO_FIN, ESCUCHA_MAX_DURACION,
)

# ── Vosk wake word ──────────────────────────────────────────────────────────
model = Model(VOSK_MODEL_PATH)

# ── Faster-Whisper ──────────────────────────────────────────────────────────
print("NOVA: Cargando Whisper...")
whisper_model = WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")
print("NOVA: Whisper cargado.")

# Prompt inicial: contextualiza a Whisper con vocabulario frecuente de NOVA
# Incluye apps, nombres propios y tecnicismos que el modelo suele malinterpretar
_WHISPER_PROMPT = (
    "Comandos de voz para asistente de IA: "
    "abre Steam, abre Discord, abre Spotify, abre Chrome, abre Opera, abre Firefox, "
    "abre Telegram, abre WhatsApp, abre Word, abre Excel, abre PowerPoint, "
    "cierra Steam, cierra Discord, cierra Chrome, cierra Spotify, "
    "reproduce música en Spotify, pausa Spotify, sube el volumen, baja el volumen, "
    "busca en YouTube, abre YouTube, pon Netflix, abre Twitch, "
    "ejecuta script Python, abre la terminal, instala programa, descarga archivo, "
    "reinicia Windows, silencia el micro, captura pantalla, "
    "qué hora es, qué tiempo hace, dime las noticias, "
    "abre Valorant, abre League of Legends, abre World of Warcraft, abre CS2, abre Rust"
)

# Palabras clave que deben tener mayor probabilidad durante la transcripción
_WHISPER_HOTWORDS = (
    "Steam, Discord, Spotify, Chrome, Opera, Firefox, Telegram, WhatsApp, "
    "YouTube, Netflix, Twitch, Valorant, League of Legends, World of Warcraft, CS2, Rust, "
    "Ollama, Python, Windows, Excel, PowerPoint, Word"
)

# Correcciones de transcripciones erróneas conocidas (clave: lo que dice Whisper, valor: lo correcto)
_CORRECCIONES = {
    # Steam
    "es tip": "Steam",
    "es tim": "Steam",
    "es team": "Steam",
    "estip": "Steam",
    "estim": "Steam",
    "esteem": "Steam",
    "estén": "Steam",
    "isteam": "Steam",
    "stem": "Steam",
    "estima": "Steam",
    "estimas": "Steam",
    # "este" es palabra común — solo se corrige en contexto de comando (ver _corregir_este_steam)

    # Discord
    "díscord": "Discord",
    "dis cord": "Discord",
    "discor": "Discord",
    "des cord": "Discord",
    "descord": "Discord",
    # Spotify
    "es poti": "Spotify",
    "espotify": "Spotify",
    "espoti": "Spotify",
    "spotifai": "Spotify",
    "espotifai": "Spotify",
    # Twitch
    "tuich": "Twitch",
    "tu ich": "Twitch",
    "twich": "Twitch",
    "tuic": "Twitch",
    # YouTube
    "jutub": "YouTube",
    "ju tub": "YouTube",
    "iutub": "YouTube",
    "you tuve": "YouTube",
    "iutube": "YouTube",
    # Netflix
    "netflis": "Netflix",
    "net flis": "Netflix",
    "netflex": "Netflix",
    "net flex": "Netflix",
    # WhatsApp
    "guasap": "WhatsApp",
    "güasap": "WhatsApp",
    "gua sap": "WhatsApp",
    "whasap": "WhatsApp",
    "wasap": "WhatsApp",
    "güats ap": "WhatsApp",
    # Telegram
    "telegran": "Telegram",
    "tele gram": "Telegram",
    # Firefox
    "fáierfojs": "Firefox",
    "faire fox": "Firefox",
    "fayer fox": "Firefox",
    "faierfox": "Firefox",
    "fire fojs": "Firefox",
    # Chrome
    "crom": "Chrome",
    "crome": "Chrome",
    # Valorant
    "valorán": "Valorant",
    "balorant": "Valorant",
    "balo ran": "Valorant",
    "valo ran": "Valorant",
    # League of Legends
    "lig of leyends": "League of Legends",
    "liga de leyendas": "League of Legends",
    "liga leyendas": "League of Legends",
    "lig of legends": "League of Legends",
    # CS2
    "ce ese dos": "CS2",
    "ce es dos": "CS2",
    # Rust
    "ras": "Rust",
    "rast": "Rust",
    # PowerPoint
    "pauer poin": "PowerPoint",
    "power poin": "PowerPoint",
    "pauerpoin": "PowerPoint",
    "powerpoin": "PowerPoint",
    # Python
    "paiton": "Python",
    "pai ton": "Python",
    "piton": "Python",
    # Windows
    "güindous": "Windows",
    "güindows": "Windows",
    "güindoz": "Windows",
    "winsows": "Windows",
    "windous": "Windows",
    # Microsoft Word
    "güord": "Word",
    "güor": "Word",
    # Excel
    "eksel": "Excel",
    "exel": "Excel",
    # Zoom
    "zum": "Zoom",
    "sum": "Zoom",
    # Microsoft Teams
    "tims": "Teams",
    "tim": "Teams",
    # Slack
    "eslak": "Slack",
    "es lak": "Slack",
    # Epic Games
    "epic geims": "Epic Games",
    "epik geim": "Epic Games",
    "epic gaims": "Epic Games",
    # Battle.net
    "batol net": "Battle.net",
    "batl net": "Battle.net",
    "batel net": "Battle.net",
    # OBS
    "o be ese": "OBS",
    "o bi es": "OBS",
    # Photoshop
    "fotoshop": "Photoshop",
    "foto shop": "Photoshop",
    "fotoxop": "Photoshop",
    # Visual Studio Code
    "bisual estudio cod": "Visual Studio Code",
    "bisual cod": "Visual Studio Code",
    "bi es cod": "VS Code",
    "be es cod": "VS Code",
    # DeepSeek
    "dip sik": "DeepSeek",
    "dip seek": "DeepSeek",
    "deep sik": "DeepSeek",
    # Tailscale
    "tail escale": "Tailscale",
    "tails keil": "Tailscale",
    "teilskeil": "Tailscale",
    # Oracle
    "oraquil": "Oracle",
    "orakle": "Oracle",
    # Docker
    "doker": "Docker",
    "doquer": "Docker",
    # Reddit
    "redit": "Reddit",
    "re dit": "Reddit",
    # WiFi
    "güifi": "WiFi",
    "güi fi": "WiFi",
    "uifi": "WiFi",
    # Bluetooth
    "blutut": "Bluetooth",
    "blu tut": "Bluetooth",
    "blutús": "Bluetooth",
    # NVIDIA
    "enbidea": "NVIDIA",
    "en bidea": "NVIDIA",
    "invidia": "NVIDIA",
    # GitHub
    "git jab": "GitHub",
    "git jub": "GitHub",
    "githab": "GitHub",
    # Correcciones de verbos: Whisper convierte imperativos a forma conjugada
    "he abierto": "abre",
    "ha abierto": "abre",
    "hm abierto": "abre",
    "he cerrado": "cierra",
    "ha cerrado": "cierra",
    "he reproducido": "reproduce",
    "he pausado": "pausa",
    "he subido": "sube",
    "he bajado": "baja",
    "he instalado": "instala",
    "he descargado": "descarga",
    "he buscado": "busca",
    "he silenciado": "silencia",
    "he reiniciado": "reinicia",
}

_VERBOS_COMANDO = (
    r"(?:puedes\s+)?(?:abre[rs]?|abrir|cierra[rs]?|cerrar|inicia[rs]?|iniciar|"
    r"lanza[rs]?|lanzar|ejecuta[rs]?|ejecutar|pon|poner|para[rs]?|parar|"
    r"mata[rs]?|matar|instala[rs]?|instalar|desinstala[rs]?|desinstalar|"
    r"reproduce[rs]?|reproducir|abre[rs]?)"
)

def _corregir_transcripcion(texto: str) -> str:
    """Corrige palabras mal transcritas por Whisper en habla española."""
    for error, correcto in _CORRECCIONES.items():
        if " " in error:
            texto = re.sub(re.escape(error), correcto, texto, flags=re.IGNORECASE)
        else:
            texto = re.sub(rf'\b{re.escape(error)}\b', correcto, texto, flags=re.IGNORECASE)
    # "este" solo se corrige a Steam cuando va precedido de un verbo de comando
    texto = re.sub(rf'({_VERBOS_COMANDO})\s+este\b', r'\1 Steam', texto, flags=re.IGNORECASE)
    return texto

# ── Kokoro TTS ────────────────────────────────────────────────────────────────
print("NOVA: Cargando Kokoro...")
import os as _os
_os.environ.setdefault("KOKORO_DEVICE", "cpu")
import torch as _torch
_kokoro = KPipeline(lang_code="e", repo_id="hexgrad/Kokoro-82M", device=_torch.device("cpu"))
print("NOVA: Kokoro listo.")

interrumpir = threading.Event()
_listener_thread = None

# Buffer para acumular frases en modo Alexa TTS (se envían juntas al Echo al final)
_alexa_buffer: list = []


# ── TTS: Kokoro ───────────────────────────────────────────────────────────────

def _habla_kokoro(texto):
    generator = _kokoro(texto, voice="ef_dora", speed=1.15)
    chunks = []
    for _, _, audio in generator:
        chunks.append(audio)
    if not chunks:
        return None
    audio_np = np.concatenate(chunks)
    audio_int16 = (audio_np * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio_int16.tobytes())
    buf.seek(0)
    return buf


# ── TTS: Edge TTS (respaldo offline) ─────────────────────────────────────────

import edge_tts

async def _habla_edge_async(texto):
    import subprocess, imageio_ffmpeg
    mp3 = "B:/NOVA/nova_respuesta.mp3"
    wav = "B:/NOVA/nova_respuesta_edge.wav"
    communicate = edge_tts.Communicate(texto, VOICE, rate=VOICE_RATE)
    await communicate.save(mp3)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ffmpeg, "-y", "-i", mp3, "-ar", "24000", "-ac", "1", wav],
                   capture_output=True)
    return wav

def _habla_edge(texto):
    return asyncio.run(_habla_edge_async(texto))


# ── Reproducción con pygame ──────────────────────────────────────────────────

def _reproducir(ruta_audio):
    pygame.mixer.init(frequency=24000, size=-16, channels=1)
    pygame.mixer.music.load(ruta_audio)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        if interrumpir.is_set():
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.quit()
            print("NOVA: Interrumpida.")
            return
        pygame.time.Clock().tick(10)
    pygame.mixer.music.unload()
    pygame.mixer.quit()


# ── API pública ──────────────────────────────────────────────────────────────

def limpiar_texto(texto):
    texto = re.sub(r'\*+', '', texto)
    texto = re.sub(r'\.{2,}', ',', texto)
    texto = re.sub(r'\.\s+', '. ', texto)
    texto = re.sub(r'^\s*[-]\s*', '', texto, flags=re.MULTILINE)
    texto = re.sub(r'<think>.*?</think>', '', texto, flags=re.DOTALL)
    return texto.strip()

def nova_habla(texto):
    """Genera y reproduce una frase de forma inmediata (no streaming)."""
    global _listener_thread

    texto = limpiar_texto(texto)
    if not texto:
        return

    # Modo Alexa: el Echo pronuncia el texto directamente
    if USE_ALEXA_TTS:
        from alexa_voz import alexa_habla
        print(f"NOVA: {texto}")
        if alexa_habla(texto):
            _esperar_alexa_con_interrupcion(texto)
            return
        # Si Alexa falla, cae al TTS local

    ruta = None
    try:
        ruta = _habla_kokoro(texto)
        print("NOVA: [Kokoro TTS]")
    except Exception as e:
        print(f"NOVA: Kokoro TTS falló -> {e}")
        try:
            ruta = _habla_edge(texto)
            print("NOVA: [Edge TTS fallback]")
        except Exception as e2:
            print(f"NOVA: Edge TTS también falló -> {e2}")
            print(f"NOVA (texto): {texto}")
            return

    if _listener_thread and _listener_thread.is_alive():
        interrumpir.set()
        _listener_thread.join(timeout=1.0)

    interrumpir.clear()
    _listener_thread = threading.Thread(target=escuchar_interrupcion, daemon=True)
    _listener_thread.start()

    try:
        _reproducir(ruta)
    except Exception as e:
        print(f"NOVA: Error reproduciendo audio -> {e}")


# ── API pipeline (TTS separado de reproducción) ──────────────────────────────

def nova_tts(texto):
    """
    Genera audio sin reproducir. Devuelve BytesIO o None.
    En modo Alexa acumula el texto en buffer (se envía al Echo con nova_alexa_flush).
    """
    texto = limpiar_texto(texto)
    if not texto:
        return None

    if USE_ALEXA_TTS:
        _alexa_buffer.append(texto)
        print(f"NOVA: {texto}")
        return None  # nova_reproduce(None) es no-op; flush al final del streaming

    try:
        buf = _habla_kokoro(texto)
        print("NOVA: [Kokoro TTS]")
        return buf
    except Exception as e:
        print(f"NOVA: Kokoro TTS fallo -> {e}")
        try:
            return _habla_edge(texto)
        except Exception as e2:
            print(f"NOVA: Edge TTS fallo -> {e2}")
            return None


def _esperar_alexa_con_interrupcion(texto: str):
    """
    Espera el tiempo estimado de locución del Echo escuchando en paralelo.
    Si se detecta la palabra de activación, para el Echo y sale.
    """
    global _listener_thread
    delay = max(1.5, len(texto.split()) * 0.4 + 0.8)

    interrumpir.clear()
    _listener_thread = threading.Thread(target=escuchar_interrupcion, daemon=True)
    _listener_thread.start()

    t0 = time.time()
    while time.time() - t0 < delay:
        if interrumpir.is_set():
            from alexa_voz import alexa_parar
            alexa_parar()
            print("NOVA: [Alexa] Interrumpida por palabra de activación.")
            return
        time.sleep(0.08)

    interrumpir.set()  # detiene el hilo de escucha


def nova_alexa_flush():
    """
    Envía todo el texto acumulado al Echo de una vez y limpia el buffer.
    Llamar después de que el play_worker termine en nova_piensa_streaming.
    No hace nada si USE_ALEXA_TTS es False.
    """
    global _alexa_buffer
    if not USE_ALEXA_TTS or not _alexa_buffer:
        _alexa_buffer = []
        return
    from alexa_voz import alexa_habla
    texto_completo = " ".join(_alexa_buffer)
    _alexa_buffer = []
    print(f"NOVA: [Alexa TTS] Enviando respuesta completa al Echo ({len(texto_completo)} chars)")
    if alexa_habla(texto_completo):
        _esperar_alexa_con_interrupcion(texto_completo)

def nova_reproduce(buf):
    """Reproduce buffer de audio con soporte de interrupcion."""
    global _listener_thread
    if buf is None:
        return
    if _listener_thread and _listener_thread.is_alive():
        interrumpir.set()
        _listener_thread.join(timeout=1.0)
    interrumpir.clear()
    _listener_thread = threading.Thread(target=escuchar_interrupcion, daemon=True)
    _listener_thread.start()
    try:
        _reproducir(buf)
    except Exception as e:
        print(f"NOVA: Error reproduciendo -> {e}")


# ── Wake word y escucha ──────────────────────────────────────────────────────

_APRENDIDAS_PATH = "B:/NOVA/activaciones_aprendidas.json"
_NUCLEOS_NOVA    = ["nova", "noba", "novo"]   # variantes fonéticas base
_EXCLUIDAS_FUZZY = {"novia", "novio", "novios", "novias"}  # palabras comunes que no deben activar

def _cargar_aprendidas():
    try:
        with open(_APRENDIDAS_PATH) as f:
            return set(json.load(f))
    except Exception:
        return set()

def _guardar_aprendida(palabra):
    aprendidas = _cargar_aprendidas()
    if palabra not in aprendidas:
        aprendidas.add(palabra)
        with open(_APRENDIDAS_PATH, "w") as f:
            json.dump(list(aprendidas), f)
        print(f"NOVA: [Wake word] Nueva variante aprendida: '{palabra}'")

def _levenshtein(a, b):
    if abs(len(a) - len(b)) > 2:
        return 99
    dp = list(range(len(b) + 1))
    for ca in a:
        ndp = [dp[0] + 1]
        for j, cb in enumerate(b):
            ndp.append(min(dp[j] + (ca != cb), dp[j + 1] + 1, ndp[j] + 1))
        dp = ndp
    return dp[-1]

def _es_similar_nova(palabra):
    """True si la palabra tiene distancia de edición ≤ 1 con algún núcleo de activación."""
    if palabra in _EXCLUIDAS_FUZZY:
        return False
    if not (3 <= len(palabra) <= 6):
        return False
    return any(_levenshtein(palabra, nucleo) <= 1 for nucleo in _NUCLEOS_NOVA)

_activaciones_extra: set = _cargar_aprendidas()

def limpiar_activacion(texto):
    for palabra in list(ACTIVACIONES) + list(_activaciones_extra):
        texto = texto.replace(palabra, "").strip()
    return texto.strip()

def contiene_activacion(texto):
    global _activaciones_extra
    # Coincidencia exacta (lista fija + aprendidas)
    todas = list(ACTIVACIONES) + list(_activaciones_extra)
    if any(p in texto for p in todas):
        return True
    # Coincidencia fuzzy por palabra
    for palabra in texto.split():
        if _es_similar_nova(palabra):
            _activaciones_extra.add(palabra)
            _guardar_aprendida(palabra)
            return True
    return False

def escuchar_interrupcion():
    rec = KaldiRecognizer(model, 16000)
    q = queue.Queue()

    def callback(indata, frames, time, status):
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16', channels=1, callback=callback):
        while not interrumpir.is_set():
            try:
                data = q.get(timeout=0.1)
                if rec.AcceptWaveform(data):
                    resultado = json.loads(rec.Result())
                    if contiene_activacion(resultado.get("text", "").lower()):
                        interrumpir.set()
                        return
                else:
                    parcial = json.loads(rec.PartialResult())
                    if contiene_activacion(parcial.get("partial", "").lower()):
                        interrumpir.set()
                        return
            except queue.Empty:
                continue

def reproducir_pitido():
    sample_rate = 44100

    def tono(freq, duracion, volumen=0.4, fade=True):
        frames = int(sample_rate * duracion)
        t = np.linspace(0, duracion, frames, False)
        onda = np.sin(2 * math.pi * freq * t)
        if fade:
            onda = onda * np.linspace(1, 0, frames)
        return (onda * volumen * 32767).astype(np.int16)

    t1 = tono(420, 0.08, volumen=0.3, fade=False)
    silencio = np.zeros(int(sample_rate * 0.03), dtype=np.float32)
    t2 = tono(840, 0.08, volumen=0.4, fade=False)
    t3 = tono(1260, 0.15, volumen=0.5, fade=True)
    secuencia = np.concatenate([t1, silencio, t2, silencio, t3])

    pygame.mixer.init(frequency=sample_rate)
    sonido = pygame.sndarray.make_sound(np.column_stack([secuencia, secuencia]).astype(np.int16))
    sonido.play()
    pygame.time.wait(400)
    pygame.mixer.quit()

def esperar_activacion():
    """
    Espera hasta oír la palabra de activación.
    Si la activación viene acompañada de un comando ("oye nova estás?"),
    devuelve el comando limpio. Si viene sola ("Nova"), devuelve None
    y el bucle principal llama a nova_escucha() para el comando.
    """
    rec = KaldiRecognizer(model, 16000)
    q = queue.Queue()
    wake_detectado = False

    def callback(indata, frames, time, status):
        q.put(bytes(indata))

    print("NOVA: En espera... (di 'Nova' para activar)")
    with sd.RawInputStream(samplerate=16000, blocksize=8000, dtype='int16', channels=1, callback=callback):
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                resultado = json.loads(rec.Result())
                texto = resultado.get("text", "").lower()
                if contiene_activacion(texto) or wake_detectado:
                    comando = limpiar_activacion(texto)
                    if comando:
                        comando = _corregir_transcripcion(comando)
                    return comando if comando else None
            else:
                if not wake_detectado:
                    parcial = json.loads(rec.PartialResult())
                    if contiene_activacion(parcial.get("partial", "").lower()):
                        # Wake word detectado a mitad de frase — seguir grabando
                        # hasta que Vosk cierre el utterance y tengamos el texto completo
                        wake_detectado = True

def nova_escucha():
    """
    Graba un comando con tiempos tipo Alexa (configurables en config.py):
      - Fase 1 — espera inicio: si no empieza a hablar en ESCUCHA_TIMEOUT_INICIO s → None
      - Fase 2 — habla activa: máximo ESCUCHA_MAX_DURACION s de voz continua
      - Fase 3 — fin: ESCUCHA_SILENCIO_FIN s de silencio tras el habla → corta y transcribe
    """
    # Limpiar estado de interrupción previo (puede quedar Set tras Alexa TTS)
    interrumpir.clear()

    print("NOVA: Escuchando...")
    SAMPLERATE = 16000
    BLOCK      = 8000   # 0.5s por bloque — fijo para mantener coherencia con Vosk

    bloques_por_seg      = SAMPLERATE / BLOCK          # = 2.0
    T_INICIO_BLOQUES = int(ESCUCHA_TIMEOUT_INICIO * bloques_por_seg)   # e.g. 16
    T_FIN_BLOQUES    = int(ESCUCHA_SILENCIO_FIN   * bloques_por_seg)   # e.g. 3
    T_MAX_BLOQUES    = int(ESCUCHA_MAX_DURACION   * bloques_por_seg)   # e.g. 20

    q = queue.Queue()
    frames            = []
    habla_detectada   = False
    bloques_sin_habla = 0
    bloques_silencio  = 0
    bloques_habla     = 0

    def callback(indata, frame_count, time_info, status):
        q.put(bytes(indata))

    with sd.RawInputStream(samplerate=SAMPLERATE, blocksize=BLOCK, dtype='int16', channels=1, callback=callback):
        while True:
            data     = q.get()
            audio_np = np.frombuffer(data, dtype=np.int16)
            es_voz   = np.abs(audio_np).mean() >= ESCUCHA_UMBRAL_VOZ

            if not habla_detectada:
                # Fase 1: esperando que empiece a hablar
                if es_voz:
                    habla_detectada = True
                    frames.append(data)
                else:
                    bloques_sin_habla += 1
                    if bloques_sin_habla >= T_INICIO_BLOQUES:
                        return None   # timeout: no empezó a hablar
            else:
                # Fase 2/3: grabando comando
                frames.append(data)
                if es_voz:
                    bloques_habla   += 1
                    bloques_silencio = 0
                else:
                    bloques_silencio += 1
                    if bloques_silencio >= T_FIN_BLOQUES:
                        break   # silencio sostenido → fin del comando
                if bloques_habla >= T_MAX_BLOQUES:
                    break       # límite máximo de habla

    if len(frames) < 2:   # menos de 1s de audio: seguramente ruido
        return None

    audio_data = b''.join(frames)
    tmp_path = "B:/NOVA/temp_audio.wav"
    with wave.open(tmp_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLERATE)
        wf.writeframes(audio_data)

    try:
        segments, _ = whisper_model.transcribe(
            tmp_path,
            language="es",
            beam_size=5,
            vad_filter=True,
            initial_prompt=_WHISPER_PROMPT,
            hotwords=_WHISPER_HOTWORDS,
            condition_on_previous_text=False,
            temperature=0,
            no_speech_threshold=0.5,
        )
        texto = _corregir_transcripcion(" ".join([s.text for s in segments]).strip())
        if texto:
            print(f"Alex: {texto}")
            return texto
        return None
    except Exception as e:
        print(f"NOVA: Error transcribiendo: {e}")
        return None
