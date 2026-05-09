# Infrastructure

## Two-Node Architecture

| Node | OS | Hardware | Role |
|---|---|---|---|
| Local PC | Windows 11 | NVIDIA GPU | Voice, UI, fast routing, offline fallback |
| Oracle Cloud | Ubuntu ARM | Always Free (4 OCPU, 24GB RAM) | DeepSeek-R1:14b, Hermes3:8b, almacén REST |

---

## Tailscale VPN

Both nodes are connected via Tailscale mesh VPN. All inter-node traffic flows through the private network:

```
PC  <PC_TAILSCALE_IP>  ←── Tailscale mesh ───→  Oracle  <ORACLE_TAILSCALE_IP>
```

Services exposed only on the Tailscale interface (never public internet):

| Service | Node | Port |
|---|---|---|
| Ollama (DeepSeek-R1, Hermes3) | Oracle | `<OLLAMA_PORT>` |
| REST Store | Oracle | `<ALMACEN_PORT>` |
| Local health endpoint | PC | `<PC_HEALTH_PORT>` |

The watchdog on Oracle (`watchdog_oracle.py`) probes `http://<PC_TAILSCALE_IP>:<PC_HEALTH_PORT>/health` to detect if the PC is online. The local watchdog (`watchdog.py`) does the reverse for Oracle services.

---

## Oracle Node Setup

### Ollama

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull models
ollama pull deepseek-r1:14b
ollama pull hermes3:8b
```

### Almacén REST (nova-almacen)

The almacén is a lightweight REST API (`infrastructure/almacen.py`) that stores the conversation historial as the distributed source of truth.

**Systemd service:** `/etc/systemd/system/nova-almacen.service`

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

### Telegram Bot (nova-telegram)

**Systemd service:** `/etc/systemd/system/nova-telegram.service`

Same structure as above, pointing to `interfaces/telegram_bot.py`.

---

## Watchdog System

Two independent watchdog layers:

### Oracle Watchdog (`infrastructure/watchdog_oracle.py`)

Runs as a cron job every minute on the Oracle node:

```cron
*/1 * * * * /usr/bin/python3 /home/ubuntu/nova/infrastructure/watchdog_oracle.py
```

Checks:
- `nova-almacen` and `nova-telegram` systemd service status
- PC reachability via Tailscale (`/health` endpoint)
- RAM, disk, CPU against configurable thresholds
- Error count in last 100 journal lines

Behavior:
- **Service down:** attempts automatic `systemctl restart`, sends Telegram alert
- **Resource threshold crossed:** Telegram alert on transition (low→high only, no spam)
- **Recovery:** Telegram notification when state returns to normal
- **State persistence:** `.watchdog_state.json` — only alerts on transitions, not every run

### Local Watchdog (`infrastructure/watchdog.py`)

Runs on the PC, monitors Oracle services from the other direction. Alerts via Telegram if Oracle becomes unreachable.

---

## Environment Configuration

All secrets and node addresses are managed via `.env`. See `.env.example` for a complete reference.

Key variables for infrastructure:

```env
OLLAMA_HOST_ORACLE=http://<ORACLE_TAILSCALE_IP>:<OLLAMA_PORT>
ALMACEN_URL=http://<ORACLE_TAILSCALE_IP>:<ALMACEN_PORT>
ALMACEN_TOKEN=your_sync_token
PC_TAILSCALE_IP=<PC_TAILSCALE_IP>
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ALLOWED_ID=your_telegram_id
```
