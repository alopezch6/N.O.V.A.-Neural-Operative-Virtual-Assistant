"""
NOVA — Reporte Diario Matutino
Ejecutado cada día a las 06:45 (Europe/Madrid) por el JobQueue de telegram_bot.py
"""

import html as _html_lib
import io
import json
import re
import threading
import wave
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import psutil
import requests
from ddgs import DDGS

from config import (
    TELEGRAM_ALLOWED_ID,
    MEMORIA_PATH, HISTORIAL_PATH,
    PC_TAILSCALE_IP,
)

_HISTORIAL_TG = Path(HISTORIAL_PATH).parent / "historial_telegram.json"
_SEP = "\n─────────────────────\n"

_RSS_HERALDO_ZGZ = "https://www.heraldo.es/rss/"
_NOTICIAS_CACHE: list[dict] = []
_TRAFICO_RESULTADOS: list[dict] = []


def get_noticias_cache() -> list[dict]:
    return _NOTICIAS_CACHE


def _strip_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = _html_lib.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

# ── Noticias ──────────────────────────────────────────────────────────────────

def _parse_rss_regex(content: bytes) -> list[dict]:
    """Parser RSS tolerante basado en regex para feeds con caracteres inválidos."""
    text = content.decode('utf-8', errors='replace')
    items = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
    result = []
    for item in items:
        titulo = _strip_html(re.search(r'<title>(.*?)</title>', item, re.DOTALL).group(1) if re.search(r'<title>(.*?)</title>', item, re.DOTALL) else '')
        link_m = re.search(r'<link>(.*?)</link>', item, re.DOTALL) or re.search(r'<guid[^>]*>(.*?)</guid>', item, re.DOTALL)
        url = link_m.group(1).strip() if link_m else ''
        desc_m = re.search(r'<description>(.*?)</description>', item, re.DOTALL)
        resumen = _strip_html(desc_m.group(1) if desc_m else '')
        if titulo:
            result.append({"titulo": titulo, "url": url, "resumen": resumen})
    return result


_KW_DEPORTE = (
    "real zaragoza", "zaragoza cf", "la romareda", "deportivo aragón",
    "deporte", "deportes", "fútbol", "futbol", "baloncesto", "basket",
    "atletismo", "ciclismo", "tenis", "pádel", "padel", "natación",
    "liga", "primera", "segunda", "copa del rey", "champions",
)

def _prioridad_noticia(titulo: str) -> int:
    t = titulo.lower()
    if "real zaragoza" in t or "la romareda" in t:
        return 0
    if any(k in t for k in ("deporte", "deportes", "fútbol", "futbol", "liga", "baloncesto")):
        return 1
    return 2


def _fetch_rss(url: str) -> list[dict]:
    r = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (compatible; NOVA/1.0)"})
    try:
        root = ET.fromstring(r.content)
        items_xml = root.findall('.//item')
        parsed = []
        for item in items_xml:
            titulo = _strip_html(item.findtext('title', ''))
            url_item = (item.findtext('link') or item.findtext('guid') or '').strip()
            resumen = _strip_html(item.findtext('description', ''))
            pub_date = (item.findtext('pubDate') or '').strip()
            if titulo:
                parsed.append({"titulo": titulo, "url": url_item, "resumen": resumen, "pubDate": pub_date})
        return parsed
    except ET.ParseError:
        return _parse_rss_regex(r.content)


def _es_de_hoy(pub_date: str) -> bool:
    """Comprueba si un pubDate RSS es de hoy (hora Madrid)."""
    if not pub_date:
        return False
    try:
        from email.utils import parsedate_to_datetime
        import pytz
        dt = parsedate_to_datetime(pub_date)
        madrid = pytz.timezone("Europe/Madrid")
        hoy = datetime.now(madrid).date()
        return dt.astimezone(madrid).date() == hoy
    except Exception:
        return False


