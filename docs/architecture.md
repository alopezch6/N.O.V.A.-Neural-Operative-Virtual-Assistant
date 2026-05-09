# Architecture

## Project Structure

```
NOVA/
├── nova.py                  # Main loop — routing, orchestration, voice/text dispatch
├── config.py                # Global config — all secrets via dotenv
├── mono.py                  # Structured logger
│
├── agents/
│   ├── agente.py            # Self-extending agent — generates & caches Python capabilities
│   ├── orquestador.py       # Multi-step task orchestration
│   ├── explorador.py        # Self-knowledge — NOVA reads its own codebase on demand
│   ├── plugin_generator.py  # LLM-generated plugins, hot-reloaded every 30s
│   └── herramientas.py      # ReAct tool set (read/write files, run commands, web search)
│
├── interfaces/
│   ├── voz.py               # Wake word (Vosk) → STT (Whisper large-v3-turbo) → TTS pipeline
│   ├── telegram_bot.py      # Telegram interface — full feature parity with voice
│   ├── servidor.py          # Local HTTP server — state endpoint for the widget
│   ├── alexa_voz.py         # Alexa Remote Control TTS integration
│   ├── nova_widget_qt.py    # PySide6 frameless window — WebGL orb, audio reactive
│   └── boot_video.py        # Animated boot sequence
│
├── memory/
│   ├── memoria.py           # Primary memory — historial.json (40-turn compressed) + Oracle sync
│   ├── memoria_profunda.py  # ChromaDB semantic search + SQLite full history
│   ├── personas.py          # Per-user persona profiles
│   ├── gestor_tareas.py     # Persistent task queue
│   ├── patrones_uso.py      # Usage pattern analytics
│   ├── recordatorios.py     # Reminder scheduler
│   └── consolidacion_nocturna.py  # Nightly memory consolidation
│
├── orchestration/
│   ├── daemon_proactivo.py  # Proactive suggestions based on context
│   ├── daemon_inactividad.py # Idle-time autonomous research + nightly report
│   ├── tareas_autonomas.py  # Background task execution
│   └── reporte_diario.py    # Daily 06:45 system report via Telegram
│
├── utils/
│   ├── acciones.py          # Action dispatcher — OS commands, apps, system control
│   ├── internet.py          # Tavily search + connectivity probe
│   ├── apps.py              # App launcher (normalized names → executable)
│   ├── presencia.py         # Idle/active presence detection
│   ├── diagnostico.py       # Self-diagnostics — import health, service status
│   └── twitch_tracker.py    # Twitch live notifications
│
├── infrastructure/
│   ├── almacen.py           # Oracle REST almacén — source of truth for memory sync
│   ├── watchdog.py          # Local watchdog — monitors PC services via Tailscale
│   ├── watchdog_oracle.py   # Oracle cron watchdog — auto-restarts systemd services
│   ├── telemetria.py        # Metrics collector
│   └── deploy.py            # Remote deploy helper
│
└── plugins/                 # Hot-reload directory — LLM-generated capability modules
```

---

## Adaptive LLM Routing

All requests go through a classification step before reaching any model:

```
Request
   │
   ├── keyword match (KEYWORDS_COMPLEJO) ──→ DeepSeek-R1:14b on Oracle (reasoning, code)
   │
   ├── internet available ──→ Groq API (gpt-oss-120b → llama-3.3-70b fallback)
   │
   └── offline / Oracle unreachable ──→ Qwen2.5:3b local
```

The classification is based on a keyword list defined in `config.py`:

```python
KEYWORDS_COMPLEJO = [
    "explica", "analiza", "por qué", "cómo funciona", "código", "programa",
    "diferencia entre", "compara", "razona", "calcula", "escribe", "redacta",
    "traduce", "resume", "planifica", "diseña", "depura", "error", "bug"
]
```

Availability checks are cached (15s for local, 10s for internet) to avoid latency on every turn.

---

## Self-Extending Agent

`agents/agente.py` handles requests that fall outside `utils/acciones.py` known actions:

1. Detects if the request is executable as Python code
2. Generates a snippet via Groq
3. Asks user confirmation before executing
4. Runs in a controlled subprocess with a destructive-operation blacklist
5. Caches the capability in `capacidades.json` — no regeneration needed next time

**Blacklisted patterns (never executed):**
```python
r"\bos\.remove\b", r"\bshutil\.rmtree\b", r"rm\s+-[rRfF]",
r"del\s+/[sqSQ]", r"\bformat\b.*[A-Za-z]:\\", r"\bwinreg\b", r"HKEY_"
```

---

## Hot-reload Plugin System

The `plugins/` directory is scanned every 30 seconds. Any new `.py` file dropped in is imported without restarting NOVA. Plugins follow a standard interface and are registered automatically.

This allows LLM-generated capabilities to become available immediately and persist across sessions without code changes to core modules.

---

## Design Decisions

**Why two nodes instead of one?**
Oracle Cloud's Always Free tier provides a persistent ARM instance with enough RAM for 14B parameter models. Running DeepSeek-R1 there keeps the local PC free for real-time tasks (voice, UI). The cost is zero.

**Why Tailscale instead of public endpoints?**
The almacén and Ollama APIs are internal services. Tailscale provides a private mesh with zero firewall configuration and mutual TLS. No port forwarding, no public exposure.

**Why not a single monolithic memory?**
Different layers serve different latency requirements. The JSON historial injects context in microseconds. ChromaDB answers semantic queries in milliseconds. SQLite holds the full audit trail without size limits. Oracle almacén is the sync point across sessions and nodes.

**Why hot-reload plugins?**
Capability gaps become one-time events. A plugin generated during a session is available immediately and survives restarts. No code changes to core required.
