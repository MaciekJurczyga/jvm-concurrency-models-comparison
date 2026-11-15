# jvm-concurrency-models-comparison

Research testbed for the thesis *"Analiza bezpieczeństwa i niezawodności modeli współbieżności w serwerowych aplikacjach Java"* (AGH).

It compares how three server concurrency models behave under load and HTTP flood, on I/O-bound and CPU-bound endpoints:

1. Spring MVC + Tomcat, platform threads,
2. Spring MVC + Tomcat, virtual threads,
3. Spring WebFlux + Netty.

Java 25, Spring Boot 4.1.2. Load is generated with k6 in an open model. Metrics are collected by Prometheus.

## Layout

| Path | Content |
|---|---|
| `apps/fake-api` | slow dependency: `GET /delay?ms=N` |
| `apps/mvc` | service under test, Spring MVC + Tomcat; profiles `platform` / `virtual` |
| `apps/webflux` | service under test, Spring WebFlux + Netty |
| `infra/` | Docker Compose, Prometheus, Grafana |
| `load/` | k6 scenarios |
| `runner/`, `analysis/` | Python orchestration and analysis |
| `results/` | measurement runs |
| `docs/` | `DECISIONS.md`, `ENVIRONMENT.md`, `METHODOLOGY.md` |

## Quick start

Requires Docker (and JDK 25 for local builds only).

```sh
./mvnw verify                                          # build + tests (Windows: mvnw.cmd)
docker compose -f infra/docker-compose.yml up -d --build --wait fake-api
curl "http://localhost:8090/delay?ms=200"              # {"delayMs":200} after ~200 ms

docker compose -f infra/docker-compose.yml up -d --build --wait mvc-platform mvc-virtual webflux
curl http://localhost:8081/io                          # {"upstreamDelayMs":100}  (platform threads)
curl http://localhost:8082/cpu                         # {"matches":true}         (virtual threads)
curl http://localhost:8082/diag/thread                 # {"thread":"VirtualThread[...]","virtual":true}
curl http://localhost:8083/io                          # {"upstreamDelayMs":100}  (WebFlux)
```

SUT endpoints: `GET /io`, `GET /cpu`, `GET /diag/thread`, `GET /actuator/health`, `GET /actuator/prometheus`.
Environment: `UPSTREAM_URL`, `IO_DELAY_MS` (100), `UPSTREAM_TIMEOUT` (5s), `BCRYPT_COST` (10). See `docs/DECISIONS.md`.
