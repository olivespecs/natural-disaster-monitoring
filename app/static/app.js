/**
 * NASA EONET Real-Time AI Monitor — Dashboard Logic
 * WebSocket | Leaflet Map | Chart.js | Event Feed | Modal
 */

'use strict';

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  events: {},           // id → enriched event
  features: [],         // current GeoJSON features from /api/v1/events/geojson
  activeFilter: 'all',
  activeRisk: null,
  includeSimulated: false,
  pollInterval: 60,
  catChart: null,
  riskChart: null,
  markers: {},          // event id → Leaflet marker
};

// ── DOM refs ──────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);


function apiUrl(path, params = {}) {
  const url = new URL(path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null) {
      url.searchParams.set(key, String(value));
    }
  });
  if (state.includeSimulated) {
    url.searchParams.set('include_simulated', 'true');
  }
  return `${url.pathname}${url.search}`;
}

// ── Clock ─────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  $('header-clock').textContent =
    now.toUTCString().replace(/.*(\d{2}:\d{2}:\d{2}).*/, '$1') + ' UTC';
}
setInterval(updateClock, 1000);
updateClock();

// ── Leaflet Map ───────────────────────────────────────────────────────────
const map = L.map('map', {
  center: [20, 0],
  zoom: 2,
  zoomControl: true,
  preferCanvas: true,
});

L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
  attribution: '© <a href="https://www.openstreetmap.org/copyright">OSM</a> contributors © <a href="https://carto.com/">CARTO</a>',
  subdomains: 'abcd',
  maxZoom: 19,
}).addTo(map);

function riskColor(risk) {
  return { CRITICAL: '#ff1744', HIGH: '#ff6d00', MEDIUM: '#ffd600', LOW: '#00e676' }[risk] || '#64748b';
}
function riskSize(risk) {
  return { CRITICAL: 18, HIGH: 14, MEDIUM: 11, LOW: 9 }[risk] || 10;
}

function makeMarker(feature) {
  const p = feature.properties;
  const sz = riskSize(p.risk_level);
  const cls = `ev-marker marker-${p.risk_level}${p.risk_level === 'CRITICAL' ? ' marker-pulse' : ''}`;
  const icon = L.divIcon({
    className: '',
    html: `<div class="${cls}" style="width:${sz}px;height:${sz}px"></div>`,
    iconSize: [sz, sz],
    iconAnchor: [sz / 2, sz / 2],
  });

  const coords = feature.geometry.coordinates;
  const marker = L.marker([coords[1], coords[0]], { icon })
    .on('click', () => showModal(p));

  marker.bindTooltip(
    `<strong>${p.title}</strong><br>${p.category} · ${p.risk_level}`,
    { direction: 'top', offset: [0, -6], className: '' }
  );
  return marker;
}

function renderMarkers(features) {
  // Remove stale markers
  const newIds = new Set(features.map(f => f.properties.id));
  for (const [id, m] of Object.entries(state.markers)) {
    if (!newIds.has(id)) { m.remove(); delete state.markers[id]; }
  }
  // Add/update markers
  for (const f of features) {
    const id = f.properties.id;
    if (state.markers[id]) { state.markers[id].remove(); }
    const m = makeMarker(f);
    m.addTo(map);
    state.markers[id] = m;
  }
}

// ── Filters ───────────────────────────────────────────────────────────────
function setFilter(cat) {
  state.activeFilter = cat;
  state.activeRisk = null;
  document.querySelectorAll('.filter-btn').forEach(b => {
    b.classList.toggle('active', b.id === `filter-${cat}` || (cat === 'all' && b.id === 'filter-all'));
    b.setAttribute('aria-pressed', b.classList.contains('active'));
  });
  applyFilters();
}

