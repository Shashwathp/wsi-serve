from prometheus_client import Counter, Histogram, Gauge

BATCH_LATENCY = Histogram(
    "worker_batch_seconds",
    "Wall time to process one batch",
    buckets=(0.1, 0.25, 0.5, 0.75, 1.0, 1.1, 1.2, 1.3, 1.35, 1.4, 1.45, 1.5, 1.75, 2.0, 3.0, 5.0, 10.0),
)

BATCH_SIZE = Histogram(
    "worker_batch_size",
    "Tiles per batch",
    buckets=(1, 2, 4, 8, 12, 16, 24, 32, 64),
)

TILES_DONE = Counter("worker_tiles_total", "Tiles processed", ["outcome"])
RECLAIMS = Counter("worker_reclaims_total", "Batches reclaimed from dead workers")

QUEUE_DEPTH = Gauge("queue_pending", "Entries claimed but not acked")
QUEUE_LEN = Gauge("queue_length", "Total entries in stream")

HTTP_LATENCY = Histogram(
    "http_request_seconds",
    "HTTP handler duration",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
