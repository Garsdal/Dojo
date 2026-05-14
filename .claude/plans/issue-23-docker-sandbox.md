# Issue #23: Add DockerSandbox adapter as opt-in alternative to LocalSandbox

**Issue:** https://github.com/Garsdal/Dojo/issues/23
**Branch (will be created in Phase 2):** `feat/issue-23-docker-sandbox`
**Status:** awaiting review

## Summary

Add a `DockerSandbox` adapter behind the existing `Sandbox` interface so users can opt into containerised experiment execution with `--memory` and `--cpus` limits. Goal is **containment, not capacity** — an OOM kills the container, not the host. `LocalSandbox` stays the default; this is a sibling adapter selected by `sandbox.backend = "docker"`. Includes a lazy "venv-rebuild" path so macOS users with a host-built `.venv` can still run experiments inside the Linux container without manual setup — a sibling `.venv-docker/` is built on first use inside a one-shot container and reused for subsequent runs.

## Files to change

| File | Change |
|---|---|
| [src/dojo/sandbox/docker.py](src/dojo/sandbox/docker.py) | New `DockerSandbox` implementing the `Sandbox` ABC, plus lazy `.venv-docker/` rebuild |
| [src/dojo/config/settings.py](src/dojo/config/settings.py) | Add `backend`, `memory_limit`, `cpu_limit`, `image`, `network`, `auto_rebuild_venv` fields to `SandboxSettings` |
| [src/dojo/api/deps.py](src/dojo/api/deps.py) | New `_build_sandbox(settings)` helper, dispatch on `settings.sandbox.backend`; replace the inline `LocalSandbox(...)` at line 126 |
| [tests/unit/test_docker_sandbox.py](tests/unit/test_docker_sandbox.py) | Unit tests with a stubbed `docker` CLI — command construction, OOM detection (exit 137), timeout, cleanup, venv-path rewrite |
| [tests/unit/test_build_lab.py](tests/unit/test_build_lab.py) | Add a test that `DOJO_SANDBOX__BACKEND=docker` flips dispatch |
| [tests/integration/test_docker_sandbox_integration.py](tests/integration/test_docker_sandbox_integration.py) | End-to-end tests gated on `docker info`; smoke, OOM, artifacts, network, venv-rebuild |
| [CLAUDE.md](CLAUDE.md) | Update "Swappable adapters" table; add note on Docker backend caveats and `.venv-docker/` |
| [CHANGELOG.md](CHANGELOG.md) | New `## [v0.0.21]` entry below `## [Unreleased]` |
| [pyproject.toml](pyproject.toml) | Bump `version = "0.0.21"` |

## Approach

### 1. Config knobs (settings first, so dispatch has something to read)

Add to `SandboxSettings` in [config/settings.py](src/dojo/config/settings.py):

```python
backend: str = "local"            # "local" | "docker"
memory_limit: str | None = None   # e.g. "8g" — passed to `docker --memory`
cpu_limit: str | None = None      # e.g. "4"  — passed to `docker --cpus`
image: str = "python:3.13-slim"   # default image; override via env or YAML
network: str = "bridge"           # docker --network value; "bridge" preserves outbound
                                  # network so experiments can fetch datasets / models.
                                  # Set to "none" for strict no-net sandboxing.
auto_rebuild_venv: bool = True    # On first run with a `<cwd>/.venv/bin/python` path,
                                  # build a sibling `<cwd>/.venv-docker/` inside the
                                  # container and rewrite python_path to it. Off → use
                                  # python_path verbatim (Linux hosts where the venv
                                  # already runs cross-platform, or users who manage
                                  # the docker-venv themselves).
```

Leave `timeout` / `verification_timeout` as-is — those apply to both backends.

### 2. `DockerSandbox` implementation

New file [src/dojo/sandbox/docker.py](src/dojo/sandbox/docker.py). Mirrors `LocalSandbox`'s shape (same `_safe_script_filename` helper extracted to a shared module — see step 2a) so the diff is reviewable.

`__init__(self, *, image, timeout, memory_limit=None, cpu_limit=None, docker_bin="docker")` — stash config, prepare an instance-level `_active_containers: set[str]` for cleanup.

`async def execute(...)`:

