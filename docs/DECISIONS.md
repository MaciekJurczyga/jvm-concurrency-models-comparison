# Design decisions

Each entry: decision, rationale, consequences. Code comments refer to entries as `DECISIONS.md, Dn`.
Status: **accepted** (in force), **provisional** (default until the pilot, E7), **open**.

## D1. Platform versions — accepted (2026-11-15)

Java 25 (Eclipse Temurin 25.0.5+8 LTS), Spring Boot 4.1.2 (latest GA on start.spring.io on 2026-11-15, supports Java 25), Maven 3.9.16 via Maven Wrapper.
All modules inherit the Boot version from the root `pom.xml`, so every service uses identical Spring, Reactor, Netty, Tomcat and Micrometer versions.

## D2. Two code bases for three models — accepted (2026-11-15)

`apps/mvc` serves both the platform-threads and the virtual-threads model; they differ only in `spring.threads.virtual.enabled` (Spring profiles `platform` / `virtual`).
`apps/webflux` is the reactive model. The thread model is then the only variable between the two MVC configurations.

## D3. Fake API: WebFlux with `Mono.delay` — accepted (2026-11-15)

`GET /delay?ms=N` (0 ≤ N ≤ 60000, otherwise 400) returns `{"delayMs":N}` after N ms.
`Mono.delay` registers a timer instead of occupying a thread, so the dependency can hold far more concurrent requests than any SUT and should not become the bottleneck.
This must still be confirmed at maximum rates in the pilot (E6/E7: delay held within a few ms).
The fake API has its own CPU set (`4-5`), disjoint from the SUT.

## D4. One shared Dockerfile, pinned images — accepted (2026-11-15)

`Dockerfile` at the repo root builds any module via `--build-arg MODULE=...`: build stage `eclipse-temurin:25.0.5_8-jdk`, runtime `eclipse-temurin:25.0.5_8-jre` (Ubuntu).
Exact tags, never `latest` (Papadopoulos et al., reproducibility). `curl` is added to the runtime image only for Compose healthchecks; it is identical in all images.
k6 is pinned likewise (`grafana/k6:2.4.0`).

## D5. JVM flags common to all services — accepted (2026-11-15)

`JVM_BASE_OPTS="-XX:+UseG1GC -XX:MaxRAMPercentage=75"`, set in the shared Dockerfile.
G1 is forced explicitly because the JVM's ergonomics pick SerialGC when the container has fewer than 2 CPUs or less than 1792 MB of memory. The SUT is planned with `mem_limit: 1g`, so without the flag it would silently run SerialGC.
The heap is sized relative to the container limit, so changing `mem_limit` scales it consistently.
CPU count is detected from the container (`ActiveProcessorCount` left at default).

## D6. Behaviour on OutOfMemoryError — provisional (2026-11-15)

Default: **no** `-XX:+ExitOnOutOfMemoryError`. We observe degradation rather than kill the process, since H3 asks how each model fails.
It can be switched per run through `JAVA_OPTS` without rebuilding the image. The SUT will have no Compose restart policy: an automatic restart during a run would distort time-to-recovery.
Final decision after the pilot (E7, plan section 9 item 3).

## D7. MVC HTTP client to the fake API — accepted (2026-11-15)

