# wsi-serve

An async inference service for gigapixel pathology slides. Submit a slide, get a
job ID immediately, and poll for per-tile results as a worker pool grinds through
thousands of independent inference tasks.

Built to close a specific gap: my prior work was batch research infrastructure
(SLURM, 24 GPUs, 11.7K whole-slide images) where nothing was serving traffic and
nothing had a latency target. This is the online version of that workload —
queues, backpressure, fault tolerance, and measured SLOs.

## What it does

A whole-slide image is too large to run through a model in one pass, so it is cut
into 224x224 tiles. One slide becomes ~7,000 independent work items. Each tile is
encoded by a frozen pathology foundation model into a 768-dim vector, then
classified into one of nine tissue types by a linear head.

The engineering is in the fan-out: one HTTP request becomes thousands of queue
entries, processed by a worker pool that must batch efficiently, survive crashes,
and report progress without scanning anything.

## Architecture

    POST /jobs
        |
        v
    FastAPI  ---->  Redis Stream (tile-level work items)
        |                   |
        |                   v
        |           Worker pool
        |             - XREADGROUP COUNT + BLOCK  (batch formation)
        |             - Phikon ViT-B  ->  768-dim embedding
        |             - 9x768 linear head  ->  tissue class
        |             - XACK
        |                   |
        v                   v
    GET /jobs/{id}    memmap        (embeddings, row = tile index)
    GET /jobs/{id}/tiles
                      Redis hash    (labels, field = tile index)
                      Redis bitmap  (progress, bit = tile index)

**Model:** Phikon (Owkin), ViT-B/16, 85.8M params, trained on 40M pan-cancer
tiles from TCGA. Frozen — no fine-tuning.

**Data:** CRC-VAL-HE-7K — 7,180 labelled colorectal histology tiles, 9 classes.

**Stack:** Python, FastAPI, Redis Streams, PyTorch, Docker Compose, Prometheus,
Grafana, k6.

## Design decisions

**Tile-level work items, not slide-level.** A dead worker loses at most one batch
instead of an entire slide's progress. Costs 7,000 queue entries instead of 1,
which Redis does not care about.

**Redis Streams over a list.** A list gives you BRPOPLPUSH and then you write your
own reaper to find work a crashed worker took and never finished. Streams provide
a pending-entries list and XAUTOCLAIM natively. XREADGROUP COUNT=n BLOCK=ms is
also exactly the batch-formation primitive — max batch size and max wait — so no
batching logic was written at all.

**Preallocated memmap for results.** Stream delivery is at-least-once, so a tile
can be processed twice after a reclaim. Writing to a fixed row index makes
duplicates a no-op. Idempotency by construction rather than dedupe logic.

**Bitmap for progress.** SETBIT on completion, BITCOUNT to read — one operation
regardless of job size. 7,180 tiles is 898 bytes, and the progress endpoint
measures 0.9 ms p50 independent of job size.

**Labels in Redis, not a file.** The first version rewrote a JSON array on every
batch. With two workers that is a read-modify-write race with silent data loss.
Moved to a Redis hash keyed by tile index, where concurrent writes to distinct
fields do not collide. The memmap never had this problem because each worker owns
distinct rows — same data, different format, different concurrency properties.

**Head exported as a plain matrix.** A pickled sklearn estimator loaded under a
different sklearn version can fail silently with wrong predictions. The classifier
is stored as a 9x768 weight matrix and a 9-vector bias, applied as a matmul. No
sklearn in the inference container.

## Results

Single worker, 8 threads, CPU inference, Docker on an M4 MacBook Air.
SLO targets were written before any instrumentation existed (see SLO.md).

### Crash recovery

Worker SIGKILLed mid-batch during a 1,200-tile job. Surviving worker reclaimed the
abandoned tiles after CLAIM_IDLE_MS expired. Job completed, zero all-zero rows in
the output array. No heartbeats, no supervisor, no coordination between workers.