1. Validate `language == "python"`, pick `effective_timeout`. Resolve `effective_python`:
   - If `python_path` is None → `"python"` (container's system Python).
   - If `python_path` ends with `/.venv/bin/python` AND `auto_rebuild_venv` is on → call `_ensure_docker_venv(cwd)` and use the returned `.venv-docker/bin/python` path.
   - Otherwise → use `python_path` verbatim (Linux host with native venv, or user-managed path).
2. Resolve `work_dir`, `effective_script_dir`, write the script to host disk exactly as `LocalSandbox` does.
3. Build the `docker run` argv:
   - `--rm` (auto-remove on exit)
   - `--name dojo-sandbox-<ulid>` (track for `cleanup()`)
   - `--memory=<memory_limit>` and `--memory-swap=<memory_limit>` if set (swap=memory disables swap, which is what we want — OOM kicks in at the limit, not after silently swapping)
   - `--cpus=<cpu_limit>` if set
   - `--network=<network>` (default `"bridge"` so experiments can fetch datasets / pull HF models / hit MLflow; `"none"` for strict sandboxing).
   - `-v <work_dir>:<work_dir>` (bind-mount workspace at the same path so absolute paths in `cwd` / `script_dir` / `DOJO_ARTIFACTS_DIR` / `python_path` work transparently — this is how the venv gets pulled in)
   - `-v <script_dir>:<script_dir>` if it's outside `work_dir`
   - `-w <work_dir>` (set cwd inside container)
   - `-e KEY=VAL` for each entry in `env_vars` (don't forward the full host env — too noisy / security)
   - `-e PYTHONUNBUFFERED=1` (so stdout streams promptly)
   - On Linux: `--user $(id -u):$(id -g)` so files written through the mount are owned by the host user (skip on macOS — Docker Desktop already maps the bind-mount user)
   - `<image> <effective_python> <script_path>`
4. `asyncio.create_subprocess_exec(*argv)` + `asyncio.wait_for(proc.communicate(), timeout=...)`.
5. On `TimeoutError`: `docker kill <container_name>` (best-effort), return `ExecutionResult(stderr="Execution timed out", exit_code=-1, ...)`.
6. On exit: if `proc.returncode == 137`, prepend a clear marker to stderr:
   ```
   stderr = "[dojo] Container OOMKilled (exit code 137). Memory limit was <X>.\n" + stderr
   ```
   This is the load-bearing UX — users need to see *why* a run failed, not just "exit 137".
7. `finally:` unlink script (mirroring LocalSandbox), remove container name from `_active_containers`.

`async def install_packages(packages)`: simplest correct thing is to run `pip install` *inside* a one-shot container against the configured image, with no bind mounts. This isn't called in the hot path (workspaces own their venvs) so the implementation just needs to not crash. Document that for the docker backend, the recommended path is to bake deps into a custom `image` rather than rely on `install_packages`.

`async def cleanup()`: best-effort `docker kill` of any container names still in `_active_containers`. Swallow `CalledProcessError` — container may already be gone.

#### 2a. Lazy `.venv-docker/` rebuild

When `auto_rebuild_venv` is on and the caller passes `python_path=<cwd>/.venv/bin/python`, the sandbox swaps it for `<cwd>/.venv-docker/bin/python` and ensures that path exists.

New private method `async def _ensure_docker_venv(self, cwd: str) -> str | None`:

1. Check `<cwd>/.venv-docker/bin/python` on host. If it exists, return its path — done.
2. Detect the workspace's dep manifest:
   - `pyproject.toml` present → use `uv` flow.
   - `requirements.txt` present → use `pip` flow.
   - Neither → build an empty venv (`python -m venv .venv-docker`). Log a warning that the user has no manifest.
3. Run a one-shot container, **not** through `execute()` (to avoid recursion and because we don't want this script-file-tempdir dance):
   ```bash
   docker run --rm -v <cwd>:<cwd> -w <cwd> <image> bash -lc '<setup-cmd>'
   ```
   where `<setup-cmd>` is one of:
   - **uv flow:** `pip install --quiet uv && uv venv .venv-docker && uv pip install --python .venv-docker/bin/python -r <(uv pip compile pyproject.toml --quiet 2>/dev/null || echo)` — *no, simpler:* `pip install --quiet uv && uv sync --project . --no-install-project --frozen 2>/dev/null || (uv venv .venv-docker && VIRTUAL_ENV=.venv-docker uv sync --active --no-install-project)`. **Picking the safest minimal version:**
     ```bash
     pip install --quiet uv && uv venv .venv-docker && \
       VIRTUAL_ENV="$PWD/.venv-docker" uv sync --active --no-install-project --no-dev
     ```
     The `--no-install-project` avoids building the user's own package (which might require system deps); `--no-dev` skips dev extras. If this misses something a user needs, they can either bake deps into a custom `image` or run their own `uv sync` from inside the container manually.
   - **pip flow:** `python -m venv .venv-docker && .venv-docker/bin/pip install --quiet -r requirements.txt`
   - **empty flow:** `python -m venv .venv-docker`
4. Stream stdout/stderr to the structured logger (`logger.info("docker_venv_build", ...)`) so the user sees progress on a slow first build. Use `asyncio.create_subprocess_exec` + read-line loop, not a one-shot `communicate()`.
5. On non-zero exit: raise a clear error including the docker stderr tail. Don't silently fall back to the host venv — that would re-introduce the exec-format-error failure mode we're trying to fix.
6. Cache the resolved path on `self._venv_cache: dict[str, str]` keyed by `cwd` so concurrent / back-to-back calls don't re-shell-out (the on-disk `.venv-docker/bin/python` check is the cross-process source of truth; the in-memory cache is for the common case of many experiments in one run).

Add a brief note to the docstring: "This rebuild happens once per workspace per container image. Delete `.venv-docker/` to force a fresh build (e.g. after adding deps to `pyproject.toml`)."

**Gitignore:** don't write `.gitignore` entries on behalf of the user (touching workspace files outside the explicit setup flow is risky). Mention `.venv-docker/` in the CLAUDE.md "Known issues" note instead so users add it themselves.

#### 2b. Extract `_safe_script_filename` to a shared module

Move from [src/dojo/sandbox/local.py](src/dojo/sandbox/local.py) to a new [src/dojo/sandbox/_script.py](src/dojo/sandbox/_script.py) (or keep `local.py` exposing it and import from there in `docker.py` — the latter is one fewer file and the existing test imports stay valid). **Going with: import from `local.py`**, since the existing test file [tests/unit/test_sandbox_naming.py](tests/unit/test_sandbox_naming.py) already imports `_safe_script_filename` from there.

### 3. Dispatch in `build_lab()`

Refactor [api/deps.py:126](src/dojo/api/deps.py#L126) — extract a `_build_sandbox(settings)` helper that mirrors `_build_tracking` / `_build_memory`:

```python
def _build_sandbox(settings: Settings) -> Sandbox:
    backend = settings.sandbox.backend
    if backend == "local":
        return LocalSandbox(timeout=settings.sandbox.timeout)
    if backend == "docker":
        return DockerSandbox(
            image=settings.sandbox.image,
            timeout=settings.sandbox.timeout,
            memory_limit=settings.sandbox.memory_limit,
            cpu_limit=settings.sandbox.cpu_limit,
            network=settings.sandbox.network,
            auto_rebuild_venv=settings.sandbox.auto_rebuild_venv,
        )
    raise ValueError(f"Unknown sandbox backend: {backend!r}")
```

Log at build time: `logger.info("sandbox_backend", backend=backend, image=..., memory_limit=..., cpu_limit=...)`.

Per CLAUDE.md "No silent fallbacks": unknown backend raises at `build_lab()` time, not at first `execute()`.

### 4. Tests

#### Unit (tests/unit/test_docker_sandbox.py)

Mock the `docker` CLI by monkey-patching `asyncio.create_subprocess_exec` with a fake that records argv and returns a configurable `(stdout, stderr, returncode)`. Cases:

- `docker run` argv contains `--memory=8g`, `--cpus=4`, `-v <cwd>:<cwd>`, `-w <cwd>`, `-e DOJO_ARTIFACTS_DIR=...`, `-e PYTHONUNBUFFERED=1`, image, python path, script path.
- `--memory-swap` mirrors `--memory` when both are set; absent when `--memory` is None.
- `--network=bridge` is on the argv by default; `network="none"` flips it.
- When `python_path` is passed (workspace venv case), it's forwarded verbatim into the container argv — no rewriting.
- Exit code 137 → `ExecutionResult.stderr` contains the OOMKilled marker.
- Timeout path: fake hangs, sandbox calls `docker kill`, returns `ExecutionResult(exit_code=-1, stderr="Execution timed out")`.
- `cleanup()` calls `docker kill` for tracked container names.
- Script file is cleaned up on success and on timeout.

#### Unit (tests/unit/test_build_lab.py — additive)

- `DOJO_SANDBOX__BACKEND=docker` produces a `LabEnvironment` whose `sandbox` is a `DockerSandbox` with the configured `memory_limit` / `cpu_limit` / `image`.
- `DOJO_SANDBOX__BACKEND=bogus` raises `ValueError` at `build_lab()`.

#### Integration (tests/integration/test_docker_sandbox_integration.py)

`@pytest.mark.skipif(not _docker_available(), reason="docker not available")` where `_docker_available()` shells out `docker info` (or `docker version`) and returns `True` on exit 0.

Tests:

1. **Smoke**: `DockerSandbox` runs `print("hello")` and gets `stdout == "hello\n"`, `exit_code == 0`.
2. **OOM containment**: with `memory_limit="32m"`, a script that does `x = bytearray(1024 * 1024 * 256)` exits with `137`, stderr contains the OOMKilled marker, **the test process is still alive afterwards** (assert by running another assertion in the same test).
3. **Artifacts via bind mount**: write a file to `DOJO_ARTIFACTS_DIR` from inside the container, then assert it exists on the host afterwards.
4. **Network reachable by default**: trivial `urllib.request.urlopen("https://pypi.org")` smoke (or similar — `socket.gethostbyname("pypi.org")` if we want to avoid TLS) returns successfully. Confirms `--network=bridge` is wired correctly.
5. **Venv rebuild — uv flow**: workspace with a minimal `pyproject.toml` (e.g. depends on `requests`), `auto_rebuild_venv=True`, point `python_path` at a non-existent `.venv/bin/python`. Sandbox builds `.venv-docker/`, the test script that does `import requests` succeeds.
6. **Venv rebuild — pip flow**: workspace with `requirements.txt`, same shape.
7. **Venv rebuild — idempotent**: second call to `execute()` against the same workspace doesn't re-shell-out to docker for the venv build (assert `_venv_cache` is populated and on-disk `.venv-docker/bin/python` exists).

Skipped by default on CI without Docker. Locally `just test` will run them when Docker is up.

### 5. CLAUDE.md update

Two small updates:

1. Swappable-adapters table: `Sandbox` row → "today's adapter(s)" becomes `LocalSandbox (subprocess), DockerSandbox (containerised, opt-in)`.
2. New short paragraph under "Known issues / nuances" noting: `DockerSandbox` is containment-only (does not increase available memory); default image is `python:3.13-slim`; default `--network=bridge` so experiments can hit the internet (use `sandbox.network = "none"` for strict isolation); workspace is bind-mounted into the container. On first run, a Linux-compatible `.venv-docker/` is auto-built alongside the host's `.venv/` from the workspace's `pyproject.toml` or `requirements.txt` (controlled by `sandbox.auto_rebuild_venv`, on by default). First build can take minutes; subsequent runs are instant. Add `.venv-docker/` to your workspace's `.gitignore`. To force a rebuild (e.g. after dep changes), delete the directory.

### 6. Release artefacts

Per `docs/RELEASING.md`:

- Bump `version` in [pyproject.toml](pyproject.toml) from `0.0.20` → `0.0.21` (minor-ish feature, but still 0.0.x; bump patch).
- Add `## [v0.0.21] - <today>` to [CHANGELOG.md](CHANGELOG.md) directly below `## [Unreleased]` with:
  - `### Agent prompts` — `(none in this release)` (this change doesn't touch prompts or tool descriptions).
  - `### Added` — DockerSandbox bullet pointing to the new module + the new `sandbox.backend / memory_limit / cpu_limit / image` config fields.

Tag/push happens after merge via ship-it's step 4 — **not** from the branch.

## Tests

- `just test` — unit + integration green. Docker integration test auto-skips if Docker isn't running.
- `just lint` — ruff clean.
- Manual smoke (optional, depending on whether reviewer has Docker locally): `DOJO_SANDBOX__BACKEND=docker DOJO_SANDBOX__MEMORY_LIMIT=2g uv run dojo run` against an existing domain and confirm experiments execute. Not required for the PR to land — the integration test covers this — but worth noting in the PR body.

## Risks / open questions

1. **`.venv-docker/` build can be slow on first run.** A workspace with heavy ML deps (torch, scikit-learn, etc.) can take minutes to install. We stream progress to the structured logger so the user sees the build happening. After the first build, subsequent runs are instant — the cached `.venv-docker/` is reused. To force a rebuild (e.g. after dependency changes), delete `.venv-docker/`.
2. **Venv-rebuild assumes uv or pip works against the user's manifest as-is.** Failure modes worth knowing about:
   - Workspace package itself requires building (e.g. native extensions). We pass `--no-install-project` to skip building the workspace's own package — only its deps go into the venv. Experiments still import workspace code via the bind-mounted source tree + relative imports, not via the installed package. This matches how `LocalSandbox` runs in practice (we never `pip install -e .` the workspace at run time).
   - System-level deps (e.g. `libpq-dev` for psycopg2). The default `python:3.13-slim` doesn't ship build tools. If a user's deps need compilation, they should override `image` with one that has the toolchain. We can't auto-detect this — if `uv sync` fails, we surface the error and let the user adjust.
   - Private indices / auth. Out of scope. If the user needs private PyPI auth, they can bake it into a custom `image` with appropriate `pip.conf` / netrc.
3. **Exec-format-error fallback when auto_rebuild_venv is off.** If a user disables the rebuild and points `python_path` at a host-built venv that won't run on Linux, the docker run exits 126 with `exec format error`. We detect that signature and prepend a clear marker telling them to enable `auto_rebuild_venv` or override `image`.
2. **Default `--network=bridge`** (per reviewer requirement) so experiments can fetch datasets, pull HF models, hit MLflow tracking URIs, etc. Strict isolation is available via `sandbox.network = "none"`. We may revisit defaults once usage patterns shake out.
3. **`--user $(id -u):$(id -g)`** is Linux-only; on macOS Docker Desktop the bind-mount user mapping is handled by the VM. The plan is to only pass `--user` when `sys.platform == "linux"`.
4. **Container name collision on rapid back-to-back runs**: handled by suffixing with a ULID via `generate_id()`.
5. **stdout buffering:** `PYTHONUNBUFFERED=1` is set in the forwarded env so stdout streams promptly.
6. **Image pull on first use**: `docker run python:3.13-slim` against a fresh Docker daemon downloads the image (~30–60s). One-time cost; flagged in the docstring and the CLAUDE.md note.

## Out of scope

- GPU support (`--gpus all` / NVIDIA runtime).
- Remote / distributed Docker (Swarm, k8s, remote daemons over TCP).
- Image management beyond a configurable default — no registry auth, no per-domain images, no auto-Dockerfile generation, no image caching layer.
- Making more memory available — this is containment-only.
- Replacing `LocalSandbox`. It stays the default for everyone.
- A per-experiment override for `memory_limit` / `cpu_limit` via tool-call args. Worth doing eventually but the orchestrator + tool layer would need to thread it through, which is a separate change.

## Release notes

CHANGELOG entry under `## [v0.0.21]`:

```markdown
### Agent prompts

(none in this release)

### Added

- **`DockerSandbox` — opt-in containerised execution.** New [src/dojo/sandbox/docker.py](src/dojo/sandbox/docker.py) implements the `Sandbox` ABC by shelling out to `docker run` with `--memory` / `--cpus` limits. An experiment that OOMs now kills the container, not the host — the dojo lab keeps running. Enable with `sandbox.backend = "docker"` in `.dojo/config.yaml` (or `DOJO_SANDBOX__BACKEND=docker`). New config knobs: `sandbox.memory_limit` (e.g. `"8g"`), `sandbox.cpu_limit` (e.g. `"4"`), `sandbox.image` (default `python:3.13-slim`), `sandbox.network` (default `"bridge"`), `sandbox.auto_rebuild_venv` (default `true`). Workspace is bind-mounted into the container at the same absolute path. On first run, a Linux-compatible `.venv-docker/` is built next to the host's `.venv/` from the workspace's `pyproject.toml` or `requirements.txt`, so macOS users don't need to set anything up manually — first build takes minutes, subsequent runs are instant. Add `.venv-docker/` to `.gitignore`. (#23)
```
