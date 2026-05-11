"""Application settings — Pydantic Settings with YAML + env var support."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    """API server configuration."""

    host: str = "127.0.0.1"
    port: int = 8000


class SandboxSettings(BaseSettings):
    """Sandbox execution configuration."""

    # Per-experiment wall-clock cap. 300s is generous enough for most sklearn
    # / boosted-tree fits on tabular data while still bounding runaway agent
    # code. Override via DOJO_SANDBOX__TIMEOUT or .dojo/config.yaml.
    timeout: float = 300.0
    # One-off cap for `dojo task setup` verification. Set high because the
    # first call to `load_data` may have to fetch+cache real datasets (parquet,
    # web downloads, etc.); subsequent verifications hit the cache. Override
    # per invocation with `dojo task setup --timeout`.
    verification_timeout: float = 600.0


class StorageSettings(BaseSettings):
    """Storage configuration."""

    base_dir: Path = Path(".dojo")


class TrackingSettings(BaseSettings):
    """Experiment tracking configuration."""

    backend: str = "file"  # "file" | "mlflow"
    enabled: bool = True

    # MLflow-specific
    mlflow_tracking_uri: str = "file:./mlruns"  # MLflow tracking server URI
    mlflow_experiment_name: str = "dojo"  # Default experiment name
    mlflow_artifact_location: str | None = None  # Override artifact root (optional)


class MemorySettings(BaseSettings):
    """Knowledge memory configuration."""

    backend: str = "local"  # "local" (future: "postgres")
    search_limit: int = 10  # Default number of results from search

    # Linker selects how RELATED_TO links are picked at write time.
    # Atom shape and search semantics are identical across linkers.
    # "keyword" — overlap heuristic, free, default
    # "llm"     — one AgentBackend.complete() call per write
    linker: str = "keyword"
    # Model used by LLMKnowledgeLinker. None falls back to
    # `agent.tool_generation_model`. Only consulted when linker == "llm".
    llm_linker_model: str | None = None


class FrontendSettings(BaseSettings):
    """Frontend dev server configuration."""

    enabled: bool = True
    port: int = 5173


class AgentSettings(BaseSettings):
    """Agent execution configuration."""

    backend: str = "claude"  # Which AgentBackend to use ("claude", "stub")
    max_turns: int = 50  # Max tool-use round trips (cumulative across continuations)
    max_budget_usd: float | None = None  # Max spend per run (None = unlimited)
    # Wall-clock cap for the whole run (loop-wide). None = unlimited. The
    # continuation loop checks this between iterations; an iteration that's
    # already in flight isn't interrupted mid-stream, so brief overshoot
    # is expected for long single iterations.
    max_wall_clock_s: float | None = None
    # When False, the orchestrator behaves as it did before the continuation
    # loop landed — one backend invocation, end. Kill switch for users who
    # want the legacy semantics.
    auto_continue: bool = True
    permission_mode: str = "acceptEdits"  # Permission mode (backend-specific)
    cwd: str | None = None  # Working directory for code execution
    # Model used for one-shot tool generation (`dojo task generate` / `setup`).
    # Sonnet 4.6 is a sensible default — strong enough to write correct sklearn
    # tool code, fast enough to keep the spinner short.
    tool_generation_model: str = "claude-sonnet-4-6"


class Settings(BaseSettings):
    """Root application settings.

    Loads from environment variables with DOJO_ prefix,
    and from .dojo/config.yaml if present.
    """

    model_config = SettingsConfigDict(
        env_prefix="DOJO_",
        env_nested_delimiter="__",
        # Tolerate unknown top-level blocks in `.dojo/config.yaml` — when we
        # delete a settings group (e.g. the `llm:` block in v0.0.16), users
        # with an old config from a previous release shouldn't hit a hard
        # ValidationError on first run. Pre-1.0 break is fine, surprise
        # crashes on upgrade are not.
        extra="ignore",
    )

    api: APISettings = Field(default_factory=APISettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    tracking: TrackingSettings = Field(default_factory=TrackingSettings)
    frontend: FrontendSettings = Field(default_factory=FrontendSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Settings":
        """Load settings, optionally from a YAML config file.

        Args:
            config_path: Path to a YAML config file. Defaults to .dojo/config.yaml.

        Returns:
            Populated Settings instance.
        """
        import yaml

        path = config_path or Path(".dojo/config.yaml")
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()