function setRiskFilter(risk) {
  state.activeFilter = 'all';
  state.activeRisk = state.activeRisk === risk ? null : risk;
  document.querySelectorAll('.filter-btn').forEach(b => {
    b.classList.remove('active');
    b.setAttribute('aria-pressed', 'false');
  });
  if (state.activeRisk) {
    $('filter-critical').classList.add('active');
    $('filter-critical').setAttribute('aria-pressed', 'true');
  } else {
    $('filter-all').classList.add('active');
    $('filter-all').setAttribute('aria-pressed', 'true');
  }
  applyFilters();
}

function applyFilters() {
  let filtered = state.features;
  if (state.activeFilter !== 'all') {
    filtered = filtered.filter(f => f.properties.category_id === state.activeFilter);
  }
  if (state.activeRisk) {
    filtered = filtered.filter(f => f.properties.risk_level === state.activeRisk);
  }
  renderMarkers(filtered);
}

// ── Modal ─────────────────────────────────────────────────────────────────
function showModal(p) {
  const recs = (p.recommendations || [])
    .map(r => `<li>${r}</li>`)
    .join('');

  const scoreW = Math.min(100, Math.max(0, p.severity_score || 0));
  const modeLabel = p.inference_mode === 'heuristic' ? 'Heuristic AI' : `Gemini ${p.inference_mode || ''}`;
  const link = p.link ? `<a class="modal-link" href="${p.link}" target="_blank" rel="noopener">🔗 View source →</a>` : '';
  
  // Pipeline path badges
  const isPipelineGemini = p.pipeline_path === 'TIER_2_GEMINI';
  const pipelineBadge = isPipelineGemini
    ? `<span class="modal-badge pipeline-gemini">✅ Tier 2 Executed</span>`
    : `<span class="modal-badge pipeline-fallback">⚠️ Tier 2 Unavailable</span>`;
  const pipelineExplanation = isPipelineGemini
    ? 'Gemini AI Enrichment executed. Heuristic bypassed.'
    : 'Zero-downtime Tier 1 Heuristic Fallback triggered.';

  $('modal-body').innerHTML = `
    <div class="modal-event-title">${p.title || 'Unknown Event'}</div>
    <div class="modal-badges">
      <span class="modal-badge risk ${p.risk_level}">${p.risk_level || 'UNKNOWN'} RISK</span>
      <span class="modal-badge trend">↗ ${p.trend || 'STABLE'}</span>
      <span class="modal-badge mode">🧠 ${modeLabel}</span>
    </div>
    
    <div class="modal-section">
      <div class="modal-section-title">🔄 Pipeline & Fallback</div>
      <div class="modal-badges" style="margin-bottom: 8px;">${pipelineBadge}</div>
      <div class="modal-narrative" style="font-size: 12px; color: var(--subtle); line-height: 1.5;">${pipelineExplanation}</div>
    </div>

    ${p.impact_narrative ? `
    <div class="modal-section">
      <div class="modal-section-title">📋 Impact Assessment</div>
      <div class="modal-narrative">${p.impact_narrative}</div>
    </div>` : ''}

    ${recs ? `
    <div class="modal-section">
      <div class="modal-section-title">⚡ Emergency Recommendations</div>
      <ul class="modal-recs">${recs}</ul>
    </div>` : ''}

    <div class="modal-section">
      <div class="modal-section-title">📊 Severity Score — ${scoreW}/100</div>
      <div class="modal-score-bar">
        <div class="modal-score-fill" style="width:${scoreW}%"></div>
      </div>
    </div>

    <div class="modal-meta">
      <div class="meta-item">
        <div class="meta-label">Category</div>
        <div class="meta-value">${p.category || '—'}</div>
      </div>
      <div class="meta-item">
        <div class="meta-label">Est. Impact</div>
        <div class="meta-value">${p.estimated_impact || '—'}</div>
      </div>
      <div class="meta-item">
        <div class="meta-label">Date</div>
        <div class="meta-value">${p.date ? p.date.slice(0,10) : '—'}</div>
      </div>
      <div class="meta-item">
        <div class="meta-label">Confidence</div>
        <div class="meta-value">${p.confidence ? (p.confidence * 100).toFixed(0) + '%' : '—'}</div>
      </div>
    </div>
    ${link}
  `;

  $('modal-backdrop').style.display = 'flex';
}

