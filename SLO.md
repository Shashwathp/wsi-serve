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