_RSS_REAL_ZARAGOZA = "https://www.heraldo.es/rss/deportes/futbol/real-zaragoza/"

def _seccion_noticias() -> str:
    global _NOTICIAS_CACHE
    _NOTICIAS_CACHE = []
    try:
        # (noticia, prioridad_base): real zaragoza hoy → 0, deportes → 1, general → 2
        pool: list[tuple[dict, int]] = [(n, 2) for n in _fetch_rss(_RSS_HERALDO_ZGZ)]
        urls_vistos = {n['url'] for n, _ in pool}

        try:
            deportes = _fetch_rss("https://www.heraldo.es/rss/deportes/")
            nuevos = [n for n in deportes if n['url'] not in urls_vistos]
            pool += [(n, 1) for n in nuevos]
            urls_vistos.update(n['url'] for n in nuevos)
        except Exception:
            pass

        try:
            zaragoza = _fetch_rss(_RSS_REAL_ZARAGOZA)
            for n in zaragoza:
                if n['url'] in urls_vistos:
                    continue
                if _es_de_hoy(n.get('pubDate', '')):
                    pool.append((n, 0))
                    urls_vistos.add(n['url'])
        except Exception:
            pass

        pool.sort(key=lambda item: item[1])
        top5 = [n for n, _ in pool[:5]]

        lines = ["📰 *NOTICIAS — HERALDO DE ARAGÓN*", ""]
        for i, n in enumerate(top5, 1):
            _NOTICIAS_CACHE.append(n)
            lines.append(f"{i}. [{n['titulo']}]({n['url']})")
        if _NOTICIAS_CACHE:
            lines.append("")
            lines.append("_/noticia <número> para leer completa_")
        return "\n".join(lines)
    except Exception as e:
        return f"📰 *NOTICIAS — HERALDO DE ARAGÓN*\n\n_(Error: {e})_"


# ── Tráfico y Tranvía ──────────────────────────────────────────────────────────

_KW_INCIDENCIA = (
    "corte", "cortado", "cortada", "incidencia", "interrupción", "interrumpido",
    "interrumpida", "afectado", "afectada", "cortes", "colapso", "obras",
    "accidente", "manifestación", "manifestacion", "huelga", "desvío", "desvio",
)

def _limpiar_titular_voz(titulo: str) -> str:
    """Elimina sufijos tipo ' | Fuente' o ' - Fuente' del título para TTS."""
    for sep in (' | ', ' - '):
        if sep in titulo:
            titulo = titulo[:titulo.index(sep)]
    return titulo.strip().rstrip('.')


def _trafico_para_voz() -> str:
    """Frase natural sobre el estado del tráfico y tranvía para el TTS. Vacío si no hay datos de hoy."""
    if not _TRAFICO_RESULTADOS:
        return "Calles despejadas. El tráfico y el tranvía circulan con total normalidad hoy."

    # Buscar incidencias específicas (descartar contextos condicionales/hipotéticos)
    for r in _TRAFICO_RESULTADOS:
        body = r.get('body', '').strip()
        titulo = r.get('title', '').strip()
        if not body or len(body) < 40:
            continue
        texto_completo = (titulo + " " + body).lower()
        kw_reales = [
            kw for kw in _KW_INCIDENCIA
            if kw in texto_completo and not re.search(rf'si\b.{{0,40}}{kw}', texto_completo)
        ]
        if not kw_reales:
            continue
        primera_frase = body.split('.')[0].strip()
        if len(primera_frase) > 30:
            return f"Atención con el tráfico: {primera_frase.rstrip('.')}."
        titular_limpio = _limpiar_titular_voz(titulo)
        if titular_limpio:
            return f"Atención con el tráfico: {titular_limpio}."

    return "Calles despejadas. El tráfico y el tranvía circulan con total normalidad hoy."


