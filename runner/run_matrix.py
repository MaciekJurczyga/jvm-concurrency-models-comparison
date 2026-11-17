"""Runs the experiment matrix: for each run restart SUT -> warm-up -> scenario -> collect artifacts -> validate -> cool down.

Layout and naming of the output: results/README.md (DECISIONS.md, D17). Procedure: plan section 6, DECISIONS.md, D18.

  python runner/run_matrix.py --dry-run
  python runner/run_matrix.py --only s1-io/platform --reps 1
  python runner/run_matrix.py --kind pilot --reps 3 --seed 42
  python runner/run_matrix.py --config runner/smoke.yaml --kind smoke
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import fnmatch
import json
import os
import platform
import random
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
COMPOSE_FILE = "infra/docker-compose.yml"
# Not "localhost": on Windows it resolves to ::1 first and each request waits ~2 s before falling back to IPv4.
PROMETHEUS_URL = "http://127.0.0.1:9090"
SUT_CONTAINER = "jcmc-sut-1"
FAKE_API_CONTAINER = "jcmc-fake-api-1"
K6_CONTAINER = "jcmc-k6"
KINDS = ("dev", "smoke", "pilot", "main", "rerun")
NO_SUT = "none"
# Time for the last Prometheus scrape and k6 remote-write flush (both every 1 s) to land before exporting.
SETTLE_S = 5
PER_RUN_OVERHEAD_S = 45


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def ts(t: dt.datetime) -> dict:
    return {"iso": t.isoformat(timespec="milliseconds"), "epoch": round(t.timestamp(), 3)}


def sh(args: list[str], check: bool = True, encoding: str = "utf-8", **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, text=True, encoding=encoding, errors="replace",
                          capture_output=True, check=check, **kw)


def compose(model: str) -> list[str]:
    base = ["docker", "compose", "-f", COMPOSE_FILE]
    # Model "none" (capacity checks without a SUT): no env file, so Compose cannot start or build a SUT.
    return base if model == NO_SUT else base + ["--env-file", f"infra/models/{model}.env"]


# ---------------------------------------------------------------- configuration

def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config_files(path: Path) -> list[Path]:
    """The config and every file it extends, base first (all are snapshotted with the series)."""
    parent = yaml.safe_load(path.read_text(encoding="utf-8")).get("extends")
    return (config_files(path.parent / parent) if parent else []) + [path]


def load_config(path: Path, overrides: list[str]) -> dict:
    cfg: dict = {}
    for f in config_files(path):
        cfg = deep_merge(cfg, yaml.safe_load(f.read_text(encoding="utf-8")))
    cfg.pop("extends", None)
    for item in overrides:
        key, sep, raw = item.partition("=")
        if not sep:
            sys.exit(f"--set expects key.path=value, got: {item}")
        node = cfg
        *parents, leaf = key.split(".")
        for p in parents:
            if not isinstance(node.get(p), dict):
                sys.exit(f"--set: unknown key {key}")
            node = node[p]
        if leaf not in node:
            sys.exit(f"--set: unknown key {key}")
        node[leaf] = yaml.safe_load(raw)
    return cfg


def test_duration_s(test: dict) -> int:
    p = test["params"]
    if "DURATION_S" in p:
        return int(p["DURATION_S"])
    if "STEP_DURATION_S" in p:
        steps = (p["MAX_RATE"] - p["START_RATE"]) // p["STEP_RATE"] + 1
        return int(steps * p["STEP_DURATION_S"])
    return int(p["BEFORE_S"] + p["FLOOD_S"] + p["AFTER_S"])


def test_models(cfg: dict, test: str) -> list[str]:
    # Capacity checks (smoke) target the fake API directly and declare models: [none], i.e. no SUT.
    return cfg["tests"][test].get("models") or cfg["models"]


def warmup_s(test: dict) -> int:
    return test["warmup"]["duration_s"] if test.get("warmup") else 0


def build_plan(cfg: dict, only: list[str], reps: int, seed: int) -> list[dict]:
    configs = [(t, m) for t in cfg["tests"] for m in test_models(cfg, t)]
    if only:
        wanted = set()
        for o in only:
            t, _, m = o.partition("/")
            hits = {c for c in configs if fnmatch.fnmatchcase(c[0], t) and fnmatch.fnmatchcase(c[1], m or "*")}
            if not hits:
                sys.exit(f"--only {o}: no match, available: {[f'{a}/{b}' for a, b in configs]}")
            wanted |= hits
        configs = [c for c in configs if c in wanted]
    order = [c for c in configs for _ in range(reps)]
    # Random, interleaved order with a recorded seed (plan section 6, Papadopoulos et al.).
    random.Random(seed).shuffle(order)
    seen: dict[tuple, int] = {}
    plan = []
    for i, (t, m) in enumerate(order, start=1):
        seen[(t, m)] = seen.get((t, m), 0) + 1
        rep = seen[(t, m)]
        plan.append({"index": i, "test": t, "model": m, "rep": rep,
                     "run_id": f"{i:03d}_{t}_{m}_r{rep}"})
    return plan


def series_id_for(kind: str, label: str | None) -> str:
    base = f"{dt.date.today():%Y-%m-%d}_{kind}"
    sid = f"{base}-{label}" if label else base
    if not (RESULTS / sid).exists():
        return sid
    if kind != "dev":
        sys.exit(f"results/{sid} already exists (results are write-once); pass a distinct --label")
    n = 2
    while (RESULTS / f"{sid}-{n}").exists():
        n += 1
    return f"{sid}-{n}"


# ---------------------------------------------------------------- environment facts

def git_state() -> dict:
    commit = sh(["git", "rev-parse", "HEAD"]).stdout.strip()
    dirty = [l for l in sh(["git", "status", "--porcelain"]).stdout.splitlines() if l.strip()]
    return {"commit": commit, "dirty": bool(dirty), "dirty_files": dirty}


def image_id(image: str) -> str | None:
    r = sh(["docker", "image", "inspect", "--format", "{{.Id}}", image], check=False)
    return r.stdout.strip() or None


def host_power() -> dict:
    """Measurement hygiene (plan section 3): power plan and AC state, recorded per run."""
    if platform.system() != "Windows":
        return {}
    plan = sh(["powercfg", "/getactivescheme"], check=False, encoding="oem").stdout.strip()
    # Win32_Battery.BatteryStatus 2 = on AC power.
    r = sh(["powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Battery | Select-Object -First 1).BatteryStatus"], check=False)
    status = r.stdout.strip()
    return {"power_plan": plan, "on_ac_power": status == "2" if status else None}


def series_versions(cfg: dict) -> dict:
    pom = (REPO / "pom.xml").read_text(encoding="utf-8")
    boot = re.search(r"spring-boot-starter-parent</artifactId>\s*<version>([^<]+)", pom)
    k6_image = re.search(r"image:\s*(grafana/k6:\S+)", (REPO / COMPOSE_FILE).read_text(encoding="utf-8")).group(1)
    images = {name: image_id(name) for name in
              ["jcmc/mvc:dev", "jcmc/webflux:dev", "jcmc/fake-api:dev", k6_image,
               "prom/prometheus:v3.16.0"]}
    return {
        "spring_boot": boot.group(1) if boot else None,
        "docker_server": sh(["docker", "version", "--format", "{{.Server.Version}}"], check=False).stdout.strip(),
        "docker_compose": sh(["docker", "compose", "version", "--short"], check=False).stdout.strip(),
        "k6": sh(["docker", "run", "--rm", k6_image, "version"], check=False).stdout.strip(),
        "python": platform.python_version(),
        "images": images,
        "host": {"system": platform.platform(), "machine": platform.machine(), "processor": platform.processor()},
    }


# ---------------------------------------------------------------- docker stats

class DockerStats:
    """Streams `docker stats` for all jcmc containers into a CSV (per-container CPU and memory, plan section 5)."""

    FIELDS = ["epoch", "container", "cpu_pct", "mem_used_bytes", "mem_limit_bytes", "mem_pct", "pids",
              "net_io", "block_io"]
    UNITS = {"B": 1, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
             "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4}

    def __init__(self, path: Path):
        self.path = path
        self.rows: list[dict] = []
        self.proc: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None

    @classmethod
    def to_bytes(cls, s: str) -> float | None:
        m = re.match(r"([\d.]+)\s*([A-Za-z]+)", s.strip())
        return float(m.group(1)) * cls.UNITS.get(m.group(2).upper(), 1) if m else None

    def start(self) -> None:
        # Without container arguments docker stats also picks up containers started later (the k6 container).
        self.proc = subprocess.Popen(["docker", "stats", "--format", "{{json .}}"], cwd=REPO,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", errors="replace")
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        with self.path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            w.writeheader()
            for line in self.proc.stdout:
                i = line.find("{")
                if i < 0:
                    continue
                try:
                    d = json.loads(line[i:])
                except json.JSONDecodeError:
                    continue
                if not d.get("Name", "").startswith("jcmc-"):
                    continue
                used, _, limit = d.get("MemUsage", "").partition("/")
                row = {"epoch": round(time.time(), 3), "container": d["Name"],
                       "cpu_pct": d.get("CPUPerc", "").rstrip("%") or None,
                       "mem_used_bytes": self.to_bytes(used), "mem_limit_bytes": self.to_bytes(limit),
                       "mem_pct": d.get("MemPerc", "").rstrip("%") or None, "pids": d.get("PIDs"),
                       "net_io": d.get("NetIO"), "block_io": d.get("BlockIO")}
                w.writerow(row)
                f.flush()
                self.rows.append(row)

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.thread:
            self.thread.join(timeout=10)

    def _values(self, field: str, container: str, start: float, end: float) -> list[float]:
        return sorted(float(r[field]) for r in self.rows
                      if r["container"] == container and r[field] and start <= r["epoch"] <= end)

    def cpu_p95(self, container: str, start: float, end: float) -> float | None:
        vals = self._values("cpu_pct", container, start, end)
        if not vals:
            return None
        return vals[min(len(vals) - 1, int(round(0.95 * (len(vals) - 1))))]

    def mem_max(self, container: str, start: float, end: float) -> float | None:
        vals = self._values("mem_used_bytes", container, start, end)
        return vals[-1] if vals else None


# ---------------------------------------------------------------- k6 and Prometheus

def run_k6(cfg: dict, model: str, script: str, env: dict, testid: str, summary_rel: str,
           raw_csv_rel: str | None, log_path: Path) -> tuple[int, dt.datetime, dt.datetime]:
    sh(["docker", "rm", "-f", K6_CONTAINER], check=False)
    env = {**env, "REQUEST_TIMEOUT": cfg["k6"]["request_timeout"], "SUMMARY_PATH": f"/results/{summary_rel}"}
    args = compose(model) + ["run", "--rm", "-T", "--name", K6_CONTAINER]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    args += ["k6", "run", "--quiet", "--no-color", "--tag", f"testid={testid}", "-o", "experimental-prometheus-rw"]
    if raw_csv_rel:
        args += ["-o", f"csv=/results/{raw_csv_rel}"]
    args.append(f"/load/scenarios/{script}")
    start = now_utc()
    with log_path.open("w", encoding="utf-8") as f:
        f.write(" ".join(args) + "\n\n")
        f.flush()
        rc = subprocess.run(args, cwd=REPO, stdout=f, stderr=subprocess.STDOUT).returncode
    return rc, start, now_utc()


def export_prometheus(cfg: dict, testid: str, start: float, end: float, out_dir: Path) -> dict:
    out_dir.mkdir()
    status = {}
    for name, template in cfg["prometheus"]["queries"].items():
        query = string.Template(template).substitute(testid=testid)
        url = f"{PROMETHEUS_URL}/api/v1/query_range?" + urllib.parse.urlencode(
            {"query": query, "start": start, "end": end, "step": cfg["prometheus"]["step"]})
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                result = json.load(resp)["data"]["result"]
        except Exception as e:  # one broken query must not lose the rest of the run's artifacts
            status[name] = f"error: {e}"
            continue
        labels = sorted({k for s in result for k in s["metric"]})
        with (out_dir / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["epoch", "value", *labels])
            for s in result:
                lv = [s["metric"].get(k, "") for k in labels]
                for t, v in s.get("values", []):
                    w.writerow([t, v, *lv])
        status[name] = f"{len(result)} series"
    (out_dir / "_queries.json").write_text(json.dumps(
        {"start": start, "end": end, "step": cfg["prometheus"]["step"], "testid": testid,
         "queries": cfg["prometheus"]["queries"], "status": status}, indent=2), encoding="utf-8")
    return status


def container_state(name: str) -> dict:
    r = sh(["docker", "inspect", "--format", "{{json .State}}", name], check=False)
    try:
        s = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": r.stderr.strip()}
    return {k: s.get(k) for k in ("Status", "Running", "OOMKilled", "ExitCode", "StartedAt", "FinishedAt", "Error")}


def summarize_k6(path: Path) -> dict:
    if not path.exists():
        return {}
    m = json.loads(path.read_text(encoding="utf-8"))["metrics"]

    def val(metric: str, key: str):
        return m.get(metric, {}).get("values", {}).get(key)

    return {"http_reqs": val("http_reqs", "count"), "http_req_failed_rate": val("http_req_failed", "rate"),
            "p50_ms": val("http_req_duration", "med"), "p99_ms": val("http_req_duration", "p(99)"),
            # dropped_iterations only appears in the summary when k6 dropped something
            "dropped_iterations": val("dropped_iterations", "count") or 0}


# ---------------------------------------------------------------- one run

def execute_run(cfg: dict, series_id: str, series_dir: Path, item: dict, note: str | None) -> dict:
    test, model, run_id = item["test"], item["model"], item["run_id"]
    tcfg = cfg["tests"][test]
    run_dir = series_dir / run_id
    run_dir.mkdir()  # write-once: fails if the directory exists
    (run_dir / "logs").mkdir()
    rel = f"{series_id}/{run_id}"
    testid = rel
    meta = {"series_id": series_id, "run_id": run_id, "test": test, "model": model, "rep": item["rep"],
            "index": item["index"], "config": f"{test}/{model}", "script": tcfg["script"],
            "endpoint": tcfg["endpoint"], "base_url": tcfg.get("base_url"), "params": tcfg["params"],
            "warmup": tcfg.get("warmup"), "expect": tcfg.get("expect"),
            "java_opts": cfg["java_opts"], "k6": cfg["k6"], "testid": testid, "git": git_state(),
            "host": host_power(), "notes": note, "timestamps": {}, "valid": None, "invalid_reasons": []}
    tstamps = meta["timestamps"]
    reasons = meta["invalid_reasons"]
    stats = DockerStats(run_dir / "docker_stats.csv")
    stats.start()
    target = {"BASE_URL": tcfg["base_url"]} if tcfg.get("base_url") else {}
    try:
        if model == NO_SUT:
            meta["sut"] = None
        else:
            log(f"{run_id}: starting SUT ({model})")
            tstamps["sut_start"] = ts(now_utc())
            env_extra = {"JAVA_OPTS": cfg["java_opts"] or ""}
            # Fresh SUT container for every run (plan section 6); dependencies keep running.
            sh(compose(model) + ["up", "-d", "--no-deps", "--no-build", "--force-recreate", "--wait", "sut"],
               env={**os.environ, **env_extra})
            tstamps["sut_healthy"] = ts(now_utc())
            meta["sut"] = {"image_id": image_id(f"jcmc/{'webflux' if model == 'reactive' else 'mvc'}:dev"),
                           "java_version": sh(["docker", "exec", SUT_CONTAINER, "java", "-version"],
                                              check=False).stderr.strip()}

        ws = None
        w = tcfg.get("warmup")
        if w:
            log(f"{run_id}: warm-up {w['duration_s']} s @ {w['rate']}/s")
            rc, ws, we = run_k6(cfg, model, "warmup.js",
                                {**target, "ENDPOINT": tcfg["endpoint"], "RATE": w["rate"],
                                 "DURATION_S": w["duration_s"]},
                                f"{testid}/warmup", f"{rel}/warmup_summary.json", None,
                                run_dir / "logs" / "k6_warmup.log")
            tstamps["warmup_start"], tstamps["warmup_end"] = ts(ws), ts(we)
            meta["warmup_exit_code"] = rc
            if rc != 0:
                reasons.append(f"warm-up k6 exit code {rc}")

        log(f"{run_id}: scenario {tcfg['script']} on {tcfg.get('base_url', '')}{tcfg['endpoint']} "
            f"(~{test_duration_s(tcfg)} s)")
        env = {**target, "ENDPOINT": tcfg["endpoint"], **tcfg["params"]}
        raw = f"{rel}/k6_raw.csv.gz" if cfg["k6"]["raw_csv"] else None
        rc, rs, re_ = run_k6(cfg, model, tcfg["script"], env, testid, f"{rel}/k6_summary.json", raw,
                             run_dir / "logs" / "k6.log")
        tstamps["run_start"], tstamps["run_end"] = ts(rs), ts(re_)
        meta["k6_exit_code"] = rc
        if rc != 0:
            reasons.append(f"k6 exit code {rc}")
        time.sleep(SETTLE_S)

        # SUT failure (exit, OOM kill) is a result for H3, not an invalid run.
        meta["sut_state_after"] = container_state(SUT_CONTAINER) if model != NO_SUT else None
        log(f"{run_id}: exporting Prometheus window")
        meta["prometheus_export"] = export_prometheus(cfg, testid, (ws or rs).timestamp(),
                                                      re_.timestamp() + SETTLE_S, run_dir / "prom")
        meta["k6_result"] = summarize_k6(run_dir / "k6_summary.json")

        v = cfg["validation"]
        if not (run_dir / "k6_summary.json").exists():
            reasons.append("k6_summary.json missing")
        dropped = meta["k6_result"].get("dropped_iterations", 0)
        if dropped > v["max_dropped_iterations"]:
            reasons.append(f"k6 dropped {dropped} iterations (max {v['max_dropped_iterations']})")
        k6_cpu = stats.cpu_p95(K6_CONTAINER, rs.timestamp(), re_.timestamp())
        meta["k6_cpu_p95_pct"] = k6_cpu
        if k6_cpu is None:
            reasons.append("no docker stats samples for the k6 container")
        elif k6_cpu > v["k6_cpu_p95_max_pct"]:
            reasons.append(f"k6 CPU p95 {k6_cpu:.0f}% > {v['k6_cpu_p95_max_pct']}%")
        meta["k6_mem_max_bytes"] = stats.mem_max(K6_CONTAINER, rs.timestamp(), re_.timestamp())
        meta["fake_api_cpu_p95_pct"] = stats.cpu_p95(FAKE_API_CONTAINER, rs.timestamp(), re_.timestamp())
        # Optional per-test expectations, used by the smoke capacity checks (fake API must hold its delay).
        exp = tcfg.get("expect") or {}
        r = meta["k6_result"]
        if "p99_max_ms" in exp and (r.get("p99_ms") is None or r["p99_ms"] > exp["p99_max_ms"]):
            reasons.append(f"p99 {r.get('p99_ms')} ms > expected {exp['p99_max_ms']} ms")
        if "failed_rate_max" in exp and (r.get("http_req_failed_rate") is None
                                         or r["http_req_failed_rate"] > exp["failed_rate_max"]):
            reasons.append(f"failed rate {r.get('http_req_failed_rate')} > expected {exp['failed_rate_max']}")
    except KeyboardInterrupt:
        reasons.append("aborted by user")
        raise
    except Exception as e:
        reasons.append(f"runner error: {e!r}")
        log(f"{run_id}: runner error: {e!r}")
    finally:
        stats.stop()
        first = tstamps.get("sut_start") or tstamps.get("warmup_start") or tstamps.get("run_start") or {}
        logs = [("fake-api", FAKE_API_CONTAINER, first.get("iso"))]
        if model != NO_SUT:
            logs.insert(0, ("sut", SUT_CONTAINER, None))
        for name, cont, since in logs:
            args = ["docker", "logs", "--timestamps"] + (["--since", since] if since else []) + [cont]
            r = sh(args, check=False)
            (run_dir / "logs" / f"{name}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if model != NO_SUT:
            sh(compose(model) + ["stop", "sut"], check=False)
        sh(["docker", "rm", "-f", K6_CONTAINER], check=False)
        meta["valid"] = not reasons
        tstamps["collected"] = ts(now_utc())
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "runner" / "experiments.yaml")
    ap.add_argument("--only", action="append", default=[], metavar="TEST/MODEL",
                    help="restrict to configurations: s2-cpu/virtual, s1-io (all models), 'cap-*' (glob, repeatable)")
    ap.add_argument("--reps", type=int, help="repetitions per configuration (default: reps from config)")
    ap.add_argument("--seed", type=int, help="seed for the run order (default: random, recorded)")
    ap.add_argument("--kind", choices=KINDS, default="dev", help="series kind, see results/README.md")
    ap.add_argument("--label", help="optional series label [a-z0-9-]")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", dest="overrides",
                    help="override a config value, e.g. tests.s1-io.params.MAX_RATE=500")
    ap.add_argument("--note", help="free-text note stored in every meta.json (hygiene deviations etc.)")
    ap.add_argument("--allow-dirty", action="store_true", help="allow a main series with uncommitted changes")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    a = ap.parse_args()

    if a.label and not re.fullmatch(r"[a-z0-9-]+", a.label):
        sys.exit("--label must match [a-z0-9-]+")
    cfg = load_config(a.config, a.overrides)
    reps = a.reps or cfg["reps"]
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(2 ** 31)
    plan = build_plan(cfg, a.only, reps, seed)
    if not plan:
        sys.exit("empty plan")
    models = sorted({p["model"] for p in plan})
    est = sum(test_duration_s(cfg["tests"][p["test"]]) + warmup_s(cfg["tests"][p["test"]])
              + PER_RUN_OVERHEAD_S for p in plan) + cfg["cooldown_s"] * (len(plan) - 1)

    if a.dry_run:
        print(f"series: results/{dt.date.today():%Y-%m-%d}_{a.kind}{'-' + a.label if a.label else ''}  "
              f"seed={seed}  runs={len(plan)}  estimated {est / 3600:.1f} h")
        for p in plan:
            t = cfg["tests"][p["test"]]
            print(f"  {p['run_id']:<34} {t['script']:<16} {t['endpoint']:<5} ~{test_duration_s(t)} s  {t['params']}")
        if a.overrides:
            print(f"overrides: {a.overrides}")
        return

    git = git_state()
    if a.kind == "main" and git["dirty"] and not a.allow_dirty:
        sys.exit("main series needs a clean git tree (commit first) or --allow-dirty")
    series_id = series_id_for(a.kind, a.label)
    series_dir = RESULTS / series_id
    series_dir.mkdir(parents=True)
    # The base config is stored as experiments.yaml, an extending config (e.g. smoke.yaml) under its own name.
    for i, f in enumerate(config_files(a.config)):
        shutil.copy(f, series_dir / ("experiments.yaml" if i == 0 else f.name))
    with (series_dir / "invalid_runs.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["run_id", "reason"])
    log(f"series {series_id}: {len(plan)} runs, seed {seed}, estimated {est / 3600:.1f} h")

    log(f"building images for {models}")
    sh(compose(NO_SUT) + ["build", "fake-api"])
    for m in models:
        if m != NO_SUT:
            sh(compose(m) + ["build", "sut"])
    log("starting fake-api and Prometheus")
    sh(compose(NO_SUT) + ["up", "-d", "--wait", "fake-api", "prometheus"])

    series = {"series_id": series_id, "kind": a.kind, "label": a.label, "seed": seed, "reps": reps,
              "only": a.only, "overrides": a.overrides, "effective_config": cfg, "notes": a.note,
              "argv": sys.argv[1:], "git": git, "started": ts(now_utc()), "status": "running",
              "estimated_s": est, "versions": series_versions(cfg), "host": host_power(),
              "plan": plan, "runs": []}
    series_path = series_dir / "series.json"

    def save_series():
        series_path.write_text(json.dumps(series, indent=2, ensure_ascii=False), encoding="utf-8")

    save_series()
    try:
        for n, item in enumerate(plan, start=1):
            log(f"=== run {n}/{len(plan)}: {item['run_id']}")
            meta = execute_run(cfg, series_id, series_dir, item, a.note)
            r = meta.get("k6_result", {})
            log(f"{item['run_id']}: valid={meta['valid']} reqs={r.get('http_reqs')} "
                f"failed={r.get('http_req_failed_rate')} p99={r.get('p99_ms')} ms "
                f"k6_cpu_p95={meta.get('k6_cpu_p95_pct')}% {meta['invalid_reasons'] or ''}")
            series["runs"].append({"run_id": item["run_id"], "valid": meta["valid"],
                                   "invalid_reasons": meta["invalid_reasons"]})
            if not meta["valid"]:
                with (series_dir / "invalid_runs.csv").open("a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([item["run_id"], "; ".join(meta["invalid_reasons"])])
            save_series()
            if n < len(plan):
                log(f"cool-down {cfg['cooldown_s']} s")
                time.sleep(cfg["cooldown_s"])
        series["status"] = "finished"
    except KeyboardInterrupt:
        series["status"] = "aborted"
        log("aborted by user")
    finally:
        series["finished"] = ts(now_utc())
        save_series()
        sh(compose(NO_SUT) + ["down"], check=False)
    invalid = [r["run_id"] for r in series["runs"] if not r["valid"]]
    log(f"series {series_id} {series['status']}: {len(series['runs'])} runs, {len(invalid)} invalid {invalid or ''}")


if __name__ == "__main__":
    main()
