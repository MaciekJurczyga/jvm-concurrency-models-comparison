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

Requires Docker (and JDK 25 for local builds only). Commands run from the repo root.

```sh
./mvnw verify                                          # build + tests (Windows: mvnw.cmd)

# Whole stack for one model: fake-api, Prometheus, Grafana and the SUT (model = platform | virtual | reactive)
docker compose -f infra/docker-compose.yml --env-file infra/models/virtual.env up -d --build --wait
curl http://localhost:8080/io                          # {"upstreamDelayMs":100}
curl http://localhost:8080/cpu                         # {"matches":true}
curl http://localhost:8080/diag/thread                 # {"thread":"VirtualThread[...]","virtual":true}
curl "http://localhost:8090/delay?ms=200"              # fake API: {"delayMs":200} after ~200 ms

# Switch the model: the same command with another env file recreates the single "sut" container
docker compose -f infra/docker-compose.yml --env-file infra/models/reactive.env up -d --build --wait

# Short k6 check with metrics pushed to Prometheus (ENDPOINT, RATE, DURATION overridable with -e)
docker compose -f infra/docker-compose.yml --env-file infra/models/reactive.env   run --rm k6 run -o experimental-prometheus-rw --tag testid=dev-smoke /load/scenarios/smoke.js

docker compose -f infra/docker-compose.yml --env-file infra/models/reactive.env down
```

Every Compose command needs `--env-file infra/models/<model>.env` (without it Compose stops with an error; DECISIONS.md, D16).
Live view: Prometheus <http://localhost:9090>, Grafana <http://localhost:3000> (Explore, no login).

SUT endpoints: `GET /io`, `GET /cpu`, `GET /diag/thread`, `GET /actuator/health`, `GET /actuator/prometheus`.
Environment: `UPSTREAM_URL`, `IO_DELAY_MS` (100), `UPSTREAM_TIMEOUT` (5s), `BCRYPT_COST` (10), `JAVA_OPTS` (empty). See `docs/DECISIONS.md`.

Results layout and naming: [`results/README.md`](results/README.md).
