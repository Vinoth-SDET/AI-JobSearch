# AI Job Search and Auto-Apply Platform

A modular platform for candidate profile management and, in later phases, job discovery and application workflows. The initial executable component is the Candidate Profile Agent.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1–3 | Manual preparation, research, and configuration | Completed manually; not software deliverables |
| 4 | Candidate Profile Agent | JSON import, review workflow, API, and tests implemented; see [phase status](docs/phase-status.md) |
| 5 | Job Discovery Agent | Phase 5.2 fixture-based acceptance and mocked multi-source persistence checks implemented; live Actor runs and URL checks not performed; see [phase status](docs/phase-status.md) |
| Future | Matching, application materials, auto-apply, orchestration | Not implemented |

## Development

Requirements: Python 3.11 or newer.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn ai_job_search.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive API documentation is at `/docs`. The SQLite database is created at `data/ai-job-search.sqlite3` by default. Set `DATABASE_PATH` to use another location.

Copy `.env.example` to `.env` as a reference for local settings. The application reads environment variables from the process; `.env` is not loaded automatically. Live Apify execution requires `APIFY_TOKEN`, `JOB_DISCOVERY_ENABLED=true`, and an explicit request with `confirm_live_run=true` and a charge budget within the configured cap. Preview requests do not contact Apify.

Run tests with:

```powershell
python -m pytest
```

See [architecture and API](docs/architecture.md), [project requirements](docs/project-requirements.md), [phase status](docs/phase-status.md), and [prepared asset intake](assets/prepared/README.md).
