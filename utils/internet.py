"""
NOVA — Módulo de información en tiempo real
Router de fuentes por tipo de consulta. Prioridad:
  1. Tiempo        → wttr.in
  2. Fútbol/sport  → TheSportsDB (key pública "3") + Tavily como fallback
  3. Crypto        → CoinGecko (sin key)
  4. Twitch        → Twitch Helix API (opcional, config.py)
  5. Películas     → TMDB (opcional, config.py)
  6. Noticias      → Tavily news / ddgs.news() como fallback
  7. Wikipedia     → API REST española (sin key)
  8. Divisas       → frankfurter.app (sin key)
  9. Fallback      → Tavily (si hay key) → ddgs.text() con fecha actual
Todas las llamadas van envueltas en un hilo con timeout de 5s (mismo límite que antes).
Caché en memoria con TTL por tipo para no repetir llamadas innecesarias.
"""

import threading
import unicodedata
import requests
from datetime import datetime, timezone, timedelta
from urllib.parse import quote as url_quote
from ddgs import DDGS

_TZ_MADRID = timezone(timedelta(hours=2))  # CEST (verano); en invierno es +1

# ── Normalización ─────────────────────────────────────────────────────────────

def quitar_acentos(texto: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto.lower())
        if unicodedata.category(c) != 'Mn'
    )

# ── Caché en memoria ──────────────────────────────────────────────────────────
# Estructura: key → (valor, timestamp_float, ttl_segundos)

_cache: dict[str, tuple[str, float, int]] = {}

def _cache_get(key: str) -> str | None:
    entry = _cache.get(key)
    if not entry:
        return None
    valor, ts, ttl = entry
    if datetime.now().timestamp() - ts < ttl:
        return valor
    del _cache[key]
    return None

def _cache_set(key: str, valor: str, ttl: int = 300) -> None:
    _cache[key] = (valor, datetime.now().timestamp(), ttl)

# ── Keywords por handler ──────────────────────────────────────────────────────

_KW_TIEMPO = [
    "tiempo", "clima", "temperatura", "llueve", "pronostico", "pronostico",
    "hace frio", "hace calor", "va a llover", "va llover", "lluvia",
    "nieve", "nieva", "nublado", "despejado",
]

_KW_FUTBOL = [
    "partido", "partidos", "juega", "juegan", "futbol", "futbol", "liga",
    "jornada", "clasificacion", "resultado", "resultados", "gol", "goles",
    "marcador", "champions", "copa del rey", "segunda division",
    "primera division", "laliga", "real zaragoza", "zaragoza cf",
]

_KW_CRYPTO = [
    "bitcoin", "ethereum", "btc", "eth", "crypto", "criptomoneda",
    "dogecoin", "solana", "bnb", "usdt", "cripto", "criptodivisa",
    "precio del bitcoin", "precio de ethereum",
]

_KW_TWITCH = [
    "twitch", "en directo", "streamando", "streamer", "esta en directo",
    "esta streaming", "canal de twitch",
]

_KW_PELICULA = [
    "pelicula", "pelicula", "serie", "estreno", "actor", "actriz",
    "director", "oscars", "tmdb", "imdb", "netflix", "hbo", "disney",
]

_KW_NOTICIAS = [
    "noticias", "noticia", "actualidad", "ultimas noticias",
    "que ha pasado", "novedades", "lo ultimo", "novedad",
]

_KW_WIKI = [
    "que es ", "quien es ", "definicion", "historia de", "origen de",
    "significa ", "significado", "como funciona", "explica ",
]

_KW_CAMBIO = [
    "tipo de cambio", "cambio de divisa", "cambio euro", "cuanto vale el euro",
    "cambio de moneda", "divisa", "euro dolar", "euro libra",
]

# Frases locales — nunca buscar en internet
_NO_INTERNET = [
    "callate", "calla", "para ya", "detente", "silencio",
    "apaga", "cierra", "abre", "pon musica", "pausa", "siguiente",
    "sube el volumen", "baja el volumen", "silencia",
    "como te llamas", "quien eres", "que eres",
    "hola nova", "buenos dias", "buenas tardes", "buenas noches",
    "gracias", "de nada", "hasta luego", "adios",
    "reinicia", "estado oracle", "estado del bot", "log", "logs",
    "deploye", "deploy", "sincroniza",
]

