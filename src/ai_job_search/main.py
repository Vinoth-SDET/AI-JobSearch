import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from ai_job_search.agents.candidate_profile.agent import CandidateProfileAgent
from ai_job_search.api.routes.candidate_profile import router as candidate_profile_router
from ai_job_search.database import SQLiteProfileRepository


def create_app(database_path: str | Path | None = None) -> FastAPI:
    path = database_path or os.environ.get(
        "DATABASE_PATH", "data/ai-job-search.sqlite3"
    )
    repository = SQLiteProfileRepository(path)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        repository.initialize()
        yield

    app = FastAPI(
        title="AI Job Search and Auto-Apply Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.candidate_profile_agent = CandidateProfileAgent(repository)
    app.include_router(candidate_profile_router, prefix="/api/v1")
    return app


app = create_app()
