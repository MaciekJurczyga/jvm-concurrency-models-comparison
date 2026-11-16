# Environment

Local measurement environment (single laptop). Verified on 2026-11-15.
Every run additionally records exact versions in its own `meta.json`.

## Hardware

| Item | Value |
|---|---|
| CPU | Intel Core i5-11260H @ 2.60 GHz, 6 cores / 12 threads |
| RAM | 15.7 GB (16 893 382 656 B) |
| OS | Windows 11 Home, build 10.0.26200 |

## Software

| Tool | Version | Notes |
|---|---|---|
| JDK (host) | Eclipse Temurin 25.0.5+8 LTS | `JAVA_HOME=C:\Program Files\Eclipse Adoptium\jdk-25.0.5.8-hotspot`; used only for local builds/tests |
| JDK (images) | `eclipse-temurin:25.0.5_8-jdk` / `eclipse-temurin:25.0.5_8-jre` | what actually runs in measurements |
| Maven | 3.9.6 (host), Maven Wrapper in repo | |
| Docker Desktop | Engine 27.4.0, Compose v2.31.0 | WSL2 backend |
| WSL | 3.0.5.0, kernel 6.18.58.1-microsoft-standard-WSL2 | |
| k6 | 2.4.0 (`grafana/k6:2.4.0`) | run as a container, no host install |
| Prometheus | `prom/prometheus:v3.16.0` | container; scrape every 1 s, remote-write receiver for k6 |
| Grafana | `grafana/grafana:13.3.1` | container; datasource only, no dashboards |
| Python | 3.13.5 | runner and analysis |

## WSL2 resources

`%UserProfile%\.wslconfig`:

```ini
[wsl2]
processors=12
memory=12GB
```

Docker reports `NCPU=12`, `MemTotal≈11.7 GiB`. About 3.7 GB RAM remains for Windows.

Container `cpuset` pins to WSL virtual CPUs, not physical cores (methodological limitation, see `METHODOLOGY.md`).
Split set in `infra/docker-compose.yml` (to be verified in the pilot, E7): SUT `0-3` + `mem_limit: 1g`, fake API `4-5`, k6 `6-9`, Prometheus/Grafana `10-11`.

## Measurement hygiene

Before a measurement series:
- laptop on AC power;
- Windows power plan set to **High performance** (default on this machine is "Balanced" – switch before E8);
- browser, IDE and other heavy apps closed;
- cool-down pause between runs (handled by the runner).

Deviations are recorded in the run's `meta.json` (`notes`).

## Verification commands (E0)

```
java -version                       # openjdk 25.0.5 Temurin
docker run --rm hello-world         # "Hello from Docker!"
docker run --rm grafana/k6:2.4.0 version   # k6 v2.4.0
```