def _seccion_trafico() -> str:
    global _TRAFICO_RESULTADOS
    _TRAFICO_RESULTADOS = []
    try:
        hoy = datetime.now().date()

        with DDGS() as ddgs:
            candidatos = list(ddgs.news(
                "tranvía zaragoza incidencia corte tráfico",
                region="es-es",
                max_results=10,
            ))

        # Solo noticias de hoy
        recientes = []
        for r in candidatos:
            fecha_str = r.get('date', '')
            try:
                fecha_r = datetime.fromisoformat(fecha_str.replace('Z', '+00:00')).date()
                if fecha_r == hoy:
                    recientes.append(r)
            except Exception:
                pass

        # Adaptar formato al esperado por _trafico_para_voz (title + body)
        _TRAFICO_RESULTADOS = [
            {"title": r.get('title', ''), "body": r.get('body', '')}
            for r in recientes
        ]

        if not recientes:
            return "🚇 *TRÁFICO Y TRANVÍA*\n\n✅ Vía libre. Sin cortes ni incidencias en tráfico o tranvía para hoy."
        lines = ["🚇 *TRÁFICO Y TRANVÍA*", ""]
        for res in recientes[:3]:
            titulo = res.get('title', '').strip()
            body = res.get('body', '').strip()
            short = (body[:110] + '…') if len(body) > 110 else body
            lines.append(f"• *{titulo}*")
            if short:
                lines.append(f"  {short}")
        return "\n".join(lines)
    except Exception as e:
        return f"🚇 *TRÁFICO Y TRANVÍA*\n\n_(Error: {e})_"


# ── Nodos ──────────────────────────────────────────────────────────────────────

def _oracle_stats() -> str:
    cpu  = round(psutil.cpu_percent(interval=0.5))
    ram  = round(psutil.virtual_memory().percent)
    disk = psutil.disk_usage('/')
    free_gb  = round(disk.free  / 1e9, 1)
    total_gb = round(disk.total / 1e9, 1)

    temp = None
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            temp = round(int(f.read().strip()) / 1000, 1)
    except Exception:
        pass

    boot   = datetime.fromtimestamp(psutil.boot_time())
    uptime = datetime.now() - boot
    uptime_str = f"{uptime.days}d {uptime.seconds // 3600}h"

    temp_str = f" · {temp}°C" if temp else ""
    return (
        f"🟢 *Oracle Cloud* — Online\n"
        f"  CPU: {cpu}% · RAM: {ram}%{temp_str}\n"
        f"  Disco: {free_gb} GB libres / {total_gb} GB\n"
        f"  Uptime: {uptime_str}"
    )

def _pc_stats() -> str:
    if not PC_TAILSCALE_IP:
        return "💻 *PC Local* — IP Tailscale no configurada"
    try:
        r = requests.get(f"http://{PC_TAILSCALE_IP}:5000/estado", timeout=3)
        d = r.json()
        pc = d.get('pc', {})
        cpu  = pc.get('cpu')
        ram  = pc.get('ram')
        temp = pc.get('temp')
        temp_str = f" · {temp}°C" if temp else ""
        cpu_str  = f"\n  CPU: {cpu}% · RAM: {ram}%{temp_str}" if cpu is not None else ""
        return f"🟢 *PC Local* — Online{cpu_str}"
    except Exception:
        return "🔴 *PC Local* — Offline"

def _seccion_nodos() -> str:
    return f"🖥️ *ESTADO DE NODOS*\n\n{_oracle_stats()}\n\n{_pc_stats()}"


# ── Clima ──────────────────────────────────────────────────────────────────────

