# Postmortem — Lab 23

Blameless local disaster-recovery exercise; timestamps are UTC.

## Timeline

| UTC time | Event | Evidence |
|---|---|---|
| 2026-10-09T13:14:33.687+00:00 | Outage | `chaos/chaos-events.jsonl:7` |
| 2026-10-09T13:14:33.695+00:00 | First user failure | `reports/drill-2-withdr.jsonl:25` |
| 2026-10-09T13:14:52.777+00:00 | Health alert | `reports/health-events.jsonl:2` |
| 2026-10-09T13:15:09.074+00:00 | Operator notified / auto drill authorization | `reports/runbook-run.jsonl:2` |
| 2026-10-09T13:15:15.192+00:00 | Cutover | `reports/failover-events.jsonl:5` |
| 2026-10-09T13:15:19.930+00:00 | First successful B request | `reports/drill-2-withdr.jsonl:48` |

## RTO / RPO targets and gap analysis

RTO target 300s; measured 46.2s; gap (measured − target) -253.8s.
RPO target 300s; measured 22.00s and 11 lost documents; gap -278.00s.
Evidence: `reports/measure-drill-2.json` and `reports/failover-events.jsonl:2`.
Largest configured recovery component is the 15s detection floor.
Operator notification lag was 35.387s; it is not the outage timestamp.
Golden signals: 10 requests, p95 26.55 ms, error rate 0%.

## Root cause — five whys

1. Users saw errors because the active region stopped answering requests.
2. The edge kept targeting A because its routing pointer and cached target remained A.
3. Baseline could not recover because no independent health detection or recovery runbook existed.
4. Simply routing to B would fail because B initially lacked vectors, weights and a full pool.
5. Availability was incomplete because compute, state replication and routing had not been operated as one tested recovery procedure.

A real incident could still fail if the snapshot store is unavailable, the copied
SQLite snapshot is inconsistent during concurrent writes, model versions mismatch,
or B never becomes ready. The current automation aborts before routing when restore
or readiness fails. Both regions and snapshots reside on one host: this validates
the procedure, not physical region isolation. Golden checks sample B directly;
the load-generator logs separately prove successful traffic through the edge.

## Action items

| Action item | Owner | Deadline | Expected effect (hypothesis; remeasure) |
|---|---|---|---|
| Evaluate 1-second probes with threshold 3 and fixed cadence | SRE | 2026-10-16 | Configured floor falls 15s → 3s; possible 12s RTO reduction |
| Use transactional SQLite backup and verify manifest checksums/version | Data platform | 2026-10-16 | Avoid corrupt restore; no measured latency claim |
| Evaluate 10-second replication and stop/reconcile source writes at cutover | Data platform | 2026-10-23 | Nominal snapshot lag bound falls 30s → 10s; measure actual RPO |
| Add sustained edge checks and an explicit failback circuit breaker | Incident commander / SRE | 2026-10-23 | Reduce undetected regressions and prevent routing flaps |

## Required reflections

1. interval × threshold = 5s × 3 = 15s, 32.5% of measured RTO.
   This is the lab's configured detection floor. Poll phase and timeouts affect the
   actual observation. With a 300s RTO, interval must fit the remaining recovery
   budget divided by 3; choosing 100s leaves no budget for restore/warm-up/routing.
2. A 1s interval lowers the configured floor by 12s, not a guaranteed 12s measured
   improvement. It increases probe load and reacts to shorter transient outages;
   retain consecutive-failure threshold, operator approval and circuit breaker.
   A lower DNS TTL can reduce cache delay without changing outage thresholds, at
   the cost of more frequent routing lookups.
3. If A loses data permanently for six hours, 11 documents absent at restore are
   unavailable on B and require replay from a durable upstream source. The logged
   number excludes writes accepted after that measurement; reconciliation is
   essential before failback or declaring all data recovered.
4. Before implementation, no component detected the outage; B held zero vectors
   and no weights. Immediate routing to B would return region_not_ready.
5. The checker runs separately and imports no serving code, so pausing A does not
   pause its observer. For proof of a five-minute RTO, open the measured JSON plus
   the request and chaos evidence lines in `reports/rto-evidence.md`.
