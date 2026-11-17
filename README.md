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

# Short manual k6 check with metrics pushed to Prometheus (Git Bash: prefix with MSYS_NO_PATHCONV=1)
docker compose -f infra/docker-compose.yml --env-file infra/models/reactive.env   run --rm -e ENDPOINT=/io -e RATE=20 -e DURATION_S=30 k6 run -o experimental-prometheus-rw --tag testid=manual /load/scenarios/warmup.js

docker compose -f infra/docker-compose.yml down       # down / ps / logs work without an env file
```

`up` needs `--env-file infra/models/<model>.env` (`--env-file` and `-f` go **before** the subcommand); without it the SUT build stops with an explicit error (DECISIONS.md, D16).
Live view: Prometheus <http://localhost:9090>, Grafana <http://localhost:3000> (Explore, no login).

SUT endpoints: `GET /io`, `GET /cpu`, `GET /diag/thread`, `GET /actuator/health`, `GET /actuator/prometheus`.
Environment: `UPSTREAM_URL`, `IO_DELAY_MS` (100), `UPSTREAM_TIMEOUT` (5s), `BCRYPT_COST` (10), `JAVA_OPTS` (empty). See `docs/DECISIONS.md`.

## Measurement runs

```sh
pip install -r runner/requirements.txt
python runner/run_matrix.py --dry-run                          # plan, order and estimated duration
python runner/run_matrix.py --only s1-io/platform --reps 1     # one configuration (series kind "dev")
python runner/run_matrix.py --kind pilot --reps 3 --seed 42    # all 12 configurations
python runner/run_matrix.py --only s2-cpu/virtual --set tests.s2-cpu.params.FLOOD_RATE=300

python runner/contract_test.py                                  # identical responses from the 3 models (E6)
python runner/run_matrix.py --config runner/smoke.yaml --kind smoke --only 's*'                       # 12 x 30 s
python runner/run_matrix.py --config runner/smoke.yaml --kind smoke --label capacity --only 'cap-*'   # k6 / fake API limits
```

On Windows, if image builds fail with `docker-credential-desktop not found`, reload the system `PATH` in the shell first.

Parameters: `runner/experiments.yaml`. Each run: fresh SUT → warm-up (discarded) → scenario (`load/scenarios/s1_baseline.js` or `s2_flood.js`) → artifacts → validation → cool-down (DECISIONS.md, D18).
Results layout and naming: [`results/README.md`](results/README.md).