_WMO_LARGO = {
    0: "☀️ Despejado", 1: "🌤️ Despejado", 2: "⛅ Parcialmente nublado",
    3: "☁️ Nublado", 45: "🌫️ Niebla", 48: "🌫️ Niebla con escarcha",
    51: "🌦️ Llovizna ligera", 53: "🌦️ Llovizna", 55: "🌧️ Llovizna intensa",
    61: "🌧️ Lluvia ligera", 63: "🌧️ Lluvia", 65: "🌧️ Lluvia intensa",
    71: "❄️ Nieve ligera", 73: "❄️ Nieve", 75: "❄️ Nieve intensa",
    80: "🌦️ Chubascos ligeros", 81: "🌧️ Chubascos", 82: "⛈️ Chubascos fuertes",
    95: "⛈️ Tormenta", 99: "⛈️ Tormenta con granizo",
}

_WMO_ICON = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    71: "❄️", 73: "❄️", 75: "❄️",
    80: "🌦️", 81: "🌧️", 82: "⛈️",
    95: "⛈️", 99: "⛈️",
}

_HORAS_REPORTE = [7, 9, 12, 15, 18, 21]

def _seccion_clima() -> str:
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=41.65&longitude=-0.88"
            "&current=temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code"
            "&hourly=temperature_2m,weather_code,precipitation_probability"
            "&daily=temperature_2m_max,temperature_2m_min"
            "&timezone=Europe%2FMadrid&forecast_days=1",
            timeout=6,
        )
        d   = r.json()
        cur = d["current"]
        day = d["daily"]
        hourly = d["hourly"]

        temp  = round(cur["temperature_2m"])
        hum   = cur["relative_humidity_2m"]
        wind  = round(cur["wind_speed_10m"])
        code  = cur["weather_code"]
        t_max = round(day["temperature_2m_max"][0])
        t_min = round(day["temperature_2m_min"][0])
        cond  = _WMO_LARGO.get(code, f"Código {code}")

        # Franja horaria: horas del día de hoy (índices 0-23)
        franjas = []
        for h in _HORAS_REPORTE:
            t  = round(hourly["temperature_2m"][h])
            wc = hourly["weather_code"][h]
            pp = hourly["precipitation_probability"][h]
            icon = _WMO_ICON.get(wc, "🌡️")
            lluvia = f" {pp}%" if pp >= 20 else ""
            franjas.append(f"{h:02d}h {icon}{t}°{lluvia}")

        horario = " | ".join(franjas)

        return (
            f"🌤️ *CLIMA — ZARAGOZA*\n\n"
            f"{cond} · {temp}°C  |  Máx {t_max}° · Mín {t_min}°\n"
            f"Humedad: {hum}% · Viento: {wind} km/h\n\n"
            f"`{horario}`"
        )
    except Exception as e:
        return f"🌤️ *CLIMA — ZARAGOZA*\n\n_(Error: {e})_"


# ── Seguridad ──────────────────────────────────────────────────────────────────

def _seccion_seguridad() -> str:
    log_paths   = ['/var/log/auth.log', '/var/log/secure']
    cutoff      = datetime.now() - timedelta(hours=24)
    current_year = datetime.now().year

    failed_ips     = []
    accepted_lines = []

    for path in log_paths:
        try:
            with open(path, 'r', errors='replace') as f:
                for line in f:
                    m = re.match(r'^(\w{3}\s+\d+\s+\d+:\d+:\d+)', line)
                    if m:
                        try:
                            ts = datetime.strptime(
                                f"{current_year} {m.group(1)}", "%Y %b %d %H:%M:%S"
                            )
                            if ts < cutoff:
                                continue
                        except ValueError:
                            pass

                    if 'Failed password' in line or 'Invalid user' in line:
                        ip_m = re.search(r'from (\d+\.\d+\.\d+\.\d+)', line)
                        if ip_m:
                            failed_ips.append(ip_m.group(1))
                    elif 'Accepted' in line:
                        user_m = re.search(r'Accepted \S+ for (\S+) from (\S+)', line)
                        if user_m:
                            accepted_lines.append((user_m.group(1), user_m.group(2)))
        except Exception:
            continue

    lines = ["🔒 *AUDITORÍA DE SEGURIDAD*", ""]

    if not failed_ips:
        lines.append("✅ Sin intentos SSH fallidos en las últimas 24h")
    else:
        counter = Counter(failed_ips)
        total   = len(failed_ips)
        unique  = len(counter)
        lines.append(f"⚠️ *{total} intentos SSH fallidos* de {unique} IPs distintas")
        lines.append("Top atacantes:")
        for ip, count in counter.most_common(5):
            lines.append(f"  `{ip}` → {count} intentos")

    unexpected = [(u, ip) for u, ip in accepted_lines if u not in ('ubuntu', 'root')]
    if unexpected:
        lines.append("\n🚨 *Accesos exitosos no habituales:*")
        for user, ip in unexpected:
            lines.append(f"  `{user}` desde `{ip}`")
    elif accepted_lines:
        lines.append("✅ Solo accesos de usuario habitual")
    else:
        lines.append("✅ Sin accesos exitosos (normal con Tailscale)")

    return "\n".join(lines)


