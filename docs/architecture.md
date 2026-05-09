# Arquitectura

## Estructura del Proyecto

```
NOVA/
├── nova.py                  # Bucle principal — enrutamiento, orquestación, voz/texto
├── config.py                # Configuración global — todos los secretos via dotenv
├── mono.py                  # Logger estructurado
│
├── agents/
│   ├── agente.py            # Agente autoextensible — genera y cachea capacidades Python
│   ├── orquestador.py       # Orquestación de tareas multi-paso
│   ├── explorador.py        # Autoconocimiento — NOVA lee su propio código bajo demanda
│   ├── plugin_generator.py  # Plugins generados por LLM, hot-reload cada 30s
│   └── herramientas.py      # Conjunto de herramientas ReAct (leer/escribir ficheros, ejecutar comandos, búsqueda web)
│
├── interfaces/
│   ├── voz.py               # Palabra de activación (Vosk) → STT (Whisper large-v3-turbo) → TTS
│   ├── telegram_bot.py      # Interfaz de Telegram — paridad completa con voz
│   ├── servidor.py          # Servidor HTTP local — endpoint de estado para el widget
│   ├── alexa_voz.py         # Integración TTS con Alexa Remote Control
│   ├── nova_widget_qt.py    # Ventana sin marco PySide6 — orbe WebGL, reactivo al audio
│   └── boot_video.py        # Secuencia de arranque animada
│
├── memory/
│   ├── memoria.py           # Memoria primaria — historial.json (40 turnos comprimidos) + sincronización Oracle
│   ├── memoria_profunda.py  # Búsqueda semántica ChromaDB + historial completo SQLite
│   ├── personas.py          # Perfiles de persona por usuario
│   ├── gestor_tareas.py     # Cola de tareas persistente
│   ├── patrones_uso.py      # Análisis de patrones de uso
│   ├── recordatorios.py     # Planificador de recordatorios
│   └── consolidacion_nocturna.py  # Consolidación nocturna de memoria
│
├── orchestration/
│   ├── daemon_proactivo.py  # Sugerencias proactivas basadas en contexto
│   ├── daemon_inactividad.py # Investigación autónoma en tiempo de inactividad + informe nocturno
│   ├── tareas_autonomas.py  # Ejecución de tareas en segundo plano
│   └── reporte_diario.py    # Informe diario a las 06:45 vía Telegram
│
├── utils/
│   ├── acciones.py          # Despachador de acciones — comandos del SO, apps, control del sistema
│   ├── internet.py          # Búsqueda Tavily + sonda de conectividad
│   ├── apps.py              # Lanzador de aplicaciones (nombres normalizados → ejecutable)
│   ├── presencia.py         # Detección de presencia activa/inactiva
│   ├── diagnostico.py       # Autodiagnóstico — salud de importaciones, estado de servicios
│   └── twitch_tracker.py    # Notificaciones de stream en Twitch
│
├── infrastructure/
│   ├── almacen.py           # Almacén REST en Oracle — fuente de verdad para sincronización de memoria
│   ├── watchdog.py          # Watchdog local — monitoriza servicios del PC vía Tailscale
│   ├── watchdog_oracle.py   # Watchdog cron en Oracle — reinicia servicios systemd automáticamente
│   ├── telemetria.py        # Recolector de métricas
│   └── deploy.py            # Ayudante de despliegue remoto
│
└── plugins/                 # Directorio hot-reload — módulos de capacidades generados por LLM
```

---

## Enrutamiento Adaptativo de LLMs

Todas las peticiones pasan por una etapa de clasificación antes de llegar a cualquier modelo:

```
Petición
   │
   ├── coincidencia de palabras clave (KEYWORDS_COMPLEJO) ──→ DeepSeek-R1:14b en Oracle (razonamiento, código)
   │
   ├── internet disponible ──→ Groq API (gpt-oss-120b → llama-3.3-70b como fallback)
   │
   └── sin internet / Oracle no accesible ──→ Qwen2.5:3b local
```

La clasificación se basa en una lista de palabras clave definida en `config.py`:

```python
KEYWORDS_COMPLEJO = [
    "explica", "analiza", "por qué", "cómo funciona", "código", "programa",
    "diferencia entre", "compara", "razona", "calcula", "escribe", "redacta",
    "traduce", "resume", "planifica", "diseña", "depura", "error", "bug"
]
```

Las comprobaciones de disponibilidad se cachean (15s para local, 10s para internet) para evitar latencia en cada turno.

---

## Agente Autoextensible

`agents/agente.py` gestiona peticiones que quedan fuera de las acciones conocidas en `utils/acciones.py`:

1. Detecta si la petición es ejecutable como código Python
2. Genera un snippet vía Groq
3. Pide confirmación al usuario antes de ejecutar
4. Ejecuta en un subproceso controlado con lista negra de operaciones destructivas
5. Cachea la capacidad en `capacidades.json` — no necesita regeneración la próxima vez

**Patrones en lista negra (nunca se ejecutan):**
```python
r"\bos\.remove\b", r"\bshutil\.rmtree\b", r"rm\s+-[rRfF]",
r"del\s+/[sqSQ]", r"\bformat\b.*[A-Za-z]:\\", r"\bwinreg\b", r"HKEY_"
```

---

## Sistema de Plugins Hot-reload

El directorio `plugins/` se escanea cada 30 segundos. Cualquier archivo `.py` nuevo que se deposite ahí se importa sin reiniciar NOVA. Los plugins siguen una interfaz estándar y se registran automáticamente.

Esto permite que las capacidades generadas por LLM estén disponibles de inmediato y persistan entre sesiones sin modificar los módulos del núcleo.

---

## Decisiones de Diseño

**¿Por qué dos nodos en lugar de uno?**
El nivel Always Free de Oracle Cloud proporciona una instancia ARM persistente con suficiente RAM para modelos de 14B parámetros. Ejecutar DeepSeek-R1 allí deja el PC local libre para tareas en tiempo real (voz, interfaz). El coste es cero.

**¿Por qué Tailscale en lugar de endpoints públicos?**
El almacén y las APIs de Ollama son servicios internos. Tailscale proporciona una malla privada sin configuración de firewall y con TLS mutuo. Sin reenvío de puertos, sin exposición pública.

**¿Por qué no una memoria monolítica?**
Las distintas capas sirven distintos requisitos de latencia. El historial JSON inyecta contexto en microsegundos. ChromaDB responde consultas semánticas en milisegundos. SQLite mantiene el historial completo sin límite de tamaño. El almacén Oracle es el punto de sincronización entre sesiones y nodos.

**¿Por qué plugins hot-reload?**
Las lagunas de capacidad se convierten en eventos únicos. Un plugin generado durante una sesión está disponible de inmediato y sobrevive a los reinicios. No se requieren cambios en el núcleo.