# Prefijos que activan internet aunque no haya keyword de handler
_SI_INTERNET_PREFIJOS = [
    "que ", "que ", "quien ", "quien ", "como ", "como ",
    "cuando ", "cuando ", "donde ", "donde ", "cual ", "cual ",
    "cuanto ", "cuanto ", "cuanta ", "cuanta ", "cuales ", "cuales ",
    "por que ", "por que ", "para que ", "para que ",
    "existe ", "hay ", "es posible ", "se puede ",
    "dime ", "explica", "explicame ", "explicame ",
    "hablame ", "hablame ", "cuentame ", "cuentame ",
    "busca ", "buscar ", "investiga ", "encuentra ",
    "informacion ", "informacion ", "noticias ",
    "diferencia entre", "comparar ", "compara ",
    "opciones para", "alternativas a", "mejor forma de",
]

_ALL_KW = (
    _KW_TIEMPO + _KW_FUTBOL + _KW_CRYPTO + _KW_TWITCH
    + _KW_PELICULA + _KW_NOTICIAS + _KW_CAMBIO
)

_CIUDADES = [
    "zaragoza", "madrid", "barcelona", "valencia", "sevilla", "bilbao",
    "malaga", "alicante", "murcia", "palma", "las palmas", "granada",
    "vitoria", "pamplona", "santander", "logrono", "burgos", "salamanca",
    "valladolid", "toledo", "ciudad real", "albacete", "cuenca",
    "teruel", "huesca", "lleida", "girona", "tarragona",
]

# ── Utilidades ────────────────────────────────────────────────────────────────

def _kw(t: str, lista: list) -> bool:
    return any(k in t for k in lista)

def _extraer_ciudad(texto: str) -> str:
    t = quitar_acentos(texto)
    for ciudad in _CIUDADES:
        if ciudad in t:
            return ciudad.capitalize()
    return "Zaragoza"

# ── Handler 1: Tiempo (wttr.in) ───────────────────────────────────────────────

def _h_tiempo(query: str) -> str | None:
    ciudad = _extraer_ciudad(query)
    try:
        r = requests.get(
            f"https://wttr.in/{ciudad}?format=j1&lang=es", timeout=4
        )
        if r.status_code != 200:
            return None
        data = r.json()
        c = data['current_condition'][0]
        temp      = c['temp_C']
        sensacion = c['FeelsLikeC']
        humedad   = c['humidity']
        viento    = c['windspeedKmph']
        desc_list = c.get('lang_es') or c.get('weatherDesc', [{}])
        desc      = desc_list[0].get('value', '') if desc_list else ''
        manana    = data['weather'][0] if data.get('weather') else {}
        max_c     = manana.get('maxtempC', '?')
        min_c     = manana.get('mintempC', '?')
        return (
            f"Tiempo en {ciudad}: {desc}, {temp}°C (sensación {sensacion}°C), "
            f"humedad {humedad}%, viento {viento} km/h. "
            f"Hoy: máx {max_c}°C / mín {min_c}°C."
        )
    except Exception:
        return None

# ── Handler 2: Fútbol (TheSportsDB — key pública "3") ────────────────────────

_SPORTSDB = "https://www.thesportsdb.com/api/v1/json/3"

# IDs conocidos para búsqueda directa sin depender del buscador de TheSportsDB
_TEAM_IDS = {
    "real zaragoza": "133753",
    "zaragoza":      "133753",
    "real madrid":   "133604",
    "barcelona":     "133739",
    "atletico":      "133900",
    "atletico madrid": "133900",
    "sevilla":       "133683",
    "valencia":      "133682",
    "villarreal":    "133680",
    "betis":         "133695",
    "real betis":    "133695",
    "athletic":      "133612",
    "athletic bilbao": "133612",
    "real sociedad": "133667",
    "osasuna":       "133676",
    "girona":        "133666",
    "espanyol":      "133705",
    "getafe":        "133668",
    "alaves":        "133642",
    "celta":         "133593",
    "celta vigo":    "133593",
    "rayo vallecano": "133597",
    "mallorca":      "133669",
    "cadiz":         "133596",
    "granada":       "133601",
    "levante":       "133749",
    "elche":         "133659",
    "valladolid":    "133715",
    "real valladolid": "133715",
}

def _extraer_equipo(texto: str) -> str:
    t = texto.lower()
    for prefijo in [
        "cuando juega el ", "cuando juega la ", "cuando juega ",
        "a que hora juega el ", "a que hora juega la ", "a que hora juega ",
        "partido del ", "partido de ", "partidos del ", "partidos de ",
        "proximo partido del ", "proximo partido de ",
        "resultado del ", "resultado de ",
        "proximos partidos del ", "proximos partidos de ",
    ]:
        if prefijo in t:
            return texto[t.index(prefijo) + len(prefijo):].strip()
    return texto

