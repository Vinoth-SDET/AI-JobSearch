from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

DiscoverySource = Literal["linkedin", "indeed", "google"]
JobStatus = Literal[
    "discovered",
    "verification_pending",
    "verified",
    "expired",
    "unavailable",
]
LocationMatch = Literal[
    "preferred_city",
    "preferred_country",
    "europe_region",
    "remote",
    "outside_preferences",
    "unknown",
]
URLStatus = Literal[
    "pending",
    "verified",
    "expired",
    "unavailable",
    "not_provided",
]


class JobSearchLocation(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=1, max_length=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)


class JobSearchPreferences(BaseModel):
    job_titles: list[str] = Field(min_length=1, max_length=20)
    locations: list[JobSearchLocation] = Field(min_length=1, max_length=100)
    remote_eligibility_rule: str | None = Field(default=None, max_length=1000)


class JobDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[DiscoverySource] = Field(
        default_factory=lambda: ["linkedin", "indeed", "google"],
        min_length=1,
        max_length=3,
    )
    max_results_per_source: int = Field(default=20, ge=1, le=100)
    max_total_charge_usd: Decimal = Field(
        gt=Decimal("0"),
        le=Decimal("10"),
        decimal_places=2,
    )

    @field_validator("sources")
    @classmethod
    def sources_must_be_unique(
        cls,
        sources: list[DiscoverySource],
    ) -> list[DiscoverySource]:
        if len(set(sources)) != len(sources):
            raise ValueError("discovery sources must be unique")
        return sources


class ActorRunPreview(BaseModel):
    source: DiscoverySource
    actor_id: str
    input: dict[str, object]
    max_items: int = Field(ge=1, le=100)
    allocated_max_charge_usd: Decimal


class JobDiscoveryPreview(BaseModel):
    preferences: JobSearchPreferences
    max_total_charge_usd: Decimal
    actor_runs: list[ActorRunPreview]


class JobPosting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    title: str = Field(min_length=1, max_length=300)
    company: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    country: str | None = Field(default=None, max_length=100)
    employment_type: str | None = Field(default=None, max_length=100)
    workplace_type: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=10_000)
    salary: str | None = Field(default=None, max_length=500)
    posted_at: str | None = None
    expires_at: str | None = None
    is_expired: bool | None = None
    status: JobStatus = "discovered"
    location_match: LocationMatch = "unknown"
    remote_eligibility: Literal[
        "eligible",
        "restricted",
        "unknown",
        "not_remote",
    ]
    application_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    source: DiscoverySource
    actor_id: str = Field(min_length=1, max_length=200)
    actor_run_id: str = Field(min_length=1, max_length=200)
    retrieved_at: datetime
    verification_evidence: list[str] = Field(default_factory=list)
    verification_checked_at: datetime | None = None
    posting_url_status: URLStatus = "pending"
    application_url_status: URLStatus = "not_provided"
    posting_final_url: HttpUrl | None = None
    application_final_url: HttpUrl | None = None
    posting_http_status: int | None = Field(default=None, ge=100, le=599)
    application_http_status: int | None = Field(default=None, ge=100, le=599)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_verification_status(cls, value: object) -> object:
        if not isinstance(value, dict) or "verification_status" not in value:
            return value
        migrated = dict(value)
        legacy_status = migrated.pop("verification_status")
        if "status" not in migrated:
            migrated["status"] = (
                "expired" if legacy_status == "expired" else "discovered"
            )
        return migrated
    duplicate_of: int | None = None
    is_repost: bool = False


class JobDiscoveryRunResult(BaseModel):
    source: DiscoverySource
    actor_id: str
    actor_run_id: str | None = None
    status: str
    retrieved_at: datetime
    received_count: int = Field(ge=0)
    saved_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)


class JobDiscoveryRunList(BaseModel):
    items: list[JobDiscoveryRunResult]
    total: int = Field(ge=0)


class JobDiscoveryResponse(BaseModel):
    preferences: JobSearchPreferences
    runs: list[JobDiscoveryRunResult]
    jobs: list[JobPosting]


class JobPostingList(BaseModel):
    items: list[JobPosting]
    total: int = Field(ge=0)


class JobDiscoveryRunRequest(JobDiscoveryRequest):
    confirm_live_run: bool = False
