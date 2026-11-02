from fastapi import APIRouter, HTTPException, Query, Request, status

from ai_job_search.agents.job_discovery.agent import (
    JobDiscoveryAgent,
    JobDiscoveryBudgetError,
    JobDiscoveryConfirmationRequiredError,
    JobDiscoveryDisabledError,
    JobDiscoveryExecutionError,
    JobSearchPreferencesUnavailableError,
)
from ai_job_search.agents.job_discovery.repository import (
    JobPostingNotFoundError,
)
from ai_job_search.database import ProfileNotFoundError
from ai_job_search.schemas.job_discovery import (
    DiscoverySource,
    JobDiscoveryPreview,
    JobDiscoveryRequest,
    JobDiscoveryResponse,
    JobDiscoveryRunList,
    JobDiscoveryRunRequest,
    JobPosting,
    JobPostingList,
    JobSearchPreferences,
)

router = APIRouter(tags=["job discovery"])


def _agent(request: Request) -> JobDiscoveryAgent:
    return request.app.state.job_discovery_agent


@router.get(
    "/job-discovery/preferences",
    response_model=JobSearchPreferences,
)
def get_job_search_preferences(request: Request) -> JobSearchPreferences:
    try:
        return _agent(request).get_preferences()
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error
    except JobSearchPreferencesUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error


@router.post(
    "/job-discovery/preview",
    response_model=JobDiscoveryPreview,
)
def preview_job_discovery(
    discovery: JobDiscoveryRequest,
    request: Request,
) -> JobDiscoveryPreview:
    try:
        return _agent(request).preview(discovery)
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error
    except JobSearchPreferencesUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except JobDiscoveryBudgetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@router.post(
    "/job-discovery/runs",
    response_model=JobDiscoveryResponse,
)
def run_job_discovery(
    discovery: JobDiscoveryRunRequest,
    request: Request,
) -> JobDiscoveryResponse:
    try:
        return _agent(request).discover(discovery)
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error
    except JobDiscoveryConfirmationRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Set confirm_live_run=true to authorize Actor execution",
        ) from error
    except JobDiscoveryDisabledError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except JobSearchPreferencesUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except JobDiscoveryBudgetError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except JobDiscoveryExecutionError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error


@router.get("/jobs", response_model=JobPostingList)
def list_discovered_jobs(
    request: Request,
    source: DiscoverySource | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobPostingList:
    return _agent(request).list_jobs(
        source=source,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/job-discovery/runs",
    response_model=JobDiscoveryRunList,
)
def list_job_discovery_runs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> JobDiscoveryRunList:
    return _agent(request).list_runs(limit=limit, offset=offset)


@router.post(
    "/jobs/{posting_id}/verify",
    response_model=JobPosting,
)
def verify_job_posting(
    posting_id: int,
    request: Request,
) -> JobPosting:
    try:
        return _agent(request).verify_posting(posting_id)
    except JobPostingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job posting not found",
        ) from error
