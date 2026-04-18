# 🛰️ NASA EONET Real-Time AI Inference System

Real-time natural disaster monitoring powered by the **NASA EONET API**, with AI-driven risk analysis using **Gemini API** (automatic heuristic fallback if no key provided).

## ✨ Features

- 🌍 **Live World Map** — color-coded Leaflet.js markers updated in real time
- 🧠 **Two-Tier AI Engine** — configured Gemini model for rich LLM analysis; heuristic engine as zero-config fallback
- ⚡ **Inference Queue** — Redis + RQ workers process every event asynchronously
- 📦 **Batched Inference** — workers process configurable event batches per invocation
- 📡 **WebSocket Push** — dashboard updates without polling
- 📊 **Live Analytics** — category distribution, risk level charts, queue monitor
- 📈 **Prometheus Metrics** — `/metrics` exports latency, queue depth, throughput, and GPU utilization
- ☸️ **Kubernetes Manifests** — Deployments, Services, GPU worker scheduling, and queue-depth autoscaling
- 🔥 Covers: Wildfires, Storms, Volcanoes, Floods, Earthquakes, Landslides & more

## 🚀 Quickstart

### 1. Clone & configure

```bash
cp .env.example .env
# (Optional) Add your Gemini API key for LLM analysis:
# GEMINI_API_KEY=your_key_here
```

Get a free Gemini key at: https://aistudio.google.com/app/apikey

### 2. Start everything

```bash
docker-compose up --build
```

Three services will start:
| Service | Container | Port |
|---------|-----------|------|
| FastAPI API + Dashboard | `eonet_api` | `8000` |
| Redis | `eonet_redis` | `6379` |
| RQ Worker | `eonet_worker` | — |

### 3. Open the dashboard

```
http://localhost:8000
```

Within ~60 seconds, NASA EONET events will appear on the map and feed as the first poll completes.

---

## 🔌 API Reference

### Events
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/events` | List all enriched events |
| `GET` | `/api/v1/events/{id}` | Single event with full AI analysis |
| `GET` | `/api/v1/events/geojson` | GeoJSON FeatureCollection for Leaflet |

### Queue
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/queue/stats` | Queue depth, workers, throughput |
| `GET` | `/api/v1/queue/jobs` | Recent job list |
| `GET` | `/api/v1/queue/dead-letter` | Jobs that exhausted retries |
| `POST` | `/api/v1/queue/retry` | Retry all failed jobs |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/analytics/summary` | Category counts, risk distribution, avg severity |
| `GET` | `/api/v1/analytics/hotspots` | Top 10 highest-severity locations |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness probe |
| `GET` | `/ready` | Readiness probe (checks Redis) |

### Docs
- Swagger UI: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

---

## 🧠 AI Inference Output

Each event is analysed through a two-tier pipeline:

```
GEMINI_API_KEY set?
  YES  →  Gemini 1.5 Flash (rich narrative + contextual recommendations)
   NO  →  Heuristic engine (deterministic, domain-expert rules, instant)
 FAIL  →  Heuristic engine (automatic fallback — zero downtime)
```

**Example output:**
```json
{
  "event_id": "EONET_5678",
  "category": "Wildfires",
  "severity_score": 82.5,
  "risk_level": "HIGH",
  "trend": "ESCALATING",
  "estimated_impact": "Regional (50k–500k potentially affected)",
  "impact_narrative": "The wildfire has expanded rapidly across three counties...",
  "recommendations": [
    "Activate mandatory evacuation for zones A-C",
    "Deploy aerial tankers to eastern flank",
    "Pre-position emergency shelters in Riverside County"
  ],
  "inference_mode": "gemma-4-26b-a4b-it",
  "confidence": 0.91
}
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `EONET_API_URL` | `https://eonet.gsfc.nasa.gov/api/v3` | NASA EONET base URL |
| `POLL_INTERVAL_SECONDS` | `60` | How often to fetch new events |
| `MAX_EVENTS_PER_POLL` | `50` | Max events per EONET request |
| `EVENT_DAYS_WINDOW` | `7` | Look back N days for open events |
| `EONET_TIMEOUT_SECONDS` | `30` | HTTP timeout for EONET requests |
| `EONET_MAX_RETRIES` | `3` | Retry attempts for transient EONET failures (429/5xx/network) |
| `EONET_RETRY_BACKOFF_SECONDS` | `1.2` | Linear backoff base in seconds between EONET retries |
| `JOB_MAX_RETRIES` | `2` | Maximum RQ retries before dead-lettering a job |
| `MAX_QUEUE_DEPTH` | `500` | Max queued jobs before poller defers new event batches |
| `INFERENCE_BATCH_SIZE` | `8` | Number of events processed per worker task invocation |
| `GEMINI_API_KEY` | _(blank)_ | Gemini API key — leave blank for heuristic mode |
| `GEMINI_MODEL` | `gemma-4-26b-a4b-it` | Gemini model name |

### Prometheus metrics endpoint

- `GET /metrics`
- Exported series:
  - `inference_latency_seconds`
  - `queue_depth_total`
  - `events_processed_total`
  - `gpu_utilization_gauge`

### Kubernetes deployment

Use manifests in `k8s/` for production-style deployment and autoscaling:

```bash
kubectl apply -f k8s/
```

---

## 🏗️ Architecture

```
NASA EONET API
      │
      ▼ (every 60s)
  EONET Poller  ──► Redis Seen-IDs (dedup)
      │
      ▼ (new events only)
  Redis Queue (eonet-inference)
      │
      ▼
  RQ Worker(s)
      ├── Heuristic pre-scoring (always)
      └── Gemini API enrichment (if key present, else heuristic)
      │
      ▼
  Redis (enriched event store, 24h TTL)
      │
      ├──► WebSocket → Dashboard (real-time push)
      └──► REST API  → Dashboard (polling fallback)
```

## 📦 Tech Stack

- **FastAPI** — REST API + WebSocket server
- **Redis + RQ** — async inference queue
- **Gemini model** — LLM analysis (optional)
- **NASA EONET v3** — live natural event data (free, no key)
- **Leaflet.js + CartoDB Dark** — interactive world map
- **Chart.js** — real-time analytics charts
- **Docker Compose** — one-command deployment

## 🛡️ Reliability Defaults

- EONET ingestion now retries transient API/network errors with backoff.
- Event deduplication uses atomic Redis set insert (`SADD`) to avoid race conditions.
- Redis event scans use cursor-based iteration (`SCAN`) to reduce blocking pressure versus `KEYS`.
- Failed jobs are retried by RQ and then moved to a dead-letter store after retries are exhausted.
- Queue throughput is measured from real completed-event timestamps in Redis (`events_per_minute`).
- Gemini output is constrained to JSON, with normalized trend values and stable 3-item recommendations.
