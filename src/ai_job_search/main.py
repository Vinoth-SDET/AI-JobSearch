import os
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from ai_job_search.agents.candidate_profile.agent import CandidateProfileAgent
from ai_job_search.agents.job_discovery.agent import (
    JobDiscoveryAgent,
    JobDiscoverySettings,
)
from ai_job_search.agents.job_discovery.repository import (
    SQLiteJobDiscoveryRepository,
)
from ai_job_search.api.routes.candidate_profile import router as candidate_profile_router
from ai_job_search.api.routes.job_discovery import router as job_discovery_router
from ai_job_search.database import SQLiteProfileRepository


def create_app(database_path: str | Path | None = None) -> FastAPI:
    path = database_path or os.environ.get(
        "DATABASE_PATH", "data/ai-job-search.sqlite3"
    )
    repository = SQLiteProfileRepository(path)
    discovery_repository = SQLiteJobDiscoveryRepository(path)
    profile_agent = CandidateProfileAgent(repository)
    apify_token = os.environ.get("APIFY_TOKEN", "").strip()
    discovery_settings = JobDiscoverySettings(
        enabled=os.environ.get(
            "JOB_DISCOVERY_ENABLED", "false"
        ).strip().casefold()
        in {"true", "1", "yes"},
        apify_token=apify_token or None,
        max_budget_usd=Decimal(
            os.environ.get("JOB_DISCOVERY_MAX_BUDGET_USD", "1.00")
        ),
        linkedin_actor_id=os.environ.get(
            "APIFY_LINKEDIN_ACTOR_ID", "bebity/linkedin-jobs-scraper"
        ).strip(),
        indeed_actor_id=os.environ.get(
            "APIFY_INDEED_ACTOR_ID", "borderline/indeed-scraper"
        ).strip(),
        google_actor_id=os.environ.get(
            "APIFY_GOOGLE_ACTOR_ID", "apify/google-search-scraper"
        ).strip(),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        repository.initialize()
        discovery_repository.initialize()
        yield

    app = FastAPI(
        title="AI Job Search and Auto-Apply Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.candidate_profile_agent = profile_agent
    app.state.job_discovery_agent = JobDiscoveryAgent(
        profile_agent,
        discovery_repository,
        discovery_settings,
    )
    app.include_router(candidate_profile_router, prefix="/api/v1")
    app.include_router(job_discovery_router, prefix="/api/v1")
    return app


app = create_app()
