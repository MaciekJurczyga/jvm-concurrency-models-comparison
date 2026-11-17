# Results: layout and naming convention

Binding for people and for tools (runner, analysis, Claude sessions). Decision record: `docs/DECISIONS.md`, D17.

## Rules

1. **`results/` holds raw data only, written once.** Nothing here is edited, renamed or overwritten after a run ends. The runner refuses to write into an existing directory.
2. **Derived data lives elsewhere:** tables, aggregates and figures go to `analysis/output/<series_id>/`. Every number in the article must be traceable to a run directory below.
3. **Invalid runs are kept, not deleted.** They are marked `"valid": false` with reasons in `meta.json` and listed in the series' `invalid_runs.csv`. Analysis skips them.
4. **One series = one invocation of `runner/run_matrix.py`** (one seed, one experiment config). A repeat of invalid runs is a new series of kind `rerun`.

## Layout

```
results/
├── README.md                              # this file
└── <series_id>/                           # e.g. 2026-11-28_main
    ├── series.json                        # seed, planned order, git commit, start/end, host notes
    ├── experiments.yaml                   # snapshot of runner/experiments.yaml used for this series
    ├── smoke.yaml                         # snapshot of an extending config, if one was used (e.g. runner/smoke.yaml)
    ├── invalid_runs.csv                   # run_id, reason (header only if all runs are valid)
    └── <run_id>/                          # e.g. 007_s2-cpu_virtual_r3
        ├── meta.json                      # versions, parameters, timestamps, validity, notes
        ├── k6_summary.json                # k6 end-of-test summary (measured scenario only)
        ├── k6_raw.csv.gz                  # k6 per-request data          (not in git)
        ├── warmup_summary.json            # k6 summary of the discarded warm-up
        ├── docker_stats.csv               # per-second CPU/memory of all containers
        ├── prom/<query_name>.csv          # Prometheus query_range export (warm-up start .. scenario end + 5 s)
        ├── prom/_queries.json             # the PromQL used, export window and per-query status
        └── logs/<service>.log             # container logs                (not in git)
```

## Names

**`series_id` = `<YYYY-MM-DD>_<kind>[-<label>]`**, date of the series start.

| kind | Purpose | In git |
|---|---|---|
| `dev` | ad hoc runs while developing the runner/scenarios; never analysed | no (whole directory ignored) |
| `smoke` | short correctness runs and capacity checks (E6) | yes |
| `pilot` | calibration runs (E7) | yes |
| `main` | the measurement series reported in the article (E8) | yes |
| `rerun` | repeats of invalid runs from a `main` series; `label` names it, e.g. `2026-11-30_rerun-main1128` | yes |

`label` is optional, lowercase `[a-z0-9-]`, used when kind + date is ambiguous (e.g. two pilots on one day: `2026-11-20_pilot-io`, `2026-11-20_pilot-cpu`).

**`run_id` = `<NNN>_<test>_<model>_r<rep>`**

| Part | Values | Meaning |
|---|---|---|
| `NNN` | `001`, `002`, … | execution order within the series (randomised, plan section 6); sorting by name = chronological order |
| `test` | `s1-io`, `s1-cpu`, `s2-io`, `s2-cpu` | scenario × endpoint (plan section 5) |
| | `cap-*` (smoke only) | capacity check of k6 / the fake API without a SUT, defined in `runner/smoke.yaml` (D19) |
| `model` | `platform`, `virtual`, `reactive` | concurrency model = env file `infra/models/<model>.env` |
| | `none` | no SUT running (capacity checks only) |
| `rep` | `r1` … `r5` | repetition of this test/model within the series |

The configuration of a run is `<test>/<model>` (e.g. `s2-cpu/virtual`), the same notation as `run_matrix.py --only`.

## Contract test

`runner/contract_test.py` (E6, D19) writes `results/<YYYY-MM-DD>_smoke-contract/contract_report.json`: one file, no run directories, same write-once rule.

## Link to Prometheus

Every k6 run is tagged `testid=<series_id>/<run_id>` (warm-up: `.../warmup`), so a run can be found in Prometheus/Grafana as long as the `prometheus-data` volume exists (default retention 15 days). Prometheus is a safety net for re-exporting a metric missed in `prom/`; the files here are the source of truth.
