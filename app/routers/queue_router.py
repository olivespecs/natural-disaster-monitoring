from fastapi import APIRouter

from app.queue.manager import get_queue_stats, inference_queue, redis_conn, list_dead_letters
from rq.job import Job
from app.config import settings

router = APIRouter(prefix="/api/v1/queue", tags=["Queue"])


@router.get("/stats", summary="Live queue depth, worker count, and throughput")
async def queue_stats():
    return get_queue_stats()


@router.get("/jobs", summary="Recent job list with statuses")
async def list_jobs(limit: int = 30):
    finished_ids = inference_queue.finished_job_registry.get_job_ids()[-limit:]
    failed_ids = inference_queue.failed_job_registry.get_job_ids()[-10:]
    queued_ids = inference_queue.get_job_ids()[:limit]

    jobs = []
    for jid in dict.fromkeys(queued_ids + finished_ids + failed_ids):
        try:
            job = Job.fetch(jid, connection=redis_conn)
            jobs.append({
                "id": jid,
                "status": str(job.get_status()),
                "created_at": str(job.created_at) if job.created_at else None,
                "enqueued_at": str(job.enqueued_at) if job.enqueued_at else None,
                "ended_at": str(job.ended_at) if job.ended_at else None,
            })
        except Exception:
            pass

    return {"jobs": jobs[:limit], "total": len(jobs)}


@router.post("/retry", summary="Re-enqueue all failed jobs")
async def retry_failed():
    failed_ids = inference_queue.failed_job_registry.get_job_ids()
    requeued = 0
    for jid in failed_ids:
        try:
            inference_queue.failed_job_registry.requeue(jid)
            requeued += 1
        except Exception:
            pass
    return {"requeued": requeued}


@router.get("/dead-letter", summary="Recent dead-letter jobs that exhausted retries")
async def dead_letter_jobs(limit: int = 50):
    jobs = list_dead_letters(limit=limit)
    return {"jobs": jobs, "total": len(jobs)}


@router.post("/simulate_load", summary="Simulate extreme load with fully structured mock EONET events")
async def simulate_load(count: int = 50):
    import uuid
    import random
    from datetime import datetime
    from app.models import EONETEvent, EONETCategory, EONETGeometry
    from app.queue.manager import enqueue_event_batch

    enqueued = 0
    categories = [
        ("wildfires", "Wildfires"),
        ("severeStorms", "Severe Storms"),
        ("volcanoes", "Volcanoes"),
        ("earthquakes", "Earthquakes")
    ]
    
    generated_events = []
    for i in range(count):
        cat_id, cat_title = random.choice(categories)
        lat = random.uniform(-60, 60)
        lon = random.uniform(-180, 180)
        
        event = EONETEvent(
            id=f"SIM_{uuid.uuid4()}",
            title=f"Simulated {cat_title} {i}",
            description="Simulated load test event",
            link="https://eonet.gsfc.nasa.gov",
            categories=[EONETCategory(id=cat_id, title=cat_title)],
            sources=[],
            geometry=[EONETGeometry(
                date=datetime.utcnow().isoformat(),
                type="Point",
                coordinates=[lon, lat]
            )]
        )
        generated_events.append(event)

    for idx in range(0, len(generated_events), settings.inference_batch_size):
        batch = generated_events[idx: idx + settings.inference_batch_size]
        job_id = await enqueue_event_batch(batch, at_front=True)
        if job_id:
            enqueued += len(batch)
        
    return {"message": f"Successfully enqueued {enqueued} simulated events.", "count": enqueued}


@router.post("/simulate-spike", summary="Simulate task spike for testing backpressure handling")
async def simulate_spike(count: int = 50):
    """Simulate a spike of tasks to test backpressure and load handling"""
    import uuid
    import random
    from datetime import datetime
    from app.models import EONETEvent, EONETCategory, EONETGeometry
    from app.queue.manager import enqueue_event_batch

    enqueued = 0
    categories = [
        ("wildfires", "Wildfires"),
        ("severeStorms", "Severe Storms"),
        ("volcanoes", "Volcanoes"),
        ("earthquakes", "Earthquakes")
    ]
    
    generated_events = []
    for i in range(count):
        cat_id, cat_title = random.choice(categories)
        lat = random.uniform(-60, 60)
        lon = random.uniform(-180, 180)
        
        event = EONETEvent(
            id=f"SPIKE_{uuid.uuid4()}",
            title=f"Spike Load Test {cat_title} {i}",
            description="Spike simulation event for backpressure testing",
            link="https://eonet.gsfc.nasa.gov",
            categories=[EONETCategory(id=cat_id, title=cat_title)],
            sources=[],
            geometry=[EONETGeometry(
                date=datetime.utcnow().isoformat(),
                type="Point",
                coordinates=[lon, lat]
            )]
        )
        generated_events.append(event)

    for idx in range(0, len(generated_events), settings.inference_batch_size):
        batch = generated_events[idx: idx + settings.inference_batch_size]
        job_id = await enqueue_event_batch(batch, at_front=True)
        if job_id:
            enqueued += len(batch)
        
    return {"message": f"Successfully enqueued {enqueued} spike events.", "count": enqueued}