def _hora_utc_a_madrid(fecha_str: str, hora_str: str) -> str:
    """Convierte hora UTC de TheSportsDB a hora de Madrid."""
    if not hora_str or hora_str == "00:00:00":
        return ""
    try:
        dt_str = f"{fecha_str}T{hora_str}"
        dt_utc = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
        dt_mad = dt_utc.astimezone(_TZ_MADRID)
        return dt_mad.strftime("%H:%M")
    except Exception:
        return hora_str[:5]

def _h_futbol(query: str) -> str | None:
    equipo_raw  = _extraer_equipo(query)
    if len(equipo_raw.strip()) < 3:
        equipo_raw = query

    equipo_norm = quitar_acentos(equipo_raw.lower()).strip()

    # Solo usar TheSportsDB si el equipo está en nuestra tabla de IDs verificados
    team_id   = None
    team_name = None
    for nombre, tid in _TEAM_IDS.items():
        if nombre in equipo_norm or equipo_norm in nombre:
            team_id   = tid
            team_name = nombre.title()
            break

    # TheSportsDB buscador de equipos es muy poco fiable para ligas españolas —
    # solo lo usamos si el equipo está en la tabla de IDs conocidos
    if not team_id:
        return None  # Tavily lo manejará en el router

    try:
        r = requests.get(
            f"{_SPORTSDB}/eventsnextteam.php",
            params={"id": team_id},
            timeout=4,
        )
        events = (r.json() or {}).get("events") or []

        if not events:
            return None

        hoy = datetime.now(_TZ_MADRID).date()
        lineas = [f"Próximos partidos de {team_name}:"]
        for ev in events[:5]:
            fecha    = ev.get("dateEvent", "?")
            hora_utc = ev.get("strTime") or ""
            hora_mad = _hora_utc_a_madrid(fecha, hora_utc)
            local    = ev.get("strHomeTeam", "?")
            visit    = ev.get("strAwayTeam", "?")
            liga     = ev.get("strLeague", "")
            hora_str = f" a las {hora_mad}h (Madrid)" if hora_mad else ""
            es_hoy   = " [HOY]" if fecha == str(hoy) else ""
            lineas.append(f"- {fecha}{es_hoy}{hora_str} — {local} vs {visit} ({liga})")
        return "\n".join(lineas)
    except Exception:
        return None

# ── Handler 3: Crypto (CoinGecko — sin key) ───────────────────────────────────

_CRYPTO_MAP = {
    "bitcoin": "bitcoin",   "btc": "bitcoin",
    "ethereum": "ethereum", "eth": "ethereum",
    "dogecoin": "dogecoin", "doge": "dogecoin",
    "solana": "solana",     "sol": "solana",
    "bnb": "binancecoin",
    "usdt": "tether",
    "xrp": "ripple",
    "cardano": "cardano",   "ada": "cardano",
}

def _h_crypto(query: str) -> str | None:
    t = query.lower()
    ids = list({v for k, v in _CRYPTO_MAP.items() if k in t})
    if not ids:
        return None  # Moneda no reconocida → DDG busca con la query original
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={
                "ids": ",".join(ids),
                "vs_currencies": "usd,eur",
                "include_24hr_change": "true",
            },
            timeout=3,
        )
        data = r.json()
        if not data:
            return None
        lineas = []
        for coin_id, prices in data.items():
            usd    = prices.get("usd", "?")
            eur    = prices.get("eur", "?")
            change = prices.get("usd_24h_change")
            cambio = f" ({change:+.1f}% 24h)" if change is not None else ""
            lineas.append(f"{coin_id.capitalize()}: ${usd:,} / {eur:,}€{cambio}")
        return "\n".join(lineas) if lineas else None
    except Exception:
        return None

# ── Handler 4: Twitch (Helix API — necesita key en config.py) ────────────────

_twitch_token_cache: dict = {"token": None, "expires": 0.0}

def _get_twitch_token(client_id: str, client_secret: str) -> str | None:
    now = datetime.now().timestamp()
    if _twitch_token_cache["token"] and now < _twitch_token_cache["expires"]:
        return _twitch_token_cache["token"]
    try:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=3,
        )
        data = r.json()
        token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        if token:
            _twitch_token_cache["token"]   = token
            _twitch_token_cache["expires"] = now + expires_in - 60
        return token
    except Exception:
        return None

