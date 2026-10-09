"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """TODO: ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    record = dict(ts=time.time(), iso=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                  step=n, name=name, **kw)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        log.write(json.dumps(record) + "\n")
    print(json.dumps(record), flush=True)
    return record


def confirm(auto: bool, msg: str) -> bool:
    """TODO: auto=True -> True; ngược lại hỏi y/N. Đừng bỏ hàm này đi."""
    return auto or input(msg + " [y/N] ").strip().lower() == "y"


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """TODO: 7 bước ở trên."""
    from dr.health_checker import probe
    import math
    if primary not in URL or target not in URL or primary == target:
        raise ValueError("primary and target must be distinct known regions")
    started = time.monotonic()
    for attempt in range(3):
        primary_ready, reason = probe(primary, 2)
        try:
            alive = httpx.get(f"{URL[target]}/healthz", timeout=2).status_code == 200
        except httpx.HTTPError:
            alive = False
        if primary_ready or not alive:
            return dict(ok=False, reason="outage unconfirmed or target unavailable")
        if attempt < 2:
            time.sleep(5)
    step(1, "xac_nhan_outage", primary=primary, target=target, probes=3, reason=reason)
    events = pathlib.Path("chaos/chaos-events.jsonl")
    kills = [json.loads(line) for line in events.read_text().splitlines()] if events.exists() else []
    outage = next((e["ts"] for e in reversed(kills)
                   if e.get("action") == "kill" and e.get("region") == primary), None)
    notice = step(2, "thong_bao_incident", t_outage=outage, primary=primary,
                  confirmation_mode="auto" if auto else "operator")
    if not confirm(auto, f"Fail over {primary} to {target}?"):
        return dict(ok=False, reason="operator declined")
    result = fo.failover(target, backend, wait=60)
    step(3, "scale_gpu_pool", result=result)
    if not result.get("ok"):
        return result
    step(4, "verify_state_replica", state=result["state"])
    step(5, "dns_cutover", ok=result["ok"], target=target)
    latencies, errors = [], 0
    for _ in range(10):
        tick = time.monotonic()
        try:
            response = httpx.get(f"{URL[target]}/v1/infer", timeout=2)
            errors += int(response.status_code != 200 or response.json().get("region") != target)
        except (httpx.HTTPError, ValueError):
            errors += 1
        latencies.append((time.monotonic()-tick)*1000)
    p95 = sorted(latencies)[math.ceil(0.95*len(latencies))-1]
    step(6, "verify_golden_signals", requests=10, p95_latency_ms=p95, error_rate=errors/10)
    step(7, "post_incident", elapsed_s=time.monotonic()-started,
         notification_delay_s=None if outage is None else notice["ts"]-outage,
         measure_command="python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300")
    return dict(**result, golden_signals_ok=errors == 0)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