`RestClient` built directly (`RestClient.builder()`, not Boot's auto-configured builder) over `JdkClientHttpRequestFactory` with an explicit `java.net.http.HttpClient`:
- HTTP/1.1 forced (the JDK default is HTTP/2, which on `http://` means an h2c upgrade attempt); WebFlux will also talk HTTP/1.1 to the fake API;
- connect timeout and read timeout = `UPSTREAM_TIMEOUT` (default 5 s), the same value WebFlux will use;
- the JDK client's connection pool has no per-host limit, so the client cannot cap concurrency below the server's own limits (unlike Apache HttpClient defaults, or the Reactor Netty pool, which must be raised explicitly in E3).

`/io` calls `GET {UPSTREAM_URL}/delay?ms={IO_DELAY_MS}` (default 100 ms) and returns `{"upstreamDelayMs":100}`.

## D8. bcrypt in `/cpu`: `matches()` against a precomputed hash — accepted (2026-11-15)

`spring-security-crypto` only (`BCryptPasswordEncoder`, no Spring Security filter chain). The hash of a constant password is computed once at startup with cost `BCRYPT_COST`; each request runs `matches()`, which costs the same as `encode()`.
`encode()` would draw a fresh salt from a shared `SecureRandom` on every request, an extra synchronisation point unrelated to the concurrency model. Response: `{"matches":true}`.
Cost is provisionally 10: a single request in the container (4 CPUs) takes about 65–80 ms end-to-end, within the planned 50–100 ms. Final calibration in E7.

## D9. Tomcat settings and the platform/virtual profiles — accepted (2026-11-15)

Pinned in `application.yml` for both profiles (they equal Boot defaults): `threads.max=200`, `threads.min-spare=10`, `accept-count=100`, `max-connections=8192`.
Profile `platform` sets `spring.threads.virtual.enabled=false`, profile `virtual` sets it to `true`; nothing else differs. In the virtual profile Tomcat runs each request on a new virtual thread, `threads.max` is ignored, and `max-connections` (8192) plus `accept-count` remain the only server-side limits. This matters when interpreting H1 and H3.
`server.tomcat.mbeanregistry.enabled=true` is needed for the `tomcat_threads_*` / `tomcat_connections_*` metrics.

## D10. Upstream failures: 504 / 502 with a fixed body — accepted (2026-11-15)

Dependency timeout → `504 {"error":"upstream_timeout"}`; any other dependency failure (connection error, 5xx) → `502 {"error":"upstream_error"}`.
k6 can then separate dependency timeouts from other dependency errors and from the server's own failures (connection refused, 503, client-side timeout). WebFlux must map errors identically.

## D11. Diagnostics and concurrency metrics — accepted (2026-11-15)

`GET /diag/thread` returns the handling thread and `isVirtual()`. It is a separate endpoint so that `/io` and `/cpu` responses stay byte-identical across models (contract test, E6). Verified in Docker: `platform` → `http-nio-8080-exec-*`, `virtual` → `VirtualThread[...tomcat-handler-*]`.
Every metric carries the tags `application` and `model` (`platform` / `virtual`; `reactive` in WebFlux).
In the virtual profile `tomcat_threads_busy_threads` and `tomcat_threads_config_max_threads` report `-1` (there is no thread pool). The model-independent measure of in-flight requests is `http_server_requests_active_seconds_count`, which WebFlux exposes as well; `tomcat_connections_current_connections` complements it for MVC.

## D12. WebFlux HTTP client to the fake API — accepted (2026-11-15)

`WebClient` built directly over a Reactor Netty `HttpClient` with an explicit `ConnectionProvider` named `fake-api`:
- `maxConnections = 10000` (`UPSTREAM_MAX_CONNECTIONS`), above Tomcat's `max-connections` (8192), so the client pool never caps concurrency below what the MVC server itself allows. The Reactor Netty default is `max(2 × CPUs, 16)`, i.e. 16 in a 4-CPU container, which would cap `/io` at roughly 160 req/s with a 100 ms dependency;
- `pendingAcquireMaxCount = -1` (unbounded queue of requests waiting for a connection) and `pendingAcquireTimeout = UPSTREAM_TIMEOUT`;
- HTTP/1.1, connect timeout and response timeout = `UPSTREAM_TIMEOUT`, as in MVC (D7).

Timeouts (response, connect, pool acquire) map to 504 and other `WebClientException`s to 502, with the same bodies as MVC (D10).
Sanity check (not a measurement): warm containers at 1500 req/s for 10 s on `/io` gave med ≈ 101 ms / p99 ≈ 114 ms (WebFlux) and med ≈ 102 ms / p99 ≈ 117 ms (MVC platform). A cold first run was about 3× slower in both, so warm-up before each run is essential (plan section 6).

## D13. bcrypt in WebFlux on `Schedulers.parallel()` — accepted (2026-11-15)

`Mono.fromCallable(() -> encoder.matches(...)).subscribeOn(Schedulers.parallel())`. Closes plan section 9 item 2.
`parallel()` is Reactor's scheduler for CPU-bound work: one thread per CPU (4 in the SUT container) and an unbounded task queue. Under S2-CPU WebFlux therefore keeps accepting requests and queues hashing work, which is the behaviour H3 predicts for the reactive model.
Rejected: `boundedElastic()` (10 × CPUs threads, queue capped at 100 000 tasks; meant for blocking calls and would behave more like a thread pool); running on the event loop (deliberately wrong variant, kept for the thesis, plan section 8).
This choice directly shapes the S2-CPU result and must be described in the methodology.

## D14. One event-loop group shared by server and client — accepted (2026-11-15)

The server runs on the loop resources of Spring's `ReactorResourceFactory`. A `WebClient` built directly via `HttpClient.create(...)` would get Reactor Netty's separate global loop, so the SUT would run two event-loop groups (8 threads on 4 CPUs).
The client therefore calls `runOn(reactorResourceFactory.getLoopResources())`, which is what Boot's auto-configured `WebClient` does. A test asserts there is exactly one event-loop group; it fails when `runOn` is removed (checked).
Loop size is left at the Reactor Netty default `max(CPUs, 4)`, which is 4 in the container. Verified there: `nproc` = 4, 4 `reactor-http-epoll-*` threads (Linux uses the epoll transport; the Windows test JVM shows `webflux-http-nio-*`).
The container also runs a few `boundedElastic-*` threads, used by actuator health checks, not by `/io` or `/cpu`.

## D15. No blocking on event-loop threads: BlockHound plus a scheduler test — accepted (2026-11-15)

BlockHound 1.0.18 (`blockhound-junit-platform`) is installed in all WebFlux tests. It works on Java 25 with `-XX:+AllowRedefinitionToAddDeleteMethods` (surefire `argLine`; the flag is deprecated, JVM warns). A dedicated test proves that BlockHound is active.
BlockHound only detects blocking calls (sleep, socket I/O, locks), not CPU-heavy work, so a separate test checks that bcrypt emits on a `parallel-*` thread.
The endpoint tests (`/io`, `/cpu`, errors, actuator) run under BlockHound with no violations.

## D16. Measurement stack in Compose: one `sut` service, Prometheus, Grafana, k6 — accepted (2026-11-16)

**SUT selection.** Compose has a single service `sut`, parametrised by an env file `infra/models/<model>.env` (`SUT_MODULE`, `SUT_SPRING_PROFILE`):
`docker compose -f infra/docker-compose.yml --env-file infra/models/<platform|virtual|reactive>.env up -d --build --wait`.
A first attempt with one service per model selected by Compose profiles was rejected: switching the profile does not stop the previous SUT, and two containers sharing the network alias `sut` would split traffic between two models by DNS round-robin, silently (observed in testing). With one service, changing the model recreates the container. Without an env file `SUT_MODULE` defaults to `none`: `down`, `ps` and `logs` work, while `up` fails in the image build with an explicit message (guard in the `Dockerfile`), so a model is never guessed.
The SUT is reachable as `sut:8080` inside the network and `localhost:8080` on the host; Prometheus and k6 never need to know which model runs, the Micrometer tag `model` identifies it (D11).

**Prometheus** `prom/prometheus:v3.16.0`, `cpuset 10-11`: scrapes `sut` and `fake-api` every 1 s (resolution needed for S2 phase transitions) and receives k6 metrics through `--web.enable-remote-write-receiver`. The TSDB sits on the named volume `prometheus-data` with default retention (15 days). It is a safety net for re-exporting a run window; the source of truth is `results/` (D17).

**k6** `grafana/k6:2.4.0`, `cpuset 6-9`, Compose profile `tools`, one-shot via `docker compose run --rm k6 run -o experimental-prometheus-rw ...`; mounts `load/` read-only and `results/`.
Trend metrics are sent as **native histograms** (`K6_PROMETHEUS_RW_TREND_AS_NATIVE_HISTOGRAM=true`, push every 1 s): `histogram_quantile` over any window then uses the full distribution, whereas the default per-flush `p(99)` gauges cannot be aggregated over time. Prometheus 3.16 ingests them without a feature flag.

**Grafana** `grafana/grafana:13.3.1`, `cpuset 10-11`: only the Prometheus datasource is provisioned (live view, no dashboards; plan section 2). Anonymous admin access, ports bound to `127.0.0.1`.

Verified (E4 DoD): for each model, `up` → 20 s k6 smoke at 20 req/s on `/io` → k6 and SUT both count 400–401 requests in Prometheus, k6 p99 from the native histogram ≈ 115–120 ms, exactly one SUT container running, `/diag/thread` matches the model.

## D17. Results layout and naming — accepted (2026-11-16)

Defined in `results/README.md` (binding). In short: `results/<YYYY-MM-DD>_<kind>[-<label>]/<NNN>_<test>_<model>_r<rep>/`, kind ∈ `dev | smoke | pilot | main | rerun`; `results/` is raw and write-once, derived data goes to `analysis/output/<series_id>/`; invalid runs are marked, never deleted; every k6 run carries `testid=<series_id>/<run_id>`.
Grouping runs into series (one runner invocation, one seed) replaces the flat `results/<date>_<scenario>_<model>_r<n>/` sketched in the plan: seed, run order and config snapshot then belong to exactly one directory, and pilot data cannot mix with the main series. `dev` series are git-ignored.

## D18. Load scenarios and the runner — accepted (2026-11-16)

**k6 scripts** (`load/`): one script per scenario, endpoint and rates from env, always an open model (plan section 5).
- `s1_baseline.js`: `ramping-arrival-rate` in steps (0 s jump + hold `STEP_DURATION_S`), not ramps, so each request belongs to exactly one rate level; every request is tagged `stage` and `rate`.
- `s2_flood.js`: three `constant-arrival-rate` scenarios (`before`, `flood`, `after`) chained by `startTime`; every request carries `phase`. The `after` phase gets the same VU budget as the flood by default, so it can keep its arrival rate while flood requests are still pending.
- `warmup.js`: constant rate, used for the warm-up and for manual checks.
- Common (`lib/common.js`): request timeout 10 s (timeout = error), `gracefulStop` 15 s (> timeout) so requests in flight at a phase boundary finish and stay in their phase, `discardResponseBodies` to save k6 CPU, `handleSummary` writes the summary JSON to the path given by the runner.

**Runner** (`runner/run_matrix.py`, config `runner/experiments.yaml`). Per series: snapshot of the config, random interleaved order from a recorded seed, images built once (so code cannot change mid-series), fake-api and Prometheus started once. Per run:
1. `up --force-recreate --no-deps` of `sut` (fresh JVM, plan section 6), wait for the healthcheck;
2. warm-up: a **separate** k6 run on the same endpoint (`warmup_summary.json`, own `testid`), so warm-up data never mixes with the measured run;
3. scenario: `k6_summary.json`, `k6_raw.csv.gz`, remote write tagged `testid=<series_id>/<run_id>`;
4. `docker stats` of all containers streamed through the whole run; `query_range` export (step 1 s) of the queries in `experiments.yaml` from warm-up start to scenario end + 5 s; container logs; `meta.json`;
5. validation, then `stop sut` and cool-down.

**Validity.** A run is invalid when k6 dropped iterations (> 0), the p95 CPU of the k6 container exceeds 320 % (80 % of its 4 CPUs), a k6 process failed, the summary is missing, or the runner hit an error. Invalid runs keep their data and are listed in `invalid_runs.csv` (D17). A SUT that crashes or is OOM-killed is **not** invalid: it is a result for H3 and is recorded in `meta.json` (`sut_state_after`).

**S2 rates are absolute** and shared by all models, separately for `/io` and `/cpu` (plan section 9 item 1, recommended variant accepted 2026-11-16); values come from the pilot (E7).

**Recorded per run:** git commit and dirty files, image IDs, JDK version inside the SUT, all parameters, timestamps, Windows power plan and AC state (measurement hygiene), free-text `--note`. A `main` series refuses to start on a dirty git tree unless `--allow-dirty`.

**Findings for the pilot (E7).**
- k6 initialises VUs beyond `preAllocatedVUs` slowly (about 12 VU/s observed). When latency jumps in a flood, it drops iterations and the run becomes invalid (seen in a short S2-CPU test). `PRE_VUS` must cover the expected peak (`rate × worst latency`, bounded by the 10 s timeout).
- E5 DoD run (`--only s1-io/platform --reps 1`, placeholder parameters, dev series, not a measurement): complete run directory; run correctly marked invalid because k6 dropped 3255 iterations. Drops occurred already at steps where the SUT was healthy (p99 ≈ 105–120 ms), i.e. VU initialisation lag with `PRE_VUS: 100`, plus at 2000 req/s where platform threads saturated (p99 rose to ≈ 350–745 ms, matching 200 threads / 0.1 s). Calibrate `PRE_VUS` close to the expected peak.
- The per-request CSV has about 13 rows per request: 148 MB (gz) for one 20-minute S1-IO run, i.e. several GB for the full matrix. k6 CPU p95 was 106 % of 400 %, so it is affordable CPU-wise; decide in E7 whether to keep it (`k6.raw_csv`).
- With the placeholder parameters the full matrix (60 runs) is estimated at about 15.7 h, well above the planned 8–10 h. Mostly S1-IO: 20 steps × 60 s = 20 min per run. Calibration must shorten S1 (narrower range or shorter steps).

## D19. Smoke tests: contract test, capacity checks, 12 short runs — accepted (2026-11-17)

**Contract test** (`runner/contract_test.py`). Each model is started fresh in Compose and probed from the host. Compared per case: status, `Content-Type`, body bytes, framing (`Content-Length` vs chunked), against a fixed expected body as well as across models. Cases: `/io` → 200 `{"upstreamDelayMs":100}` (23 B), `/cpu` → 200 `{"matches":true}` (16 B), upstream port closed → 502 `{"error":"upstream_error"}` (26 B), upstream slower than the timeout (`IO_DELAY_MS=3000`, `UPSTREAM_TIMEOUT=1s`, test-only override file) → 504 `{"error":"upstream_timeout"}` (28 B). It also checks health, the `model` tag in `/actuator/prometheus` and the thread kind via `/diag/thread`.
Two findings, both fixed:
- MVC sent the 502/504 bodies **chunked**, WebFlux with `Content-Length`. The `ResponseEntity` return path flushes the response before Tomcat knows the length. The handler now sets the status on `HttpServletResponse` and returns the record, like `/io`; the MVC test asserts `Content-Length`. Bodies and status codes were already identical; only the framing (and so the bytes on the wire for error responses in S2) differed.
- Stopping the fake API does not produce a 502: Docker DNS for a stopped container does not fail fast, so all three models waited for the timeout and answered 504. The 502 case therefore points the SUT at a closed port (`http://fake-api:9`, connection refused).
Report: `results/2026-11-17_smoke-contract/contract_report.json`.

**Runner extensions** for the smoke series (no change to how measured runs execute):
- `extends:` in a config file, deep-merged into the base. `runner/smoke.yaml` lists only differences from `experiments.yaml`, and both files are snapshotted into the series directory.
- Capacity checks without a SUT: a test may declare `models: [none]` and `base_url` (k6 then targets the fake API directly), `warmup: null`, and `expect` (`p99_max_ms`, `failed_rate_max`, extra validity conditions). `--only` accepts globs (`'cap-*'`, `s1-io` = all models).
- `meta.json` also records the k6 container's peak memory and the fake API container's CPU p95. Prometheus export adds `fake_api_max_latency`.
- `s2_flood.js`: separate `NORMAL_PRE_VUS` for the before/after phases. Each phase is its own k6 scenario with its own VU pool, all preallocated at start, so one `PRE_VUS` for all three phases tripled k6 memory. `warmup.js` accepts `PRE_VUS`.

**Capacity checks** (series `2026-11-17_smoke-capacity` with k6 raw CSV, `…-capacity-nocsv` without; k6 straight at `fake-api/delay?ms=100`, 30 s at a constant rate after a 15 s warm-up; laptop on the balanced power plan, so indicative only). All runs failed their strict criteria (0 dropped, p99 ≤ 120 ms):

| rate | raw CSV | k6 p50 / p99 | dropped | k6 CPU p95 (of 400 %) | k6 mem | fake API mean latency (max of 1 s windows) | fake API `process_cpu_usage` max |
|---|---|---|---|---|---|---|---|
| 6000/s | yes | 101 / 207 ms | 340 | 260 % | 754 MB | 102 ms | 0.83 |
| 6000/s | no | 100 / 113 ms | 121 | 211 % | 504 MB | 100 ms | 0.45 |
| 8000/s | yes | 101 / 217 ms | 364 | 261 % | 1019 MB | 101 ms | 0.70 |
| 8000/s | no | 100 / 159 ms | 949 | 255 % | 643 MB | 101 ms | 0.77 |
| 10000/s | yes | 108 / 491 ms | 20306 | 320 % | 1480 MB | 104 ms | 0.98 |
| 10000/s | no | 101 / 292 ms | 5979 | 304 % | 821 MB | 102 ms | 0.89 |

Conclusions:
1. **Fake API** keeps its delay on the server side (mean 100–104 ms) up to 10000/s, but on its 2 CPUs it is close to saturation at 10000/s. Up to about 8000/s it is not the bottleneck.
2. **k6 raw CSV** costs latency accuracy: at 6000/s client p99 goes from 113 ms to 207 ms, and k6 memory grows throughout the run. Decide in E7 (recommendation: off for S2-IO; Prometheus native histograms + summary give the per-window percentiles).
3. **Dropped iterations at scenario start.** At 6000–8000/s k6 drops ~120–360 iterations in the first second(s) of a constant-rate scenario although most preallocated VUs are idle; at 8000/s there were also mid-run bursts with a VU spike. Under the strict rule (0 dropped) every high-rate run, including each S2 flood start, would be invalid. E7 decision: a relative limit (e.g. ≤ 0.1 % of iterations) or a short ramp at phase start.
4. **Harness tail at high rates.** Even without CSV, client p99 at 8000/s is ~130–160 ms against a server-side 100 ms. S1-IO saturation thresholds (p99 < X ms) must sit well above this, or S1-IO must stay below ~6000/s.
5. **k6 VU capacity** (`cap-k6-vus18000`: 2000/s on a 9 s response = 18000 concurrent requests, 20000 preallocated VUs): ~4.1–4.8 GB of k6 memory (~240 KB per VU), k6 CPU saturated (p95 377–394 %), p50 9.0–9.8 s instead of 9.0 s, 6–62 % timeouts while all 18000 connections open within 9 s. Steady state after that held (p50 ≈ 9.0 s). About 15000–20000 pending requests is the upper bound of the load generator on this laptop. In an S2 flood that the SUT does not absorb, k6 needs `rate × request timeout` VUs (e.g. 4000/s × 10 s = 40000), which is out of reach. E7 must bound flood rate × timeout (a shorter k6 timeout, a lower flood rate, or accepting drops in the flood phase as a documented limitation).

**Smoke series** `2026-11-17_smoke` (12 configurations × 1, 30 s scenario after a 15 s warm-up, `runner/smoke.yaml`; S1 in three 10 s steps, S2 as 10 s before / 10 s flood / 10 s after; floods at /io 2200/s and /cpu 80/s). Every run produced a complete directory (summary, raw CSV, 23 Prometheus exports without errors, docker stats, logs, `meta.json`). No SUT crashed. 11 of 12 runs were valid on the first try:
- S1-IO (500→1500/s): p99 107–113 ms in all three models; S1-CPU (10→40/s): p50 61–62 ms, p99 79–90 ms;
- S2-CPU: p99 4.1 s (reactive), 4.5 s (virtual), 6.7 s (platform), no errors; S2-IO: p99 133 ms (reactive), 230 ms (virtual), no errors.
- `011_s2-io_platform_r1` was **invalid**: 415 dropped iterations once active flood VUs reached `PRE_VUS` = 3000 (platform p50 ≈ 1.4 s at 2200/s needs ~3100 VUs, and k6 adds VUs mid-test too slowly, D18). Rerun `2026-11-17_rerun-smoke1117` (`PRE_VUS` 5000): 52 dropped at the start of the `after` phase (the post-flood backlog made after-phase requests take ~2 s, and 500/s × 2 s > `NORMAL_PRE_VUS` 1000). Rerun `2026-11-17_rerun-smoke1117-2` (`PRE_VUS` 5000, `NORMAL_PRE_VUS` 2500): valid, but 1808 k6 timeouts (5.6 %) in the `after` phase, explained below.

Findings from the smoke series for E7:
6. **Every preallocated VU opens its own keep-alive connection.** k6 rotates iterations over the whole VU pool, so with `NORMAL_PRE_VUS` 2500 Tomcat already held 2502 connections before the flood at 500/s, 7502 during it, and the new after-phase VUs pushed it past `max-connections` = 8192. The surplus waited in the accept queue (`accept-count` 100) and timed out after 10 s. The first run, with ~5000 connections in total, had no errors. **The number of TCP connections to the SUT is set by k6's VU budget, not by the load**, and it interacts directly with Tomcat's `max-connections` (H1/H3, D9). E7 has to set VU budgets deliberately (identical for all models within a test) and report the connection count, or change connection reuse in k6.
7. **Each phase needs `rate × worst latency` preallocated VUs**, including the `after` phase (post-flood backlog), otherwise k6 drops iterations.
8. **SUT metrics have gaps under overload in the platform model.** The Prometheus scrape of `/actuator/prometheus` waits in the same 200-thread Tomcat pool and misses its 1 s timeout, so `sut_*` series are empty during the platform flood (e.g. 6 s gap in `011`). Client-side k6 metrics are unaffected. Options for E7: separate management port (own connector/thread pool), longer scrape timeout, or accept and document the gap.

## Open
- S2 rate values, phase lengths, k6 VU budgets, OOM behaviour (D6) — calibrate in the pilot (E7).
- From D19: raw CSV on/off, rule for dropped iterations at phase start, harness tail vs S1-IO threshold, flood rate × timeout vs k6 VU capacity, connection count set by k6 VU budgets vs Tomcat `max-connections`, per-phase VU preallocation, SUT scrape gaps in the platform model.
