# Artifacts

Each experiment gets a fresh `.dojo/domains/{id}/runs/{eid}/artifacts/` directory. The runner passes its path as `artifacts_dir` to **both** `train()` and `evaluate()`.

- **`evaluate(..., artifacts_dir)` writes durable per-run diagnostics** — residual plots, calibration curves, error breakdowns. These are produced on every run and are part of the user-defined evaluation contract in `SETUP.md`.
- **`train(..., artifacts_dir)` writes opportunistic artifacts** — model checkpoints (`joblib.dump(model, artifacts_dir / "model.pkl")`), training curves, feature importances. The agent decides when an artifact is worth keeping; not every run will write here.

Everything written to `artifacts_dir` is:

1. Copied into the durable Dojo archive at `.dojo/artifacts/experiments/{eid}/...`.
2. Forwarded to the active tracking backend (`MlflowTracker.log_artifact` uploads to MLflow; `FileTracker` records a reference; `NoopTracker` drops it).

See [CLAUDE.md](../CLAUDE.md) for the architectural details (per-experiment ingest in [src/dojo/tools/experiments.py](../src/dojo/tools/experiments.py) `_ingest_artifacts`, the artifact-store interface, the tracking adapter dispatch).
