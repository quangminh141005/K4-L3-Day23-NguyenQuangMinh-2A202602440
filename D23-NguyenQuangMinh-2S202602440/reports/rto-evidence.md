# RTO/RPO Evidence — Lab 23

Executed on 2026-10-09 in conda `env_lab23`, bare mode, filesystem replication,
netblock mock (SIGSTOP), 5-second edge TTL and 6-second pool warm-up. All ISO times
below are UTC. Raw request timestamps denote request starts, per the grading tool.

## Baseline without DR

| Metric | Value | Evidence |
|---|---|---|
| Outage | 2026-10-09T13:13:43.859+00:00 | `chaos/chaos-events.jsonl:5` |
| First failed request | +0.493s | `reports/drill-1-nodr.jsonl:18` |
| Failed requests | 16 | `reports/measure-drill-1.json` |
| Recovery | NO_RECOVERY within 40-second observation | `reports/measure-drill-1.json` |

## Recovery drill

| Milestone | Seconds from outage | Evidence |
|---|---|---|
| Outage (2026-10-09T13:14:33.687+00:00) | 0s | `chaos/chaos-events.jsonl:7` |
| First user error | 0.008s | `reports/drill-2-withdr.jsonl:25` |
| Health checker detects A | 19.090s | `reports/health-events.jsonl:2` |
| Snapshot restore complete | 35.395s | `reports/failover-events.jsonl:2` |
| B ready | 41.500s | `reports/failover-events.jsonl:4` |
| DNS cutover | 41.505s | `reports/failover-events.jsonl:5` |
| First successful B request / measured RTO | 46.2s | `reports/drill-2-withdr.jsonl:48` |

| Metric | Measured | Target | Verdict | Evidence |
|---|---|---|---|---|
| Inference RTO | 46.2s | 300s | PASS | `reports/measure-drill-2.json` |
| Vector DB RPO at restore | 22.00s / 11 documents | 300s | PASS | `reports/failover-events.jsonl:2` |
| Embedding model version | embed-model=vi-e5-base@v3 | Compatible weights and index | Restored | `reports/failover-events.jsonl:2` |
| Golden signals (10 requests) | p95 26.55 ms; errors 0% | p95 < 1000 ms; errors 0 | PASS | `reports/runbook-run.jsonl:6` |

## RTO decomposition

These are non-overlapping measured intervals. The detection floor is a configured
15s budget; actual detection additionally depends on probe phase and timeouts.
Extra rows retain those overheads so the decomposition sums to the measured RTO.

| Component | Seconds | Evidence / calculation | Improvement |
|---|---|---|---|
| Health-check detection floor | 15.000s | interval × threshold, `reports/health-events.jsonl:2` | Reduce interval cautiously |
| Detection phase / timeout overhead | 4.090s | actual detection minus floor, `reports/health-events.jsonl:2` | Fixed-cadence concurrent probes |
| Operator confirmation / verify / restore | 16.305s | detection → restore event, `reports/failover-events.jsonl:2` | Preflight snapshot; faster incident handling |
| Scale dispatch overhead | 0.000s | restore → scale, `reports/failover-events.jsonl:3` | Negligible locally |
| GPU pool warm-up | 6.105s | scale → ready; waited_s=6.105, `reports/failover-events.jsonl:4` | Keep standby pool full at higher cost |
| Cutover verification overhead | 0.005s | ready → cutover, `reports/failover-events.jsonl:5` | Negligible locally |
| DNS/LB TTL cache and request sampling | 4.738s | first B request minus cutover, `reports/drill-2-withdr.jsonl:48` | Lower TTL; increases routing refresh work |
| Total (rounded to tool precision) | 46.2s | exact timestamp sum = 46.243s | Below 300s |

Snapshot copying itself took 0.0023s (restore event). RPO is
computed from primary and restored DB latest timestamps and lost-document count,
not snapshot age. The independent ingest process continues during SIGSTOP, so this
is RPO **at restore**, not a claim about every subsequent write. NO_RECOVERY in the
baseline means no recovery observed, not an infinite-duration measurement.
