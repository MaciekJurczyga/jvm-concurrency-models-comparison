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

## Open

- bcrypt scheduler in WebFlux (plan section 9 item 2) — decide in E3.
- Absolute vs relative S2 rates (section 9 item 1) — decide in E7.