def _extraer_streamer(texto: str) -> str:
    t = texto.lower()
    for prefijo in [
        "esta en directo ", "esta streamando ", "stream de ",
        "canal de ", "twitch de ", "directo de ",
    ]:
        if prefijo in t:
            return texto[t.index(prefijo) + len(prefijo):].strip().split()[0]
    palabras = [
        w for w in t.split()
        if w not in {"en", "directo", "twitch", "stream", "canal", "de", "el", "la", "esta", "streaming"}
    ]
    return palabras[-1] if palabras else ""

def _h_twitch(query: str, client_id: str, client_secret: str) -> str | None:
    if not client_id or not client_secret:
        return None
    streamer = _extraer_streamer(query)
    if len(streamer) < 2:
        return None
    token = _get_twitch_token(client_id, client_secret)
    if not token:
        return None
    try:
        r = requests.get(
            "https://api.twitch.tv/helix/streams",
            params={"user_login": streamer},
            headers={"Client-Id": client_id, "Authorization": f"Bearer {token}"},
            timeout=3,
        )
        streams = r.json().get("data", [])
        if streams:
            s = streams[0]
            return (
                f"{streamer} está en directo en Twitch ahora mismo. "
                f"Juego: {s.get('game_name', '?')}. "
                f"Título: {s.get('title', '?')[:80]}. "
                f"Viewers: {s.get('viewer_count', 0):,}."
            )
        return f"{streamer} no está en directo ahora en Twitch."
    except Exception:
        return None

# ── Handler 5: Películas/Series (TMDB — necesita key en config.py) ────────────

def _h_tmdb(query: str, api_key: str) -> str | None:
    if not api_key:
        return None
    t = query.lower()
    for prefijo in ["pelicula ", "serie ", "informacion de ", "busca ", "que es "]:
        if t.startswith(prefijo):
            query = query[len(prefijo):].strip()
            break
    try:
        r = requests.get(
            "https://api.themoviedb.org/3/search/multi",
            params={"api_key": api_key, "query": query, "language": "es-ES", "page": 1},
            timeout=3,
        )
        results = r.json().get("results", [])
        if not results:
            return None
        # Buscar el resultado más relevante (título más cercano a la query)
        query_norm = quitar_acentos(query).lower()
        item = next(
            (x for x in results[:3]
             if quitar_acentos(x.get("title") or x.get("name") or "").lower() in query_norm
             or query_norm in quitar_acentos(x.get("title") or x.get("name") or "").lower()),
            results[0]
        )
        tipo   = item.get("media_type", "")
        titulo = item.get("title") or item.get("name", "?")
        desc   = (item.get("overview") or "Sin descripción.")[:200]
        nota   = item.get("vote_average")
        nota_s = f" Nota: {nota:.1f}/10." if nota else ""
        if tipo == "movie":
            año = (item.get("release_date") or "?")[:4]
            return f"Película '{titulo}' ({año}).{nota_s} {desc}"
        elif tipo == "tv":
            año = (item.get("first_air_date") or "?")[:4]
            return f"Serie '{titulo}' (desde {año}).{nota_s} {desc}"
        return None
    except Exception:
        return None

# ── Handler 6: Noticias (ddgs.news) ──────────────────────────────────────────

def _h_noticias(query: str) -> str | None:
    try:
        with DDGS() as ddgs:
            res = list(ddgs.news(query, max_results=4, timelimit='w'))
            if res:
                return "\n".join(f"{r['title']}: {r['body']}" for r in res)
    except Exception:
        pass
    return None

# ── Handler 7: Wikipedia ES (sin key) ────────────────────────────────────────

def _h_wikipedia(query: str) -> str | None:
    t = query.lower()
    for prefijo in [
        "que es ", "quien es ", "definicion de ", "historia de ",
        "explica ", "explicame ", "como funciona ", "que significa ",
    ]:
        if t.startswith(prefijo):
            query = query[len(prefijo):].strip()
            break
    try:
        r = requests.get(
            "https://es.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 1},
            timeout=3,
        )
        search = r.json().get("query", {}).get("search", [])
        if not search:
            return None
        title = search[0]["title"]
        # Verificar que el título tiene alguna relación con la query (al menos una palabra clave)
        query_words = set(quitar_acentos(query).lower().split()) - {"el", "la", "los", "las", "de", "del", "un", "una"}
        title_norm = quitar_acentos(title).lower()
        if query_words and not any(w in title_norm for w in query_words):
            return None  # Resultado irrelevante → DDG
        r2 = requests.get(
            f"https://es.wikipedia.org/api/rest_v1/page/summary/{url_quote(title)}",
            timeout=3,
        )
        extract = r2.json().get("extract", "")
        return f"{title}: {extract[:400]}" if extract else None
    except Exception:
        return None

# ── Handler 8: Divisas (frankfurter.app — sin key) ───────────────────────────