CLAIM_IDLE_MS is set to 10 s against a measured batch latency of 1.4 s — roughly
7x headroom, tight enough to recover quickly and loose enough that a merely slow
worker does not get its work stolen.

### Batch size sweep

800-tile job, 1 worker, 8 threads.

| Batch | Throughput | Batch p50 | Per-tile |
|---|---|---|---|
| 1 | 9.0 tiles/s | 0.110 s | 109.9 ms |
| 4 | 10.8 tiles/s | 0.373 s | 93.3 ms |
| 8 | 11.3 tiles/s | 0.719 s | 89.9 ms |
| 16 | 11.4 tiles/s | 1.439 s | 89.9 ms |
| 32 | 11.5 tiles/s | 2.914 s | 91.1 ms |
| 64 | 11.9 tiles/s | 5.910 s | 96.7 ms |

Per-tile cost is a U-curve with a flat minimum at batch 8-16. Batching from 1 to 8
cuts per-tile cost 18% by amortizing fixed per-batch overhead. Beyond 16 it
regresses: on CPU the larger activation matrices exceed cache and the workload
shifts from compute-bound to memory-bandwidth-bound. This is the opposite of GPU
behaviour, where throughput keeps climbing past batch 128.

Batch 64 buys 4% more throughput than batch 8 for 8x the batch latency. Since
batch latency sets time-to-first-tile, that trade fails the SLO.

Chose batch 8. Time-to-first-tile p95 dropped from 2.03 s to 1.07 s, a 47%
reduction, with throughput unchanged.

### Worker/thread sweep

1,200-tile job, total threads held at 8 across all configurations.

| Config | Throughput | Batch p50 |
|---|---|---|
| 1 worker x 8 threads | 10.9 tiles/s | 1.50 s |
| 2 workers x 4 threads | 10.4 tiles/s | 3.17 s |
| 4 workers x 2 threads | 9.3 tiles/s | 7.48 s |
| 8 workers x 1 thread | 10.3 tiles/s | 16.08 s |

Throughput is flat while batch latency scales linearly with worker count. The
workload is compute-bound, so splitting a fixed core budget across more processes
redistributes the same work rather than adding capacity.

Replica count is not a throughput dial on a single machine.

### SLO compliance

Under capacity (1 job / 30 s = 6.7 tiles/s arriving, ~11 tiles/s drained):

| Metric | Target | Measured | |
|---|---|---|---|
| Submit p99 | < 500 ms | 25.9 ms | pass |
| Time to first tile p95 | < 5 s | 1.07 s | pass |
| Job e2e p95 | < 120 s | 18.1 s | pass |
| Progress endpoint p99 | < 100 ms | 0.9 ms | pass |
| Tiles lost on SIGKILL | 0 | 0 | pass |
| Error rate | < 0.1% | 0% | pass |

Over capacity (1 job / 10 s = 20 tiles/s arriving):

| Metric | Target | Measured | |
|---|---|---|---|
| Time to first tile p95 | < 5 s | 238.8 s | FAIL |
| Job e2e p95 | < 120 s | 240 s | FAIL |
| Error rate | < 0.1% | 57.9% | FAIL |

The system does not degrade gracefully past its capacity ceiling — the queue grows
without bound and every subsequent job waits longer than the last. There is no
admission control or backpressure at the API. This is a known limitation, not a
bug that was missed.

## Two measurement bugs worth describing

Both were found by distrusting a result that looked fine.

### A load test that reported 0% failures while 58% of jobs never finished

The first end-to-end load test passed its error-rate threshold at 0.00% on an
overloaded system. Two things caused that.

k6 kills in-flight iterations when a scenario's duration elapses, so jobs still
waiting in the queue were terminated before they could increment the timeout
counter. And because those jobs never completed, they contributed no sample to the
latency metric — so the p95 was computed over only the jobs that finished fastest.
Survivorship bias, the same family of error as coordinated omission.

Fixed by extending gracefulStop past MAX_WAIT and recording MAX_WAIT as a censored
sample for jobs that time out. A censored lower bound understates the true latency
but at least it cannot be silently dropped.

