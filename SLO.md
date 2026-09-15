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
