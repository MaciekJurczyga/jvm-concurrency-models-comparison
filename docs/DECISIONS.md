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
A first attempt with one service per model selected by Compose profiles was rejected: switching the profile does not stop the previous SUT, and two containers sharing the network alias `sut` would split traffic between two models by DNS round-robin, silently (observed in testing). With one service, changing the model recreates the container. Without an env file Compose stops with an error instead of guessing a model.
The SUT is reachable as `sut:8080` inside the network and `localhost:8080` on the host; Prometheus and k6 never need to know which model runs, the Micrometer tag `model` identifies it (D11).

**Prometheus** `prom/prometheus:v3.16.0`, `cpuset 10-11`: scrapes `sut` and `fake-api` every 1 s (resolution needed for S2 phase transitions) and receives k6 metrics through `--web.enable-remote-write-receiver`. The TSDB sits on the named volume `prometheus-data` with default retention (15 days). It is a safety net for re-exporting a run window; the source of truth is `results/` (D17).

**k6** `grafana/k6:2.4.0`, `cpuset 6-9`, Compose profile `tools`, one-shot via `docker compose run --rm k6 run -o experimental-prometheus-rw ...`; mounts `load/` read-only and `results/`.
Trend metrics are sent as **native histograms** (`K6_PROMETHEUS_RW_TREND_AS_NATIVE_HISTOGRAM=true`, push every 1 s): `histogram_quantile` over any window then uses the full distribution, whereas the default per-flush `p(99)` gauges cannot be aggregated over time. Prometheus 3.16 ingests them without a feature flag.

**Grafana** `grafana/grafana:13.3.1`, `cpuset 10-11`: only the Prometheus datasource is provisioned (live view, no dashboards; plan section 2). Anonymous admin access, ports bound to `127.0.0.1`.

Verified (E4 DoD): for each model, `up` → 20 s k6 smoke at 20 req/s on `/io` → k6 and SUT both count 400–401 requests in Prometheus, k6 p99 from the native histogram ≈ 115–120 ms, exactly one SUT container running, `/diag/thread` matches the model.

## D17. Results layout and naming — accepted (2026-11-16)

Defined in `results/README.md` (binding). In short: `results/<YYYY-MM-DD>_<kind>[-<label>]/<NNN>_<test>_<model>_r<rep>/`, kind ∈ `dev | smoke | pilot | main | rerun`; `results/` is raw and write-once, derived data goes to `analysis/output/<series_id>/`; invalid runs are marked, never deleted; every k6 run carries `testid=<series_id>/<run_id>`.
Grouping runs into series (one runner invocation, one seed) replaces the flat `results/<date>_<scenario>_<model>_r<n>/` sketched in the plan: seed, run order and config snapshot then belong to exactly one directory, and pilot data cannot mix with the main series. `dev` series are git-ignored.

## Open
- Absolute vs relative S2 rates (section 9 item 1) — decide in E7.