Identical workload, before and after the fix:

| Metric | Before | After |
|---|---|---|
| Failure rate | 0% | 57.9% |
| Job e2e p95 | 89.8 s (pass) | 240 s (fail) |
| Thresholds crossed | 1 | 3 |

HTTP error rate was 0.00% across 3,468 requests in both runs. The API was healthy
the whole time. Monitoring HTTP status alone would have shown a fully green
service while most submitted work never completed.

### Prometheus reported a p99 that did not exist in the data

histogram_quantile returned exactly 1.50 s for batch latency. The raw samples gave
1.452 s. The reported value was pinned to a bucket boundary because every
observation fell inside a single 1.0-1.5 bucket, and Prometheus interpolates
within buckets rather than knowing where observations actually landed.

A 3% error here, but the size is arbitrary — with buckets of (1.0, 2.0) the same
data would have reported 2.0, a 38% error. The estimate is bounded by bucket
width, not by measurement precision.

Every batch also appends a raw timestamp, size, and duration to a CSV, so
percentiles can be computed exactly and checked against the histogram. Buckets
were subsequently retuned around the measured distribution — which only works for
a workload already characterized, and is why the raw samples are kept.

## Load testing methodology

k6 with the constant-arrival-rate executor — open-loop. A closed-loop generator
sends its next request only after the previous one returns, so it slows down when
the service slows down and never observes behaviour under sustained arrival during
a slowdown. That is coordinated omission, and it makes p99s look far better than
reality.

Arrival rate is held constant regardless of how the service responds, which is what
produces the unbounded queue growth documented above.

SLO targets are encoded as k6 thresholds, so the SLO is a test that exits non-zero
rather than a document nobody reads.

## Limitations

**Not tested beyond a single machine.** Everything runs in Docker Compose on one
laptop. There is no multi-node behaviour, no network partition testing, no real
distributed failure mode.

**No autoscaling.** Kubernetes and KEDA were scoped out after the worker sweep
showed that adding replicas on a fixed core budget does not add throughput. A
scaling demo on one machine would show the mechanism working while throughput
stayed flat. Autoscaling only adds capacity when replicas land on additional
hardware.

**No admission control.** The API accepts every job with a 202 regardless of queue
depth. Past capacity this produces unbounded growth rather than shedding load or
signalling backpressure. A production version would reject or queue-with-notice
above a depth threshold.

**Stream is never trimmed.** Acked entries are retained, so the stream grows
without bound. Needs XADD MAXLEN or periodic XTRIM.

**Classifier accuracy is not a result.** The linear probe reports 99.95% on a
random within-set split, which is leakage — adjacent tiles from the same slide land
in both train and test. Published cross-cohort numbers for this task are around
95%. The head exists so the service has something legible to return, not as a
modeling contribution.

**CPU only.** Measured 61 tiles/s on Apple MPS versus 11 tiles/s in a CPU
container, but Docker on Apple Silicon has no GPU access, so the served path is
CPU. A GPU cost comparison on rented hardware was scoped out as low value relative
to the remaining work.

## What this project does not demonstrate

Worth stating plainly. This is a two-week solo project and it cannot show: being
paged for something you did not build, incident response with real users affected,
rollback under pressure, multi-team API contracts you cannot unilaterally change,
authn/authz, multi-tenancy, audit trails, or the slow operational drift that only
appears over months.

## Running it

    docker compose up -d --scale worker=1
    curl -X POST localhost:8000/jobs -H 'content-type: application/json' \
      -d '{"n_tiles": 200}'
    curl localhost:8000/jobs/<job_id>

Prometheus at localhost:9090, Grafana at localhost:3000, API docs at
localhost:8000/docs.

Load tests:

    k6 run -e RATE=1 -e UNIT=30s -e DURATION=2m load/e2e.js

Crash recovery demo:

    ./scratch/killtest.sh

## Licence note

Phikon weights are Owkin's, released for non-commercial research use. They are
downloaded at runtime and not redistributed here. This project is a portfolio
exercise, not a product.
