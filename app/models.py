from pydantic import BaseModel
from typing import List, Optional, Any
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TrendOutlook(str, Enum):
    STABLE = "STABLE"
    ESCALATING = "ESCALATING"
    DECLINING = "DECLINING"


class EONETGeometry(BaseModel):
    date: str
    type: str
    coordinates: Any


class EONETCategory(BaseModel):
    id: str
    title: str


class EONETSource(BaseModel):
    id: str
    url: str


class EONETEvent(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    link: str
    closed: Optional[str] = None
    categories: List[EONETCategory] = []
    sources: List[EONETSource] = []
    geometry: List[EONETGeometry] = []


class InferenceResult(BaseModel):
    event_id: str
    category: str
    severity_score: float          # 0–100
    risk_level: RiskLevel
    trend: TrendOutlook
    estimated_impact: str
    impact_narrative: str
    recommendations: List[str]
    inference_mode: str            # "gemma-4-26b-a4b-it" or "heuristic"
    pipeline_path: str             # "TIER_2_GEMINI" or "TIER_1_HEURISTIC"
    confidence: float
    processed_at: datetime


class EnrichedEvent(BaseModel):
    event: EONETEvent
    inference: Optional[InferenceResult] = None
    job_id: str
    status: str                    # queued | processing | completed | failed
    queued_at: datetime
    completed_at: Optional[datetime] = None


class QueueStats(BaseModel):
    queued: int
    started: int
    finished: int
    failed: int
    workers: int
    events_per_minute: float
    avg_latency_ms: Optional[float] = 0.0
    last_latency_ms: Optional[int] = 0
    backpressure_warning: Optional[bool] = False
    current_processing_event_id: Optional[str] = None
    last_poll_at: Optional[str] = None
    next_poll_in: Optional[int] = None
    is_polling: Optional[bool] = False
