# Memory System

NOVA uses a four-layer memory architecture. Each layer serves a different latency and scope requirement.

---

## Layer 1 — Compressed JSON Historial

**File:** `historial.json`  
**Module:** `memory/memoria.py`  
**Latency:** microseconds

Rolling window of the last 40 turns, stored as compressed JSON. Injected directly into the LLM context on every request. This is the working memory — what the model can "see" in the current conversation.

Synced bidirectionally with the Oracle almacén at session start and end. If the local file is stale or absent, it pulls from Oracle.

---

## Layer 2 — Semantic Vector Memory

**Engine:** ChromaDB + `paraphrase-multilingual-MiniLM-L12-v2`  
**Module:** `memory/memoria_profunda.py`  
**Latency:** milliseconds

Stores conversation turns and autonomous learning entries as embeddings. Used for:
- Retrieving semantically relevant past conversations before responding
- Cross-session context injection ("you mentioned this last week")
- Storing findings from idle-time autonomous research

The embedding model runs locally, offline, without API calls.

---

## Layer 3 — SQLite Full History

**Module:** `memory/memoria_profunda.py`  
**Latency:** milliseconds

Complete, uncompressed conversation history. Never truncated. Used for:
- Full-text search across all sessions
- Audit trail
- Nightly consolidation and pattern analysis (`consolidacion_nocturna.py`)
- Usage statistics (`patrones_uso.py`)

---

## Layer 4 — Oracle Almacén (Source of Truth)

**Endpoint:** `http://<oracle-ip>:9101`  
**Module:** `infrastructure/almacen.py`  
**Auth:** Bearer token via `ALMACEN_TOKEN`

REST API running on the Oracle node. Acts as the distributed source of truth for the JSON historial. Both nodes (PC and Oracle) sync to and from this endpoint.

This ensures that a session started via voice on the PC and continued via Telegram has the same memory state.

**Endpoints:**
- `GET /historial` — fetch current historial
- `POST /historial` — push updated historial
- `GET /health` — liveness check (used by both watchdogs)

---

## Autonomous Research (Idle-time Learning)

`orchestration/daemon_inactividad.py` monitors activity. After 30 minutes of silence:

1. Derives research topics from recent conversation turns
2. Falls back to baseline topics (AI news, game updates)
3. Searches via DuckDuckGo (`ddgs`)
4. Stores findings as `tipo=aprendizaje` turns in ChromaDB

A nightly report summarizes what was learned and sends it via Telegram at 00:00.

---

## Memory Flow

```
New conversation turn
        │
        ▼
  Inject context (Layer 1 — JSON historial, Layer 2 — semantic search)
        │
        ▼
  Generate response
        │
        ▼
  Save turn → Layer 1 (JSON) + Layer 2 (ChromaDB) + Layer 3 (SQLite)
        │
        ▼
  Sync Layer 1 → Layer 4 (Oracle almacén)
```
