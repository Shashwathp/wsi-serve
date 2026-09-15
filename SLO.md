# Service level objectives

Scenario: research platform. Users submit slides and poll for progress.
Not interactive, not overnight batch.

## Targets

| # | Objective | Target |
|---|---|---|
| 1 | Job submission acknowledged | p99 < 500 ms |
| 2 | Time to first completed tile | p95 < 5 s |
| 3 | 1,000-tile job, single worker | p95 < 120 s |
| 4 | Progress endpoint latency | p99 < 100 ms |
| 5 | Tiles lost on worker SIGKILL | 0 |
| 6 | Recovery time after worker death | < 15 s |
| 7 | Error rate at 8 concurrent jobs | < 0.1% |

## Notes

Targets set 2026-09-15, before any instrumentation existed.
Basis: single CPU worker measured at ~12 tiles/s, batch 16, batch latency ~1.3 s.
Target 6 = CLAIM_IDLE_MS (10 s) + one batch (1.3 s) + polling slack.
Target 3 assumes one worker; scales roughly linearly with worker count.

Written before measurement on purpose. Misses get recorded, not revised.

## Results, 2026-09-15

Single CPU worker, batch 16, wait 200ms. Open-loop arrival via k6.

**Under capacity** (1 job / 30s = 6.7 tiles/s arriving, 12 tiles/s drained)

| Metric | Target | Measured | |
|---|---|---|---|
| Time to first tile p95 | < 5 s | 2.03 s | pass |
| Job e2e p95 | < 120 s | 18.8 s | pass |
| Submit p99 | < 500 ms | 25.9 ms | pass |
| Error rate | < 0.1% | 0% | pass |

**Over capacity** (1 job / 10s = 20 tiles/s arriving, 12 tiles/s drained)

| Metric | Target | Measured | |
|---|---|---|---|
| Time to first tile p95 | < 5 s | 90.2 s | FAIL |
| Job e2e p95 | < 120 s | 89.8 s | pass, but invalid |

The e2e "pass" is survivorship bias: 14 of 19 jobs were still queued when the
run ended and contributed no sample. Only the 5 fastest jobs were measured.
Reported failure rate was 0% for the same reason — k6 interrupted those
iterations before MAX_WAIT, so they never incremented the timeout counter.

Measured capacity ceiling: ~12 tiles/s per worker. Arrival above that produces
unbounded queue growth, not graceful degradation.

## Metric correction

The over-capacity run was re-tested after fixing two measurement bugs:
jobs still queued at test end were being dropped from the latency sample,
and k6 killed those iterations before they could increment the timeout counter.

Fix: gracefulStop extended past MAX_WAIT, and timed-out jobs now record
MAX_WAIT as a censored e2e sample rather than contributing nothing.

Identical workload, before and after:

| Metric | Before fix | After fix |
|---|---|---|
| Failure rate | 0% | 57.9% |
| Job e2e p95 | 89.8 s (pass) | 240 s (fail) |
| Jobs completed | 5 / 19 | 8 / 19 |
| Thresholds crossed | 1 | 3 |

240 s is the censoring floor, not the true latency — those jobs were still
running when measurement stopped. The real p95 is higher.

HTTP error rate was 0.00% across 3,468 requests in both runs. The API stayed
healthy throughout. Monitoring HTTP status alone would have shown a fully
green service while 58% of submitted work never completed.

## Worker/thread sweep

1,200-tile job, batch 16, 8 CPUs allocated to the Docker VM.
Total threads held constant at 8 across all configurations.

| Config | Throughput | Batch p50 |
|---|---|---|
| 1 worker x 8 threads | 10.9 tiles/s | 1.50 s |
| 2 workers x 4 threads | 10.4 tiles/s | 3.17 s |
| 4 workers x 2 threads | 9.3 tiles/s | 7.48 s |
| 8 workers x 1 thread | 10.3 tiles/s | 16.08 s |

Throughput is flat (9.3-10.9) while batch latency scales ~linearly with
worker count. The workload is compute-bound, so splitting a fixed core
budget across more processes redistributes the same work rather than
adding capacity, and each worker takes proportionally longer per batch.

Implication: replica count is not a throughput dial on a single machine.
Autoscaling replicas only adds capacity when replicas land on additional
hardware. Kubernetes/KEDA was scoped out on this basis rather than building
a scaling demo that would not actually scale.

Remaining dial: batch size, which changes per-tile fixed overhead rather
than redistributing it.
