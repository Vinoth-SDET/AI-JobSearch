from ai_job_search.database import SQLiteProfileRepository
from ai_job_search.schemas.candidate_profile import (
    CandidateProfile,
    CandidateProfileHistory,
    CandidateProfileImport,
    CandidateProfileRecord,
    CandidateProvidedDetails,
)


class CandidateProfileAgent:
    def __init__(self, repository: SQLiteProfileRepository) -> None:
        self._repository = repository

    def create(self, profile: CandidateProfile) -> CandidateProfileRecord:
        return self._repository.create(profile)

    def import_profile(
        self,
        source: CandidateProfileImport,
    ) -> CandidateProfileRecord:
        source_profile = source.model_dump(
            mode="json",
            by_alias=True,
            exclude_unset=True,
        )
        return self._repository.import_profile(
            source.to_candidate_profile(),
            source_profile,
        )

    def get(self) -> CandidateProfileRecord:
        return self._repository.get()

    def get_history(self) -> CandidateProfileHistory:
        return self._repository.get_history()

    def replace(self, profile: CandidateProfile) -> CandidateProfileRecord:
        return self._repository.replace(profile)

    def delete(self) -> None:
        self._repository.delete()

    def confirm_paths(self, paths: list[str]) -> CandidateProfileRecord:
        return self._repository.confirm_paths(paths)

    def update_candidate_confirmed_details(
        self,
        details: CandidateProvidedDetails,
    ) -> CandidateProfileRecord:
        serialized = details.model_dump(mode="json", exclude_unset=True)
        if details.target_compensation is not None:
            serialized["target_compensation"] = details.target_compensation.model_dump(
                mode="json"
            )
        return self._repository.update_candidate_confirmed_details(
            serialized
        )
