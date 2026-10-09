# Runbook — Primary Region A unavailable

Run from the repository root after `conda activate env_lab23`. Local endpoints only.
The incident commander authorizes failover; the on-call operator executes it. Default
execution requires a `y` confirmation. Use `--auto` only for this graded drill or CI.

Prerequisites: both bare-mode services and edge running; a valid filesystem snapshot
with vector DB, model weights, and embedding model version. Before the drill run
`python3 state/replicate.py --every 30 --duration 150 --backend fs` and verify a
record in `reports/replication.jsonl`. Start the traffic recorder and health checker
using the commands in GUIDE.md before injecting the outage.

| # | Step | Copy-paste command | Completion signal | Owner |
|---|---|---|---|---|
| 1 | Confirm outage | `python3 chaos/kill_region.py status` | A not ready; independent checker records three consecutive failures; B alive. A paused process can have a live PID. | On-call |
| 2 | Open incident and start recovery | `python3 dr/runbook.py --primary a --target b --backend fs` | Steps 1–2 logged with outage and notification timestamps; enter `y` once authorized. | On-call / incident commander |
| 3 | Restore state and scale pool (automatic within step 2 command) | `cat reports/failover-events.jsonl` | Ordered verify, restore (RPO seconds, lost docs, embedding version), and scale-to-full events. Do not run failover twice. | Recovery automation |
| 4 | Verify replica and readiness | `curl -fsS http://127.0.0.1:8002/readyz` | HTTP 200; vectors nonempty, weights present, warm-up complete; runbook step 4 records state. | On-call |
| 5 | Verify DNS/LB cutover | `curl -fsS http://127.0.0.1:8080/edge/state` | Active region b after the 5-second cache expires; cutover follows successful readiness. | On-call |
| 6 | Verify golden signals | `cat reports/runbook-run.jsonl` | Step 6: 10 real requests, error rate 0 and p95 latency below 1000 ms; also `curl -fsS http://127.0.0.1:8080/v1/infer` returns region b. | On-call |
| 7 | Measure and review | `python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Valid true, no warnings, PASS; archive logs and complete evidence/postmortem. | Incident commander |

If snapshot restore fails or readiness times out, automation aborts without changing
the routing pointer. Investigate the error and restore availability of A rather than
sending traffic to an unready B. If golden signals fail after cutover, the incident
commander alone may authorize rollback; never alternate regions automatically.

For a paused A, run `python3 chaos/kill_region.py restore --region a --backend bare`.
Before returning traffic, reconcile writes accepted since cutover, validate the
embedding version, and snapshot the authoritative B state with
`python3 state/snapshot.py put --region b --backend fs`. Require A readiness and
healthy B golden signals, then execute
`python3 dr/failover.py --target a --backend fs` under commander authorization.
This restores B's snapshot into A, waits for readiness, and changes routing safely.
For a killed process, restart the bare stack after first stopping existing lab
services; retain all evidence. Finish the drill with `bash scripts/down_bare.sh`.
