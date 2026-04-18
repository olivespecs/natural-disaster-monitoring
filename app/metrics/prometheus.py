"""Prometheus metrics collector backed by Redis-stored counters and gauges."""

import threading

from prometheus_client import REGISTRY
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, HistogramMetricFamily

from app.queue.manager import (
    LATENCY_BUCKET_BOUNDS_SECONDS,
    METRICS_EVENTS_PROCESSED_TOTAL_KEY,
    METRICS_GPU_UTILIZATION_KEY,
    METRICS_INFERENCE_LATENCY_BUCKET_PREFIX,
    METRICS_INFERENCE_LATENCY_SUM_SECONDS_KEY,
    inference_queue,
    redis_conn,
)

_COLLECTOR_REGISTERED = False
_COLLECTOR_LOCK = threading.Lock()


class RedisBackedCollector:
    """Collect Prometheus metrics from Redis and queue state."""

    def collect(self):
        queue_depth = GaugeMetricFamily(
            "queue_depth_total",
            "Current queue depth for inference jobs.",
        )
        queue_depth.add_metric([], float(inference_queue.count))
        yield queue_depth

        processed_total_raw = redis_conn.get(METRICS_EVENTS_PROCESSED_TOTAL_KEY) or b"0"
        processed_total = CounterMetricFamily(
            "events_processed",
            "Total successfully processed events.",
        )
        processed_total.add_metric([], float(processed_total_raw))
        yield processed_total

        gpu_util_raw = redis_conn.get(METRICS_GPU_UTILIZATION_KEY) or b"0"
        gpu_utilization = GaugeMetricFamily(
            "gpu_utilization_gauge",
            "Latest observed GPU utilization percentage.",
        )
        gpu_utilization.add_metric([], float(gpu_util_raw))
        yield gpu_utilization

        latency_sum_raw = redis_conn.get(METRICS_INFERENCE_LATENCY_SUM_SECONDS_KEY) or b"0"
        latency_sum = float(latency_sum_raw)

        cumulative_count = 0
        histogram_buckets = []
        for bound in LATENCY_BUCKET_BOUNDS_SECONDS:
            bucket_key = f"{METRICS_INFERENCE_LATENCY_BUCKET_PREFIX}{bound}"
            bucket_count = int(float(redis_conn.get(bucket_key) or b"0"))
            cumulative_count += bucket_count
            histogram_buckets.append((str(bound), cumulative_count))

        inf_bucket_count = int(float(redis_conn.get(f"{METRICS_INFERENCE_LATENCY_BUCKET_PREFIX}+Inf") or b"0"))
        histogram_buckets.append(("+Inf", cumulative_count + inf_bucket_count))

        latency_histogram = HistogramMetricFamily(
            "inference_latency_seconds",
            "Inference latency in seconds.",
            buckets=histogram_buckets,
            sum_value=latency_sum,
        )
        yield latency_histogram


def register_metrics_collector() -> None:
    """Register the Redis-backed collector once per process."""
    global _COLLECTOR_REGISTERED
    with _COLLECTOR_LOCK:
        if _COLLECTOR_REGISTERED:
            return
        REGISTRY.register(RedisBackedCollector())
        _COLLECTOR_REGISTERED = True
