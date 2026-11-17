"""Contract test (E6): the three SUT models must answer identically on the measured endpoints.

For every model a fresh SUT is started in Compose and the same requests are sent from the host. Compared per case:
status, Content-Type, body bytes and framing (Content-Length vs chunked), plus a fixed expected body, so that
"all three equally wrong" also fails. Error paths: 502 with the upstream port closed (connection refused), 504 with
an upstream slower than the timeout (DECISIONS.md, D10, D19). /diag/thread confirms that each model really runs on its own thread kind.

  python runner/contract_test.py              # writes results/<date>_smoke-contract/contract_report.json
  python runner/contract_test.py --no-build --no-save
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.client
import json
import sys
import tempfile
from pathlib import Path

from run_matrix import COMPOSE_FILE, RESULTS, compose, git_state, log, sh

MODELS = ("platform", "virtual", "reactive")
HOST, PORT = "127.0.0.1", 8080

# Expected responses of the measured endpoints and of the dependency-failure paths (API contract, plan section 4).
EXPECTED = {
    "io": (200, b'{"upstreamDelayMs":100}'),
    "cpu": (200, b'{"matches":true}'),
    "io_upstream_down": (502, b'{"error":"upstream_error"}'),
    "io_upstream_timeout": (504, b'{"error":"upstream_timeout"}'),
}

# Test-only SUT settings; the measured setup keeps 100 ms / 5 s and the real fake API address.
# Not "stop fake-api" for the 502 case: a stopped container's name does not fail fast in Docker DNS,
# so every model waited for the timeout and answered 504 (observed).
OVERRIDES = {
    "io_upstream_down": {"UPSTREAM_URL": "http://fake-api:9"},
    "io_upstream_timeout": {"IO_DELAY_MS": "3000", "UPSTREAM_TIMEOUT": "1s"},
}


def get(path: str) -> dict:
    conn = http.client.HTTPConnection(HOST, PORT, timeout=15)
    try:
        conn.request("GET", path)
        r = conn.getresponse()
        body = r.read()
        headers = {k.lower(): v for k, v in r.getheaders()}
    finally:
        conn.close()
    if "content-length" in headers:
        framing = "content-length"
    elif headers.get("transfer-encoding", "").lower() == "chunked":
        framing = "chunked"
    else:
        framing = "other"
    return {"status": r.status, "content_type": headers.get("content-type"), "body": body.decode("utf-8", "replace"),
            "body_bytes": len(body), "framing": framing,
            "header_names": sorted(headers)}


def contract_view(resp: dict) -> tuple:
    return resp["status"], resp["content_type"], resp["body"], resp["framing"]


def start_sut(model: str, extra_files: list[str] = ()) -> None:
    args = compose(model)
    for f in extra_files:
        args[args.index("--env-file"):args.index("--env-file")] = ["-f", f]
    sh(args + ["up", "-d", "--no-deps", "--no-build", "--force-recreate", "--wait", "sut"])


def check_model(model: str, overrides: dict[str, str]) -> dict:
    log(f"{model}: fresh SUT")
    start_sut(model)
    out = {}
    get("/io"), get("/cpu")  # first calls initialise lazy beans and connection pools; not part of the contract
    out["io"] = get("/io")
    out["cpu"] = get("/cpu")
    out["health"] = get("/actuator/health")
    prom = get("/actuator/prometheus")
    out["prometheus_has_model_tag"] = f'model="{model}"' in prom["body"]
    out["diag_thread"] = json.loads(get("/diag/thread")["body"])

    for case, override in overrides.items():
        log(f"{model}: {case} -> expect {EXPECTED[case][0]}")
        start_sut(model, [override])
        out[case] = get("/io")
    sh(compose(model) + ["stop", "sut"])
    return out


def thread_kind_ok(model: str, diag: dict) -> bool:
    if model == "virtual":
        return diag["virtual"] is True
    if model == "platform":
        return diag["virtual"] is False and "http-nio" in diag["thread"]
    return diag["virtual"] is False and "reactor-http" in diag["thread"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-build", action="store_true", help="use the existing jcmc/* images")
    ap.add_argument("--no-save", action="store_true", help="print only, do not write a report into results/")
    a = ap.parse_args()

    if not a.no_build:
        log("building images")
        for m in ("platform", "reactive"):
            sh(compose(m) + ["build", "sut", "fake-api"])
    sh(compose(MODELS[0]) + ["up", "-d", "--wait", "fake-api"])

    with tempfile.TemporaryDirectory() as tmp:
        overrides = {}
        for case, env in OVERRIDES.items():
            path = Path(tmp) / f"{case}.override.yml"
            lines = ["services:", "  sut:", "    environment:"] + [f'      {k}: "{v}"' for k, v in env.items()]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            overrides[case] = str(path)
        try:
            results = {m: check_model(m, overrides) for m in MODELS}
        finally:
            sh(["docker", "compose", "-f", COMPOSE_FILE, "down"], check=False)

    failures = []
    print(f"\n{'case':<22}{'model':<10}{'status':<8}{'bytes':<7}{'framing':<16}{'content-type':<20}body")
    for case, (status, body) in EXPECTED.items():
        views = {m: contract_view(results[m][case]) for m in MODELS}
        for m in MODELS:
            r = results[m][case]
            print(f"{case:<22}{m:<10}{r['status']:<8}{r['body_bytes']:<7}{r['framing']:<16}"
                  f"{str(r['content_type']):<20}{r['body']}")
            if (r["status"], r["body"].encode()) != (status, body):
                failures.append(f"{case}/{m}: expected {status} {body.decode()}")
        if len(set(views.values())) != 1:
            failures.append(f"{case}: models differ: {views}")
    for m in MODELS:
        r = results[m]
        if r["health"]["status"] != 200:
            failures.append(f"health/{m}: status {r['health']['status']}")
        if not r["prometheus_has_model_tag"]:
            failures.append(f"prometheus/{m}: no model=\"{m}\" tag")
        if not thread_kind_ok(m, r["diag_thread"]):
            failures.append(f"diag/{m}: unexpected thread {r['diag_thread']}")
        print(f"diag/thread {m:<10}{r['diag_thread']}")

    report = {"date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "git": git_state(),
              "expected": {k: {"status": s, "body": b.decode()} for k, (s, b) in EXPECTED.items()},
              "overrides": OVERRIDES,
              "results": results, "passed": not failures, "failures": failures}
    if not a.no_save:
        out_dir = RESULTS / f"{dt.date.today():%Y-%m-%d}_smoke-contract"
        out_dir.mkdir(parents=True)  # write-once (results/README.md)
        (out_dir / "contract_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
        log(f"report: {out_dir.relative_to(RESULTS.parent)}/contract_report.json")
    if failures:
        print("\nCONTRACT FAILED:\n  " + "\n  ".join(failures))
        sys.exit(1)
    print("\nCONTRACT OK: identical status, Content-Type, body and framing on all checked cases")


if __name__ == "__main__":
    main()
