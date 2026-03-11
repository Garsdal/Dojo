# AgentML task runner — https://github.com/casey/just

# ── Development ───────────────────────────────────────────────────────────────

# Install all deps (incl. dev + optional extras)
dev:
    uv sync --all-extras

# Run all tests
test:
    uv run pytest -v

# Lint check
lint:
    uv run ruff check src/ tests/
    uv run ruff format --check src/ tests/

# Auto-fix lint + format
format:
    uv run ruff check --fix src/ tests/
    uv run ruff format src/ tests/

# ── Running ───────────────────────────────────────────────────────────────────

# Start with stub agent (no API key required)
run-stub:
    AGENTML_AGENT__BACKEND=stub uv run agentml start

# Start with Claude agent (requires ANTHROPIC_API_KEY)
run-claude:
    AGENTML_AGENT__BACKEND=claude uv run agentml start

# Start with stub agent + MLflow tracking (MLflow UI on :8080)
run-stub-mlflow:
    uv run mlflow server --backend-store-uri ./mlruns --host 127.0.0.1 --port 8080 &
    @sleep 2
    AGENTML_AGENT__BACKEND=stub \
    AGENTML_TRACKING__BACKEND=mlflow \
    AGENTML_TRACKING__MLFLOW_TRACKING_URI=http://127.0.0.1:8080 \
    uv run agentml start

# Start with Claude agent + MLflow tracking (MLflow UI on :8080)
run-claude-mlflow:
    uv run mlflow server --backend-store-uri ./mlruns --host 127.0.0.1 --port 8080 &
    @sleep 2
    AGENTML_AGENT__BACKEND=claude \
    AGENTML_TRACKING__BACKEND=mlflow \
    AGENTML_TRACKING__MLFLOW_TRACKING_URI=http://127.0.0.1:8080 \
    uv run agentml start

# Stop all services (backend :8000, frontend :5173, MLflow :8080)
stop:
    -lsof -ti :8000 | xargs kill -9
    -lsof -ti :5173 | xargs kill -9
    -lsof -ti :8080 | xargs kill -9

# ── Frontend ──────────────────────────────────────────────────────────────────

frontend-install:
    cd frontend && npm install

frontend-dev:
    cd frontend && npm run dev

frontend-build:
    cd frontend && npm run build

# ── Misc ──────────────────────────────────────────────────────────────────────

# Run frontend in background + backend (without built-in frontend server)
dev-all:
    cd frontend && npm run dev &
    uv run agentml start --no-frontend