def _h_cambio(_query: str) -> str | None:
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "EUR", "to": "USD,GBP,JPY,CHF,MXN"},
            timeout=3,
        )
        data  = r.json()
        rates = data.get("rates", {})
        if not rates:
            return None
        nombres = {"USD": "Dólar", "GBP": "Libra", "JPY": "Yen", "CHF": "Franco suizo", "MXN": "Peso MX"}
        fecha   = data.get("date", "")
        lineas  = [f"Tipos de cambio EUR ({fecha}):"]
        for moneda, valor in rates.items():
            lineas.append(f"  1€ = {valor:.4f} {nombres.get(moneda, moneda)}")
        return "\n".join(lineas)
    except Exception:
        return None

# ── Handler 9: Tavily (búsqueda inteligente para IA) ──────────────────────────

def _h_tavily(query: str) -> str | None:
    from config import TAVILY_API_KEY
    if not TAVILY_API_KEY:
        return None
    try:
        from tavily import TavilyClient
        hoy = datetime.now(_TZ_MADRID).strftime("%d de %B de %Y")
        client  = TavilyClient(api_key=TAVILY_API_KEY)
        result  = client.search(
            f"{query} {hoy}",
            max_results=4,
            search_depth="advanced",
        )
        partes = []
        for r in (result.get("results") or [])[:4]:
            titulo    = r.get("title", "")
            contenido = (r.get("content") or r.get("snippet") or "")[:400]
            if titulo or contenido:
                partes.append(f"{titulo}: {contenido}" if titulo else contenido)
        return "\n".join(partes) if partes else None
    except Exception:
        return None

# ── Handler 10: DuckDuckGo fallback ──────────────────────────────────────────

def _h_ddgs(query: str) -> str | None:
    hoy = datetime.now(_TZ_MADRID).strftime("%d de %B de %Y")
    try:
        with DDGS() as ddgs:
            res = list(ddgs.text(f"{query} {hoy}", max_results=4, timelimit='w'))
            if res:
                return "\n".join(f"{r['title']}: {r['body']}" for r in res)
    except Exception:
        pass
    return None

# ── Router ────────────────────────────────────────────────────────────────────

def _router(pregunta: str, container: dict) -> None:
    from config import TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET, TMDB_API_KEY

    cached = _cache_get(pregunta)
    if cached:
        container['info'] = cached
        return

    t = quitar_acentos(pregunta)
    resultado = None
    ttl = 300

    if _kw(t, _KW_TIEMPO):
        resultado = _h_tiempo(pregunta)
        ttl = 600

    elif _kw(t, _KW_FUTBOL):
        resultado = _h_futbol(pregunta)
        if not resultado:
            # TheSportsDB falló o no tiene datos — Tavily busca en sitios de deporte actualizados
            resultado = _h_tavily(pregunta)
        ttl = 900

    elif _kw(t, _KW_CRYPTO):
        resultado = _h_crypto(pregunta)
        ttl = 120

    elif _kw(t, _KW_TWITCH):
        resultado = _h_twitch(pregunta, TWITCH_CLIENT_ID, TWITCH_CLIENT_SECRET)
        ttl = 60

    elif _kw(t, _KW_PELICULA):
        resultado = _h_tmdb(pregunta, TMDB_API_KEY)
        ttl = 3600

    elif _kw(t, _KW_NOTICIAS):
        resultado = _h_tavily(pregunta) or _h_noticias(pregunta)
        ttl = 300

    elif _kw(t, _KW_WIKI):
        resultado = _h_wikipedia(pregunta)
        ttl = 3600

    elif _kw(t, _KW_CAMBIO):
        resultado = _h_cambio(pregunta)
        ttl = 1800

    # Fallback: Tavily (preciso y actual) → DuckDuckGo (último recurso)
    if not resultado:
        resultado = _h_tavily(pregunta) or _h_ddgs(pregunta)

    if resultado:
        _cache_set(pregunta, resultado, ttl)
        container['info'] = resultado

# ── API pública ───────────────────────────────────────────────────────────────

def necesita_internet(texto: str) -> bool:
    t = quitar_acentos(texto).strip()
    # Solo omitir internet para comandos locales explícitos
    return not any(t.startswith(k) or k in t for k in _NO_INTERNET)

def obtener_info_internet(pregunta: str) -> str | None:
    """Devuelve str con información relevante o None. Timeout global 5s."""
    container = {'info': None}
    hilo = threading.Thread(target=_router, args=(pregunta, container), daemon=True)
    hilo.start()
    hilo.join(timeout=5)
    return container['info']