# ── Estado NOVA ────────────────────────────────────────────────────────────────

def _seccion_nova() -> str:
    mem_count = hist_voz = hist_tg = 0

    try:
        mem = json.loads(Path(MEMORIA_PATH).read_text(encoding='utf-8'))
        mem_count = len(mem) if isinstance(mem, list) else len(mem.get('memorias', []))
    except Exception:
        pass

    try:
        hist = json.loads(Path(HISTORIAL_PATH).read_text(encoding='utf-8'))
        hist_voz = len(hist) if isinstance(hist, list) else 0
    except Exception:
        pass

    try:
        tg = json.loads(_HISTORIAL_TG.read_text(encoding='utf-8'))
        hist_tg = len(tg)
    except Exception:
        pass

    return (
        f"🧠 *ESTADO DE NOVA*\n\n"
        f"Memorias: {mem_count}\n"
        f"Historial voz: {hist_voz} msgs · Telegram: {hist_tg} msgs"
    )


# ── Versión de voz ────────────────────────────────────────────────────────────

def _clima_para_voz() -> str:
    """Genera una descripción natural del clima para TTS."""
    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=41.65&longitude=-0.88"
            "&current=temperature_2m,weather_code"
            "&hourly=temperature_2m,weather_code,precipitation_probability"
            "&daily=temperature_2m_max,temperature_2m_min"
            "&timezone=Europe%2FMadrid&forecast_days=1",
            timeout=6,
        )
        d   = r.json()
        cur = d["current"]
        day = d["daily"]
        hourly = d["hourly"]

        temp  = round(cur["temperature_2m"])
        code  = cur["weather_code"]
        t_max = round(day["temperature_2m_max"][0])
        t_min = round(day["temperature_2m_min"][0])
        cond  = _WMO_LARGO.get(code, "tiempo variable").replace("☀️","").replace("🌤️","").replace("⛅","").replace("☁️","").replace("🌧️","").replace("⛈️","").replace("❄️","").replace("🌫️","").replace("🌦️","").strip()

        # Detectar si va a llover en algún momento del día
        lluvia_horas = [
            f"las {h:02d}h" for h in range(24)
            if hourly["precipitation_probability"][h] >= 40
        ]
        lluvia_str = ""
        if lluvia_horas:
            lluvia_str = f" Hay probabilidad de lluvia hacia {lluvia_horas[0]}."

        return (
            f"El tiempo en Zaragoza: {cond.lower()}, {temp} grados ahora mismo. "
            f"Máxima de {t_max} y mínima de {t_min}.{lluvia_str}"
        )
    except Exception:
        return "No se han podido obtener datos del tiempo."