function closeModal() {
  $('modal-backdrop').style.display = 'none';
}

function showArchitectureModal() {
  const backdrop = document.getElementById('architecture-modal-backdrop');
  if (!backdrop) {
    console.warn('Architecture modal backdrop not found');
    return;
  }
  
  const body = document.getElementById('architecture-modal-body');
  if (!body) {
    console.warn('Architecture modal body not found');
    return;
  }
  
  body.innerHTML = `
    <div class="arch-section">
      <h3>Event Processing Pipeline</h3>
      <div class="arch-diagram">EONET API (NASA)
        ↓
  Polling Client (Celery Task)
        ↓
  Event Normalization &amp; Enrichment
        ↓
  Gemini AI Analysis (Fallback: Heuristics)
        ↓
  Risk Scoring &amp; Rules Engine
        ↓
  WebSocket Broadcast (Real-time Updates)
      </div>
    </div>
    
    <div class="arch-section">
      <h3>Queue Management</h3>
      <ul class="arch-list">
        <li><strong>Celery</strong> — Distributed task queue for async processing</li>
        <li><strong>Redis</strong> — Broker &amp; result backend for task coordination</li>
        <li><strong>Worker Pool</strong> — 4+ processes for concurrent event handling</li>
        <li><strong>Backpressure Control</strong> — Dynamic queue throttling when overloaded</li>
      </ul>
    </div>
    
    <div class="arch-section">
      <h3>Inference Engine</h3>
      <ul class="arch-list">
        <li><strong>Gemini API</strong> — Primary LLM for contextual risk assessment</li>
        <li><strong>Fallback Rules</strong> — Deterministic scoring when API is unavailable</li>
        <li><strong>Geo Utils</strong> — Proximity &amp; impact radius calculations</li>
        <li><strong>Caching</strong> — Reduces redundant API calls &amp; latency</li>
      </ul>
    </div>
    
    <div class="arch-section">
      <h3>Real-time Monitoring</h3>
      <ul class="arch-list">
        <li><strong>WebSocket</strong> — Instant event &amp; metric updates to clients</li>
        <li><strong>Metrics Endpoint</strong> — Queue depth, latency, worker health</li>
        <li><strong>Health Checks</strong> — Redis, API connectivity, task queue status</li>
      </ul>
    </div>
    
    <div class="modal-footer">
      <button class="modal-button secondary" onclick="closeArchitectureModal()" type="button">Close</button>
    </div>
  `;
  
  backdrop.style.display = 'flex';
}

function closeArchitectureModal() {
  const backdrop = document.getElementById('architecture-modal-backdrop');
  if (backdrop) {
    backdrop.style.display = 'none';
  }
}

function updateQueueMetrics(data) {
  const metricsDiv = $('queue-metrics');
  if (!metricsDiv) return;
  
  // Extract latency values from backend (field names: avg_latency_ms, last_latency_ms, queued)
  const hasAvgLatency = typeof data.avg_latency_ms === 'number' && Number.isFinite(data.avg_latency_ms);
  const avgLatency = hasAvgLatency ? data.avg_latency_ms.toFixed(0) : '-';
  const hasLastLatency = data.last_latency_ms !== undefined && data.last_latency_ms !== null;
  const lastLatency = hasLastLatency ? data.last_latency_ms : '-';
  const queueSize = data.queued || 0;
  const eventsPerMin = typeof data.events_per_minute === 'number' && Number.isFinite(data.events_per_minute)
    ? data.events_per_minute.toFixed(1)
    : '0.0';
  
  metricsDiv.innerHTML = `
    <div class="metric-item">
      <strong>Avg Latency</strong>
      <span class="metric-value">${avgLatency} ms</span>
    </div>
    <div class="metric-item">
      <strong>Last Job</strong>
      <span class="metric-value">${lastLatency} ms</span>
    </div>
    <div class="metric-item">
      <strong>Queue Depth</strong>
      <span class="metric-value">${queueSize}</span>
    </div>
    <div class="metric-item">
      <strong>E/min</strong>
      <span class="metric-value">${eventsPerMin}</span>
    </div>
  `;
}

