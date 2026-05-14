# HTTP API

`dojo start` runs a FastAPI server on `http://localhost:8000`. The live OpenAPI spec is at `/docs` — that's the source of truth. This page exists as a quick orientation.

The server reads and writes the same `.dojo/` directory the CLI uses, so a CLI-started run is visible to the API and vice versa.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/domains` | Create a research domain |
| `POST` | `/domains/{id}/task` | Attach a Task (regression today) |
| `POST` | `/domains/{id}/tools/generate` | AI-generate `load_data` / `evaluate` from SETUP.md, verify against contract |
| `POST` | `/domains/{id}/task/freeze` | Freeze the task — gated on every required tool's verification |
| `POST` | `/domains/{id}/task/unfreeze` | Unfreeze the task |
| `POST` | `/domains/{id}/workspace/setup` | One-time workspace prep (venv + deps) |
| `POST` | `/agent/run` | Start an agent run on a domain (requires a frozen task) |
| `GET`  | `/agent/runs/{id}/events` | Live SSE event stream |
| `GET`  | `/experiments?domain_id=` | List experiments |
| `GET`  | `/knowledge?domain_id=` | List knowledge atoms |
| `GET`  | `/health` | Health check |
