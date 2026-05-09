"""Unit tests for configuration loading."""

from dojo.config.settings import MemorySettings, Settings, TrackingSettings


def test_default_tracking_settings() -> None:
    s = Settings()
    assert s.tracking.backend == "file"
    assert s.tracking.enabled is True
    # Default URI ends with /mlruns (may be resolved to absolute path by MLflow)
    assert s.tracking.mlflow_tracking_uri.endswith("mlruns")
    assert s.tracking.mlflow_experiment_name == "dojo"


def test_default_memory_settings() -> None:
    s = Settings()
    assert s.memory.backend == "local"
    assert s.memory.search_limit == 10


def test_tracking_mlflow_settings() -> None:
    t = TrackingSettings(backend="mlflow", mlflow_tracking_uri="http://localhost:5000")
    assert t.backend == "mlflow"
    assert t.mlflow_tracking_uri == "http://localhost:5000"


def test_tracking_disabled() -> None:
    t = TrackingSettings(enabled=False)
    assert t.enabled is False


def test_memory_custom_limit() -> None:
    m = MemorySettings(search_limit=25)
    assert m.search_limit == 25


def test_settings_tolerates_removed_blocks_in_yaml(tmp_path) -> None:
    """A stale `llm:` block from a pre-v0.0.16 config must not crash load.

    Regression: before adding `extra="ignore"` to the Settings model_config,
    users with an old `.dojo/config.yaml` hit a hard ValidationError on
    first run after upgrading because pydantic-settings rejected the
    unknown top-level `llm` key.
    """
    config = tmp_path / "config.yaml"
    config.write_text(
        """\
llm:
  provider: stub
  model: stub
tracking:
  backend: file
"""
    )
    # Must not raise — the `llm` block is silently dropped.
    s = Settings.load(config_path=config)
    assert s.tracking.backend == "file"
    assert not hasattr(s, "llm")


def test_settings_from_yaml(tmp_path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        """\
tracking:
  backend: mlflow
  mlflow_tracking_uri: "http://mlflow:5000"
  mlflow_experiment_name: my-project
memory:
  backend: local
  search_limit: 20
"""
    )
    s = Settings.load(config_path=config)
    assert s.tracking.backend == "mlflow"
    assert s.tracking.mlflow_tracking_uri == "http://mlflow:5000"
    assert s.tracking.mlflow_experiment_name == "my-project"
    assert s.memory.search_limit == 20