function checkBackpressure(metrics) {
  const banner = document.querySelector('.backpressure-banner');
  if (!banner) return;
  
  // Determine if backpressure is active
  const queueSize = metrics.queued || 0;
  const avgLatency = metrics.avg_latency_ms || 0;
  
  // Thresholds for backpressure
  const QUEUE_THRESHOLD = 50;
  const LATENCY_THRESHOLD_MS = 500;
  
  const isBackpressured = queueSize > QUEUE_THRESHOLD || avgLatency > LATENCY_THRESHOLD_MS;
  
  if (isBackpressured) {
    banner.classList.add('active');
    banner.innerHTML = `
      <span class="backpressure-icon">⚠️</span>
      <span>Backpressure: Queue=${queueSize}, Latency=${avgLatency.toFixed(0)}ms</span>
    `;
  } else {
    banner.classList.remove('active');
  }
}

function simulateSpike() {
  // Simulate a spike by creating multiple dummy tasks
  console.log('Simulating task spike...');
  const spikeCount = 10;
  
  // Send request to backend to inject test tasks
  fetch(`/api/v1/queue/simulate-spike?count=${spikeCount}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  })
    .then(r => r.json())
    .then(data => {
      state.includeSimulated = true;
      console.log('Spike simulation started:', data);
      fetchGeoJSON();
      fetchEvents();
      fetchSummary();
      alert(`✓ Spike simulation started (${data.count || spikeCount} events). New spike events are prioritized in queue.`);
    })
    .catch(err => console.error('Spike simulation failed:', err));
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

// ── Charts ────────────────────────────────────────────────────────────────
const CHART_COLORS = [
  '#ff6384', '#36a2eb', '#ffce56', '#4bc0c0',
  '#9966ff', '#ff9f40', '#00d4ff', '#00e676', '#ff1744', '#7c3aed',
];

function initCharts() {
  const base = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
  };

  state.catChart = new Chart($('cat-chart'), {
    type: 'doughnut',
    data: { labels: [], datasets: [{ data: [], backgroundColor: CHART_COLORS, borderWidth: 0 }] },
    options: {
      ...base,
      cutout: '65%',
      plugins: {
        ...base.plugins,
        legend: {
          display: true, position: 'bottom',
          labels: { color: '#64748b', font: { size: 9 }, boxWidth: 10, padding: 6 },
        },
      },
    },
  });

  state.riskChart = new Chart($('risk-chart'), {
    type: 'bar',
    data: {
      labels: ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'],
      datasets: [{
        data: [0, 0, 0, 0],
        backgroundColor: ['#00e676', '#ffd600', '#ff6d00', '#ff1744'],
        borderRadius: 4, borderWidth: 0,
      }],
    },
    options: {
      ...base,
      scales: {
        x: { grid: { display: false }, ticks: { color: '#64748b', font: { size: 9 } } },
        y: { grid: { color: 'rgba(255,255,255,0.04)' }, ticks: { color: '#64748b', font: { size: 9 } } },
      },
    },
  });
}

function updateCharts(summary) {
  if (!summary) return;

  // Category donut
  const cats = summary.by_category || {};
  state.catChart.data.labels = Object.keys(cats);
  state.catChart.data.datasets[0].data = Object.values(cats);
  state.catChart.update('none');

  // Risk bar
  const risks = summary.by_risk_level || {};
  state.riskChart.data.datasets[0].data = [
    risks.LOW || 0, risks.MEDIUM || 0, risks.HIGH || 0, risks.CRITICAL || 0,
  ];
  state.riskChart.update('none');
}

// ── Stats counters ────────────────────────────────────────────────────────
function updateStats(events) {
  const total = events.length;
  const completed = events.filter(e => e.status === 'completed');
  const critical = completed.filter(e => e.inference?.risk_level === 'CRITICAL').length;
  const high = completed.filter(e => e.inference?.risk_level === 'HIGH').length;

  $('s-total').textContent = total;
  $('s-critical').textContent = critical;
  $('s-high').textContent = high;
  $('s-processed').textContent = completed.length;

  // Inference badge
  const modes = completed.map(e => e.inference?.inference_mode).filter(Boolean);
  const geminiCount = modes.filter(m => m !== 'heuristic').length;
  if (geminiCount > 0) {
    $('inference-icon').textContent = '✨';
    $('inference-label').textContent = `Gemini AI (${geminiCount}/${completed.length})`;
    $('inference-badge').style.borderColor = 'rgba(124,58,237,0.4)';
    $('inference-badge').style.color = '#a78bfa';
  } else if (completed.length > 0) {
    $('inference-icon').textContent = '🧠';
    $('inference-label').textContent = 'Heuristic Engine';
    $('inference-badge').style.borderColor = '';
    $('inference-badge').style.color = '';
  } else {
    $('inference-icon').textContent = '🧠';
    $('inference-label').textContent = 'Awaiting data…';
  }
}

// ── Event feed ────────────────────────────────────────────────────────────
function renderFeed(events) {
  const completed = events
    .filter(e => e.status === 'completed' && e.inference)
    .sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));

  $('feed-badge').textContent = `${completed.length} event${completed.length !== 1 ? 's' : ''}`;

  const feed = $('event-feed');
  if (completed.length === 0) {
    feed.innerHTML = `
      <div class="feed-empty" id="feed-empty">
        <div class="spinner"></div>
        <p>Waiting for NASA EONET data…</p>
      </div>`;
    return;
  }

  const oldScroll = feed.scrollLeft;

  const renderItems = completed.slice(0, 30);

  feed.innerHTML = renderItems.map(e => {
    const inf = e.inference;
    const risk = inf.risk_level || 'MEDIUM';
    const mode = inf.inference_mode === 'heuristic' ? 'heuristic' : 'gemini';
    const modeLabel = mode === 'heuristic' ? 'heuristic' : 'Gemini';
    return `
      <div class="event-card risk-${risk}" onclick='showModalFromFeed(${JSON.stringify(e.event?.id || "")})'
           role="button" tabindex="0" aria-label="${e.event?.title || 'Event'}">
        <div class="card-top">
          <span class="card-title">${e.event?.title || 'Unknown Event'}</span>
          <span class="risk-pill ${risk}">${risk}</span>
        </div>
        <div class="card-meta">
          <span class="card-cat">${inf.category || ''}</span>
          <span class="card-score">⚡ ${inf.severity_score}/100</span>
          <span class="mode-chip ${mode}">${modeLabel}</span>
        </div>
      </div>`;
  }).join('');

  if (oldScroll > 0) {
    feed.scrollLeft = oldScroll;
  }
}

function showModalFromFeed(eventId) {
  const f = state.features.find(f => f.properties.id === eventId);
  if (f) showModal(f.properties);
}

// ── Queue monitor ─────────────────────────────────────────────────────────
function updateQueue(data) {
  $('q-queued').textContent   = data.queued  ?? 0;
  $('q-started').textContent  = data.started ?? 0;
  $('q-finished').textContent = data.finished ?? 0;
  $('q-failed').textContent   = data.failed  ?? 0;
  $('worker-label').textContent = `${data.workers ?? 0} worker${data.workers !== 1 ? 's' : ''}`;

  if (data.last_poll_at) {
    const d = new Date(data.last_poll_at);
    $('last-poll').textContent = d.toLocaleTimeString();
  }
  if (data.next_poll_in != null) {
    $('next-poll').textContent = `${data.next_poll_in}s`;
    const pct = (data.next_poll_in / state.pollInterval) * 100;
    $('poll-fill').style.width = pct + '%';
  }
  
  // Update new queue metrics and backpressure status
  if (data.avg_latency_ms !== undefined || data.queued !== undefined) {
    updateQueueMetrics(data);
    checkBackpressure(data);
  }
}

// ── Data fetch helpers ────────────────────────────────────────────────────
async function fetchGeoJSON() {
  try {
    const r = await fetch(apiUrl('/api/v1/events/geojson'));
    const data = await r.json();
    state.features = data.features || [];
    applyFilters();
  } catch (e) { console.warn('GeoJSON fetch failed:', e); }
}

async function fetchEvents() {
  try {
    const r = await fetch(apiUrl('/api/v1/events', { limit: 250 }));
    const data = await r.json();
    const events = data.events || [];
    events.forEach(e => { if (e.event?.id) state.events[e.event.id] = e; });
    renderFeed(events);
    updateStats(events);
  } catch (e) { console.warn('Events fetch failed:', e); }
}

async function fetchSummary() {
  try {
    const r = await fetch(apiUrl('/api/v1/analytics/summary'));
    const data = await r.json();
    updateCharts(data);
  } catch (e) { console.warn('Summary fetch failed:', e); }
}

// ── WebSocket ─────────────────────────────────────────────────────────────
function connectWebSockets() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const base = `${proto}://${location.host}`;

  // Events WebSocket
  function connectEventsWS() {
    const ws = new WebSocket(`${base}/ws/events`);
    ws.onopen = () => console.log('[WS:events] connected');
    ws.onmessage = e => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'event_completed') {
        const ev = msg.data;
        if (ev?.event?.id) state.events[ev.event.id] = ev;
        // Refresh data
        fetchGeoJSON();
        fetchEvents();
        fetchSummary();
      }
    };
    ws.onclose = () => setTimeout(connectEventsWS, 3000);
    // Keep-alive ping
    setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 25000);
  }

  // Queue WebSocket
  function connectQueueWS() {
    const ws = new WebSocket(`${base}/ws/queue`);
    ws.onopen = () => console.log('[WS:queue] connected');
    ws.onmessage = e => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'queue_stats') {
        updateQueue(msg.data);
        if (msg.data.poll_interval_seconds) {
          state.pollInterval = msg.data.poll_interval_seconds;
        }
      }
    };
    ws.onclose = () => setTimeout(connectQueueWS, 3000);
    setInterval(() => { if (ws.readyState === 1) ws.send('ping'); }, 25000);
  }

  connectEventsWS();
  connectQueueWS();
}

// ── Init ──────────────────────────────────────────────────────────────────
async function init() {
  initCharts();
  connectWebSockets();

  // Auto-scroll logic for the carousel
  setInterval(() => {
    const feed = $('event-feed');
    if (!feed) return;
    // Pause if user is interacting with the feed
    if (feed.matches(':hover') || feed.matches(':focus-within') || feed.matches(':active')) return;
    // Pause if a modal is currently open
    const modal = $('modal-backdrop');
    if (modal && modal.style.display === 'flex') return;

    if (feed.children.length > 1) {
      if (feed.scrollLeft + feed.clientWidth >= feed.scrollWidth - 10) {
        feed.scrollLeft = 0;
      } else {
        const shift = feed.children[1].offsetLeft - feed.children[0].offsetLeft;
        feed.scrollBy({ left: shift, behavior: 'smooth' });
      }
    }
  }, 3000);

  // Initial data load
  await Promise.all([fetchGeoJSON(), fetchEvents(), fetchSummary()]);

  // Periodic refresh as fallback
  setInterval(() => { fetchGeoJSON(); fetchEvents(); fetchSummary(); }, 15000);
}

init().catch(console.error);
