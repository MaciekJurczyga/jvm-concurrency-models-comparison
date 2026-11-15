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

## Open

- bcrypt scheduler in WebFlux (plan section 9 item 2) — decide in E3.
- Absolute vs relative S2 rates (section 9 item 1) — decide in E7.
