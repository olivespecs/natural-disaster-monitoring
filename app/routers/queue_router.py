from fastapi import APIRouter

from app.queue.manager import get_queue_stats, inference_queue, redis_conn, list_dead_letters
from rq.job import Job

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