def _seguridad_para_voz() -> str:
    log_paths = ['/var/log/auth.log', '/var/log/secure']
    cutoff    = datetime.now() - timedelta(hours=24)
    current_year = datetime.now().year
    failed_ips = []

    for path in log_paths:
        try:
            with open(path, 'r', errors='replace') as f:
                for line in f:
                    m = re.match(r'^(\w{3}\s+\d+\s+\d+:\d+:\d+)', line)
                    if m:
                        try:
                            ts = datetime.strptime(f"{current_year} {m.group(1)}", "%Y %b %d %H:%M:%S")
                            if ts < cutoff:
                                continue
                        except ValueError:
                            pass
                    if 'Failed password' in line or 'Invalid user' in line:
                        ip_m = re.search(r'from (\d+\.\d+\.\d+\.\d+)', line)
                        if ip_m:
                            failed_ips.append(ip_m.group(1))
        except Exception:
            continue

    if not failed_ips:
        return "Sin incidencias de seguridad en las últimas 24 horas."
    unique = len(set(failed_ips))
    return (
        f"Seguridad: {len(failed_ips)} intentos de acceso SSH bloqueados "
        f"desde {unique} direcciones distintas. Ningún acceso no autorizado."
    )


def _tareas_para_voz() -> str:
    """Menciona tareas pendientes de Alex si las hay."""
    try:
        from gestor_tareas import obtener_pendientes, obtener_tareas_para_seguimiento
        seguimiento = obtener_tareas_para_seguimiento()
        if not seguimiento:
            return ""
        # Mencionar solo la más antigua con seguimiento pendiente
        t = seguimiento[0]
        from gestor_tareas import registrar_seguimiento
        registrar_seguimiento(t["id"])
        desc = t["descripcion"][:80]
        return f"Recordatorio: tenías pendiente {desc}."
    except Exception:
        return ""


def generar_texto_voz() -> str:
    """Versión concisa del reporte, optimizada para TTS."""
    now   = datetime.now()
    dias  = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    fecha = f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]}"

    # Nodos
    cpu_o = round(psutil.cpu_percent(interval=0.3))
    ram_o = round(psutil.virtual_memory().percent)
    pc_online = False
    try:
        requests.get(f"http://{PC_TAILSCALE_IP}:5000/estado", timeout=2)
        pc_online = True
    except Exception:
        pass
    pc_str  = "el PC local está operativo" if pc_online else "el PC local está apagado"
    nodos   = f"Oracle en línea al {cpu_o}% de CPU y {ram_o}% de RAM. {pc_str.capitalize()}."

    clima     = _clima_para_voz()
    seguridad = _seguridad_para_voz()
    trafico   = _trafico_para_voz()
    tareas    = _tareas_para_voz()

    partes = [f"Buenos días, Señor. Hoy es {fecha}.", nodos, clima, seguridad, trafico]
    if tareas:
        partes.append(tareas)
    return " ".join(p for p in partes if p) + " Que tenga un buen día."


# ── Kokoro local (lazy-load, corre en Oracle) ──────────────────────────────────
_kokoro_pipeline = None
_kokoro_lock     = threading.Lock()

def _get_kokoro():
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        with _kokoro_lock:
            if _kokoro_pipeline is None:
                import os
                import torch
                from kokoro import KPipeline
                os.environ.setdefault("KOKORO_DEVICE", "cpu")
                _kokoro_pipeline = KPipeline(
                    lang_code="e", repo_id="hexgrad/Kokoro-82M",
                    device=torch.device("cpu"),
                )
    return _kokoro_pipeline

_TTS_REPLACEMENTS = {
    "tranvía": "tranbia",
    "Tranvía": "Tranbia",
    "tráfico": "trafico",
    "Tráfico": "Trafico",
    "línea": "linea",
    "Línea": "Linea",
    "málaga": "malaga",
    "Málaga": "Malaga",
}

def _normalizar_tts(texto: str) -> str:
    for original, sustitucion in _TTS_REPLACEMENTS.items():
        texto = texto.replace(original, sustitucion)
    return texto

