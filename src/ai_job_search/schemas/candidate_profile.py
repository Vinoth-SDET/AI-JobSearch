from datetime import datetime
from typing import Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class ProfileSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class WorkExperience(ProfileSchema):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=50)
    end_date: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=10_000)
    accomplishments: list[str] = Field(default_factory=list, max_length=100)


class Education(ProfileSchema):
    institution: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_date: str | None = Field(default=None, max_length=50)
    end_date: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=5_000)


class ProfileLink(ProfileSchema):
    label: str = Field(min_length=1, max_length=100)
    url: AnyHttpUrl


class CandidateProfile(ProfileSchema):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(
        default=None,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=200)
    headline: str | None = Field(default=None, max_length=300)
    summary: str | None = Field(default=None, max_length=10_000)
    skills: list[str] = Field(default_factory=list, max_length=200)
    experience: list[WorkExperience] = Field(default_factory=list, max_length=100)
    education: list[Education] = Field(default_factory=list, max_length=100)
    certifications: list[str] = Field(default_factory=list, max_length=100)
    links: list[ProfileLink] = Field(default_factory=list, max_length=100)

    @field_validator("full_name")
    @classmethod
    def full_name_must_not_be_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("full_name must not be blank")
        return value

    @field_validator("skills", "certifications")
    @classmethod
    def list_items_must_not_be_blank(cls, values: list[str]) -> list[str]:
        if any(not value for value in values):
            raise ValueError("items must not be blank")
        return values


class CandidateProfileRecord(BaseModel):
    profile: CandidateProfile
    created_at: datetime
    updated_at: datetime
    review_status: Literal["pending_candidate_review", "confirmed"]
    source_profile: dict[str, object] | None = None
    unconfirmed_paths: list[str] = Field(default_factory=list)
    candidate_confirmed_details: dict[str, object] = Field(default_factory=dict)


class CandidateProfileHistoryItem(BaseModel):
    version: int
    action: Literal[
        "profile_created",
        "profile_imported",
        "candidate_details_updated",
        "claims_confirmed",
        "profile_replaced",
        "profile_migrated",
    ]
    changed_at: datetime
    record: CandidateProfileRecord


class CandidateProfileHistory(BaseModel):
    items: list[CandidateProfileHistoryItem]


class TargetCompensation(BaseModel):
    amount_lpa: float = Field(gt=0)
    currency: Literal["INR"] = "INR"
    period: Literal["annual"] = "annual"
    basis: str = "unspecified"


class CandidateProvidedDetails(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    automation_experience_years: str | None = Field(default=None, min_length=1)
    current_location: str | None = Field(default=None, min_length=1)
    preferred_locations: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )
    notice_period: str | None = Field(default=None, min_length=1)
    target_compensation: TargetCompensation | None = None
    relocation_destinations: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=50,
    )

    @field_validator("preferred_locations", "relocation_destinations")
    @classmethod
    def location_items_must_not_be_blank(
        cls,
        values: list[str] | None,
    ) -> list[str] | None:
        if values is not None and any(not value for value in values):
            raise ValueError("location entries must not be blank")
        return values

    @model_validator(mode="after")
    def require_at_least_one_detail(self) -> "CandidateProvidedDetails":
        if not self.model_fields_set:
            raise ValueError("provide at least one candidate detail")
        return self


class ImportSchema(BaseModel):
    model_config = ConfigDict(
        extra="allow",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class SourceIdentity(ImportSchema):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    phone: str | None = None
    current_city: str | None = None
    current_state: str | None = None
    current_country: str | None = None
    linkedin_url: str | None = None
    portfolio_or_github_url: str | None = None


class SourceSummary(ImportSchema):
    headline: str | None = None
    professional_summary: str | None = None
    total_experience_years: str | None = None
    automation_experience_years: str | None = None
    current_job_title_for_forms: str | None = None
    confirmed: bool | None = None


class SourceAchievement(ImportSchema):
    text: str = Field(min_length=1)
    metric: str | None = None
    confirmed: bool | None = None


class SourceEmployment(ImportSchema):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    achievements: list[SourceAchievement] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class SourceSkill(ImportSchema):
    name: str = Field(min_length=1, max_length=200)
    category: str | None = None
    years: int | float | str | None = None
    proficiency: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confirmed: bool | None = None


class SourceProject(ImportSchema):
    name: str | None = None
    project: str | None = None
    description: str | None = None
    what_it_does: str | None = None
    link_or_evidence: str | None = None
    confirmed: bool | None = None


class SourceCertification(ImportSchema):
    name: str = Field(min_length=1)
    issuer: str | None = None
    date: str | None = None
    credential_id: str | None = None


class SourceEducation(ImportSchema):
    degree: str | None = None
    institution: str = Field(min_length=1)
    year: str | None = None


class CandidateProfileImport(ImportSchema):
    metadata: dict[str, object] | None = Field(default=None, alias="_meta")
    identity: SourceIdentity
    summary: SourceSummary | None = None
    employment_history: list[SourceEmployment] = Field(default_factory=list)
    employment_gaps_for_forms: list[dict[str, object]] = Field(default_factory=list)
    skills: list[SourceSkill] = Field(default_factory=list)
    ai_agent_experience: dict[str, object] | None = None
    selected_projects: list[SourceProject] = Field(default_factory=list)
    certifications: list[SourceCertification] = Field(default_factory=list)
    education: list[SourceEducation] = Field(default_factory=list)
    job_preferences: dict[str, object] | None = None
    work_authorisation_and_sponsorship: dict[str, object] | None = None
    availability: dict[str, object] | None = None
    standard_application_answers: list[dict[str, object]] = Field(
        default_factory=list
    )

    def to_candidate_profile(self) -> CandidateProfile:
        identity = self.identity
        location = ", ".join(
            part
            for part in (
                identity.current_city,
                identity.current_state,
                identity.current_country,
            )
            if part
        ) or None
        links: list[ProfileLink] = []
        for label, url in (
            ("LinkedIn", identity.linkedin_url),
            ("Portfolio or GitHub", identity.portfolio_or_github_url),
        ):
            if url:
                normalized_url = url if "://" in url else f"https://{url}"
                links.append(ProfileLink(label=label, url=normalized_url))

        summary = self.summary
        experience = []
        for role in self.employment_history:
            accomplishments = [
                f"{item.text} ({item.metric})" if item.metric else item.text
                for item in role.achievements
            ]
            experience.append(
                WorkExperience(
                    company=role.company,
                    title=role.title,
                    location=role.location,
                    start_date=role.start_date,
                    end_date=role.end_date,
                    accomplishments=accomplishments,
                )
            )

        return CandidateProfile(
            full_name=identity.full_name,
            email=identity.email,
            phone=identity.phone,
            location=location,
            headline=summary.headline if summary else None,
            summary=summary.professional_summary if summary else None,
            skills=[skill.name for skill in self.skills],
            experience=experience,
            education=[
                Education(
                    institution=item.institution,
                    degree=item.degree,
                    end_date=item.year,
                )
                for item in self.education
            ],
            certifications=[item.name for item in self.certifications],
            links=links,
        )


class CandidateProfileConfirmation(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=200)

    @field_validator("paths")
    @classmethod
    def paths_must_be_json_pointers(cls, paths: list[str]) -> list[str]:
        if any(not path.startswith("/") or path == "/" for path in paths):
            raise ValueError("each path must be a non-root JSON pointer")
        if len(set(paths)) != len(paths):
            raise ValueError("paths must be unique")
        return paths
