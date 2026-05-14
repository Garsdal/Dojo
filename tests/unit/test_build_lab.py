"""Unit tests for build_lab() backend dispatch."""

import pytest

from dojo.api.deps import build_lab
from dojo.config.settings import (
    MemorySettings,
    SandboxSettings,
    Settings,
    StorageSettings,
    TrackingSettings,
)
from dojo.sandbox.docker import DockerSandbox
from dojo.sandbox.local import LocalSandbox
from dojo.storage.local import LocalMemoryStore
from dojo.tracking.file_tracker import FileTracker
from dojo.tracking.noop_tracker import NoopTracker


def test_build_lab_file_tracker(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="file", enabled=True),
        memory=MemorySettings(backend="local"),
    )
    lab = build_lab(settings)
    assert isinstance(lab.tracking, FileTracker)
    assert isinstance(lab.memory_store, LocalMemoryStore)


def test_build_lab_tracking_disabled(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(enabled=False),
        memory=MemorySettings(backend="local"),
    )
    lab = build_lab(settings)
    assert isinstance(lab.tracking, NoopTracker)


def test_build_lab_mlflow_tracker(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(
            backend="mlflow",
            enabled=True,
            mlflow_tracking_uri=f"file:{tmp_path / 'mlruns'}",
            mlflow_experiment_name="test",
        ),
        memory=MemorySettings(backend="local"),
    )
    lab = build_lab(settings)
    from dojo.tracking.mlflow_tracker import MlflowTracker

    assert isinstance(lab.tracking, MlflowTracker)


def test_build_lab_unknown_tracking_backend(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="unknown", enabled=True),
        memory=MemorySettings(backend="local"),
    )
    with pytest.raises(ValueError, match="Unknown tracking backend"):
        build_lab(settings)


def test_build_lab_unknown_memory_backend(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="file", enabled=True),
        memory=MemorySettings(backend="unknown"),
    )
    with pytest.raises(ValueError, match="Unknown memory backend"):
        build_lab(settings)


def test_build_lab_local_sandbox_default(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="file"),
        memory=MemorySettings(backend="local"),
    )
    lab = build_lab(settings)
    assert isinstance(lab.sandbox, LocalSandbox)


def test_build_lab_docker_sandbox(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="file"),
        memory=MemorySettings(backend="local"),
        sandbox=SandboxSettings(
            backend="docker",
            image="python:3.13-slim",
            memory_limit="4g",
            cpu_limit="2",
            network="none",
        ),
    )
    lab = build_lab(settings)
    assert isinstance(lab.sandbox, DockerSandbox)
    assert lab.sandbox.image == "python:3.13-slim"
    assert lab.sandbox.memory_limit == "4g"
    assert lab.sandbox.cpu_limit == "2"
    assert lab.sandbox.network == "none"


def test_build_lab_unknown_sandbox_backend(tmp_path) -> None:
    settings = Settings(
        storage=StorageSettings(base_dir=tmp_path / ".dojo"),
        tracking=TrackingSettings(backend="file"),
        memory=MemorySettings(backend="local"),
        sandbox=SandboxSettings(backend="bogus"),
    )
    with pytest.raises(ValueError, match="Unknown sandbox backend"):
        build_lab(settings)
