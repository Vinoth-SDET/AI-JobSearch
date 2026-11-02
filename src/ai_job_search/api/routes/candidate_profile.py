from fastapi import APIRouter, HTTPException, Request, Response, status

from ai_job_search.agents.candidate_profile.agent import CandidateProfileAgent
from ai_job_search.database import (
    InvalidConfirmationPathError,
    ProfileAlreadyExistsError,
    ProfileHasUnconfirmedClaimsError,
    ProfileNotFoundError,
)
from ai_job_search.schemas.candidate_profile import (
    CandidateProfile,
    CandidateProfileConfirmation,
    CandidateProfileHistory,
    CandidateProfileImport,
    CandidateProvidedDetails,
    CandidateProfileRecord,
)

router = APIRouter(tags=["candidate profile"])


def _agent(request: Request) -> CandidateProfileAgent:
    return request.app.state.candidate_profile_agent


@router.post(
    "/candidate-profile",
    status_code=status.HTTP_201_CREATED,
    response_model=CandidateProfileRecord,
)
def create_candidate_profile(
    profile: CandidateProfile,
    request: Request,
) -> CandidateProfileRecord:
    try:
        return _agent(request).create(profile)
    except ProfileAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A candidate profile already exists",
        ) from error


@router.post(
    "/candidate-profile/import",
    status_code=status.HTTP_201_CREATED,
    response_model=CandidateProfileRecord,
)
def import_candidate_profile(
    source: CandidateProfileImport,
    request: Request,
) -> CandidateProfileRecord:
    try:
        return _agent(request).import_profile(source)
    except ProfileAlreadyExistsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A candidate profile already exists",
        ) from error


@router.get(
    "/candidate-profile",
    response_model=CandidateProfileRecord,
)
def get_candidate_profile(request: Request) -> CandidateProfileRecord:
    try:
        return _agent(request).get()
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error


@router.get(
    "/candidate-profile/history",
    response_model=CandidateProfileHistory,
)
def get_candidate_profile_history(request: Request) -> CandidateProfileHistory:
    try:
        return _agent(request).get_history()
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error


@router.post(
    "/candidate-profile/review/confirm",
    response_model=CandidateProfileRecord,
)
def confirm_candidate_profile_claims(
    confirmation: CandidateProfileConfirmation,
    request: Request,
) -> CandidateProfileRecord:
    try:
        return _agent(request).confirm_paths(confirmation.paths)
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error
    except InvalidConfirmationPathError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Each path must identify a pending claim in the imported profile",
        ) from error


@router.patch(
    "/candidate-profile/candidate-details",
    response_model=CandidateProfileRecord,
)
def update_candidate_provided_details(
    details: CandidateProvidedDetails,
    request: Request,
) -> CandidateProfileRecord:
    try:
        return _agent(request).update_candidate_confirmed_details(details)
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error


@router.put(
    "/candidate-profile",
    response_model=CandidateProfileRecord,
)
def replace_candidate_profile(
    profile: CandidateProfile,
    request: Request,
) -> CandidateProfileRecord:
    try:
        return _agent(request).replace(profile)
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error
    except ProfileHasUnconfirmedClaimsError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Imported profile contains unconfirmed claims",
        ) from error


@router.delete(
    "/candidate-profile",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_candidate_profile(request: Request) -> Response:
    try:
        _agent(request).delete()
    except ProfileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate profile not found",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