def obtener_audio_texto(texto_voz: str, voice: str = "ef_dora", speed: float = 0.88) -> bytes | None:
    """Genera audio WAV con Kokoro a partir de un texto arbitrario."""
    try:
        pipeline = _get_kokoro()
        texto_voz = _normalizar_tts(texto_voz)
        # Procesar frase a frase para que un fallo no corte el audio entero
        frases = [f.strip() for f in re.split(r'(?<=[.!?])\s+', texto_voz) if f.strip()]
        chunks = []
        for frase in frases:
            try:
                for _, _, audio in pipeline(frase, voice=voice, speed=speed):
                    if audio is not None and len(audio) > 0:
                        chunks.append(audio)
            except Exception as e:
                print(f"[TTS] frase omitida por error ({e}): {frase[:60]}")
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
        return buf.read()
    except Exception as e:
        print(f"[REPORTE] TTS error: {e}")
        return None

def obtener_audio_reporte() -> bytes | None:
    """Genera audio WAV con Kokoro en Oracle a partir del texto de voz."""
    return obtener_audio_texto(generar_texto_voz())


# ── Ensamblado ─────────────────────────────────────────────────────────────────

def generar_reporte() -> str:
    now   = datetime.now()
    dias  = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    fecha = f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}"

    def _seccion_tareas() -> str:
        try:
            from gestor_tareas import obtener_pendientes
            pendientes = obtener_pendientes()
            if not pendientes:
                return ""
            lines = ["📋 *TAREAS PENDIENTES*", ""]
            for t in pendientes[:5]:
                creada = datetime.fromisoformat(t["creada"])
                dias_p = (datetime.now() - creada).days
                antig = f"hace {dias_p}d" if dias_p > 0 else "hoy"
                lines.append(f"• {t['descripcion'][:70]} _({antig})_")
            return "\n".join(lines)
        except Exception:
            return ""

    seccion_tareas = _seccion_tareas()
    secciones = [
        f"🌅 *Buenos días, Señor.*\n`{fecha} · 07:00`",
        _seccion_nodos(),
        _seccion_clima(),
        _seccion_seguridad(),
        _seccion_nova(),
        _seccion_trafico(),
        _seccion_noticias(),
    ]
    if seccion_tareas:
        secciones.insert(4, seccion_tareas)
    cuerpo = _SEP.join(s for s in secciones if s)
    return cuerpo + f"\n{_SEP.strip()}\n_Sistema nominal. Que tenga un buen día._"


async def enviar_reporte(context) -> None:
    """Callback para el JobQueue de python-telegram-bot."""
    try:
        texto = generar_reporte()
    except Exception as e:
        await context.bot.send_message(
            chat_id=TELEGRAM_ALLOWED_ID,
            text=f"⚠️ Error generando el reporte matutino: {e}",
        )
        return

    # Leer el reporte en el Echo
    try:
        from alexa_voz import inicializar_alexa, alexa_habla
        texto_voz = generar_texto_voz()
        if inicializar_alexa():
            alexa_habla(texto_voz)
    except Exception as e:
        print(f"[REPORTE] Echo speak fallido: {e}")

    # Mandar siempre nota de voz Kokoro por Telegram
    try:
        audio = obtener_audio_reporte()
        if audio:
            import io as _io
            await context.bot.send_voice(
                chat_id=TELEGRAM_ALLOWED_ID,
                voice=_io.BytesIO(audio),
            )
    except Exception as e:
        print(f"[REPORTE] Audio Kokoro fallido: {e}")

    # Enviar siempre el texto completo
    partes = []
    limite = 4000
    while texto:
        if len(texto) <= limite:
            partes.append(texto)
            break
        corte = texto.rfind('\n', 0, limite)
        if corte <= 0:
            corte = limite
        partes.append(texto[:corte].strip())
        texto = texto[corte:].strip()

    for parte in partes:
        await context.bot.send_message(
            chat_id=TELEGRAM_ALLOWED_ID,
            text=parte,
            parse_mode="Markdown",
        )
