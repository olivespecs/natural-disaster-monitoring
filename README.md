# 🛰️ NASA EONET Real-Time AI Inference System

Real-time natural disaster monitoring powered by the **NASA EONET API**, with AI-driven risk analysis using **Gemini API** (automatic heuristic fallback if no key provided).

## ✨ Features

- 🌍 **Live World Map** — color-coded Leaflet.js markers updated in real time
- 🧠 **Two-Tier AI Engine** — Gemini 1.5 Flash for rich LLM analysis; heuristic engine as zero-config fallback
- ⚡ **Inference Queue** — Redis + RQ workers process every event asynchronously
- 📡 **WebSocket Push** — dashboard updates without polling
- 📊 **Live Analytics** — category distribution, risk level charts, queue monitor
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
  "inference_mode": "gemini-1.5-flash",
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
| `GEMINI_API_KEY` | _(blank)_ | Gemini API key — leave blank for heuristic mode |
| `GEMINI_MODEL` | `gemini-1.5-flash` | Gemini model name |

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
- **Gemini 1.5 Flash** — LLM analysis (optional)
- **NASA EONET v3** — live natural event data (free, no key)
- **Leaflet.js + CartoDB Dark** — interactive world map
- **Chart.js** — real-time analytics charts
- **Docker Compose** — one-command deployment
