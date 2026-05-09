# Infraestructura

## Arquitectura de Dos Nodos

| Nodo | SO | Hardware | Rol |
|---|---|---|---|
| PC Local | Windows 11 | GPU NVIDIA | Voz, interfaz, enrutamiento rápido, fallback offline |
| Oracle Cloud | Ubuntu ARM | Always Free (4 OCPU, 24GB RAM) | DeepSeek-R1:14b, Hermes3:8b, almacén REST |

---

## VPN Tailscale

Ambos nodos están conectados mediante VPN mesh de Tailscale. Todo el tráfico entre nodos fluye por la red privada:

```
PC  100.68.163.22  ←── malla Tailscale ───→  Oracle  100.111.223.84
```

Servicios expuestos únicamente en la interfaz Tailscale (nunca internet público):

| Servicio | Nodo | Puerto |
|---|---|---|
| Ollama (DeepSeek-R1, Hermes3) | Oracle | 11434 |
| Almacén REST | Oracle | 9101 |
| Endpoint de salud local | PC | 5000 |

El watchdog en Oracle (`watchdog_oracle.py`) sondea `http://100.68.163.22:5000/health` para detectar si el PC está en línea. El watchdog local (`watchdog.py`) hace lo inverso para los servicios de Oracle.

---

## Configuración del Nodo Oracle

### Ollama

```bash
# Instalar Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Descargar modelos
ollama pull deepseek-r1:14b
ollama pull hermes3:8b
```

### Almacén REST (nova-almacen)

El almacén es una API REST ligera (`infrastructure/almacen.py`) que almacena el historial de conversaciones como fuente de verdad distribuida.

**Servicio systemd:** `/etc/systemd/system/nova-almacen.service`

```ini
[Unit]
Description=NOVA Almacén REST
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/ubuntu/nova/infrastructure/almacen.py
WorkingDirectory=/home/ubuntu/nova
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

### Bot de Telegram (nova-telegram)

**Servicio systemd:** `/etc/systemd/system/nova-telegram.service`

Misma estructura que el anterior, apuntando a `interfaces/telegram_bot.py`.

---

## Sistema de Watchdogs

Dos capas de watchdog independientes:

### Watchdog Oracle (`infrastructure/watchdog_oracle.py`)

Corre como tarea cron cada minuto en el nodo Oracle:

```cron
*/1 * * * * /usr/bin/python3 /home/ubuntu/nova/infrastructure/watchdog_oracle.py
```

Comprueba:
- Estado de los servicios systemd `nova-almacen` y `nova-telegram`
- Alcanzabilidad del PC vía Tailscale (endpoint `/health`)
- RAM, disco y CPU frente a umbrales configurables
- Conteo de errores en las últimas 100 líneas del journal

Comportamiento:
- **Servicio caído:** intenta `systemctl restart` automático, envía alerta por Telegram
- **Umbral de recursos superado:** alerta por Telegram en la transición (bajo→alto, sin spam)
- **Recuperación:** notificación por Telegram cuando el estado vuelve a la normalidad
- **Persistencia de estado:** `.watchdog_state.json` — solo alerta en transiciones, no en cada ejecución

### Watchdog Local (`infrastructure/watchdog.py`)

Corre en el PC, monitoriza los servicios de Oracle desde el otro lado. Envía alerta vía Telegram si Oracle deja de ser accesible.

---

## Configuración del Entorno

Todos los secretos y direcciones de nodos se gestionan mediante `.env`. Ver `.env.example` como referencia completa.

Variables clave para la infraestructura:

```env
OLLAMA_HOST_ORACLE=http://100.111.223.84:11434
ALMACEN_URL=http://100.111.223.84:9101
ALMACEN_TOKEN=tu_token_de_sincronizacion
PC_TAILSCALE_IP=100.68.163.22
TELEGRAM_BOT_TOKEN=tu_token_del_bot
TELEGRAM_ALLOWED_ID=tu_id_de_telegram
```
