# Sistema de Memoria

NOVA utiliza una arquitectura de memoria de cuatro capas. Cada capa sirve un requisito diferente de latencia y alcance.

---

## Capa 1 — Historial JSON Comprimido

**Archivo:** `historial.json`  
**Módulo:** `memory/memoria.py`  
**Latencia:** microsegundos

Ventana deslizante de los últimos 40 turnos, almacenada como JSON comprimido. Se inyecta directamente en el contexto del LLM en cada petición. Es la memoria de trabajo — lo que el modelo puede "ver" en la conversación actual.

Se sincroniza bidireccionalmente con el almacén Oracle al inicio y fin de cada sesión. Si el archivo local está obsoleto o ausente, se descarga desde Oracle.

---

## Capa 2 — Memoria Vectorial Semántica

**Motor:** ChromaDB + `paraphrase-multilingual-MiniLM-L12-v2`  
**Módulo:** `memory/memoria_profunda.py`  
**Latencia:** milisegundos

Almacena turnos de conversación y entradas de aprendizaje autónomo como embeddings. Se usa para:
- Recuperar conversaciones pasadas semánticamente relevantes antes de responder
- Inyección de contexto entre sesiones ("mencionaste esto la semana pasada")
- Almacenar hallazgos de la investigación autónoma en tiempo de inactividad

El modelo de embeddings se ejecuta localmente, sin conexión, sin llamadas a API.

---

## Capa 3 — Historial Completo SQLite

**Módulo:** `memory/memoria_profunda.py`  
**Latencia:** milisegundos

Historial completo y sin comprimir de todas las conversaciones. Nunca se trunca. Se usa para:
- Búsqueda de texto completo en todas las sesiones
- Registro de auditoría
- Consolidación nocturna y análisis de patrones (`consolidacion_nocturna.py`)
- Estadísticas de uso (`patrones_uso.py`)

---

## Capa 4 — Almacén Oracle (Fuente de Verdad)

**Endpoint:** `http://<oracle-ip>:9101`  
**Módulo:** `infrastructure/almacen.py`  
**Autenticación:** Bearer token vía `ALMACEN_TOKEN`

API REST que corre en el nodo Oracle. Actúa como fuente de verdad distribuida para el historial JSON. Ambos nodos (PC y Oracle) sincronizan hacia y desde este endpoint.

Esto garantiza que una sesión iniciada por voz en el PC y continuada por Telegram tenga el mismo estado de memoria.

**Endpoints:**
- `GET /historial` — obtener historial actual
- `POST /historial` — subir historial actualizado
- `GET /health` — comprobación de disponibilidad (usada por ambos watchdogs)

---

## Investigación Autónoma (Aprendizaje en Inactividad)

`orchestration/daemon_inactividad.py` monitoriza la actividad. Tras 30 minutos de silencio:

1. Deriva temas de investigación de los turnos de conversación recientes
2. Recurre a temas base (noticias de IA, actualizaciones de juegos)
3. Busca vía DuckDuckGo (`ddgs`)
4. Almacena los hallazgos como turnos de tipo `aprendizaje` en ChromaDB

Un informe nocturno resume lo aprendido y lo envía por Telegram a las 00:00.

---

## Flujo de Memoria

```
Nuevo turno de conversación
        │
        ▼
  Inyectar contexto (Capa 1 — historial JSON, Capa 2 — búsqueda semántica)
        │
        ▼
  Generar respuesta
        │
        ▼
  Guardar turno → Capa 1 (JSON) + Capa 2 (ChromaDB) + Capa 3 (SQLite)
        │
        ▼
  Sincronizar Capa 1 → Capa 4 (almacén Oracle)
```
