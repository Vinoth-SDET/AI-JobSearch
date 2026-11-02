from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import urlsplit

from pydantic import HttpUrl, ValidationError

from ai_job_search.agents.candidate_profile.agent import CandidateProfileAgent
from ai_job_search.agents.job_discovery.repository import (
    SQLiteJobDiscoveryRepository,
)
from ai_job_search.agents.job_discovery.verification import (
    SafePostingURLVerifier,
    URLVerification,
)
from ai_job_search.schemas.job_discovery import (
    ActorRunPreview,
    DiscoverySource,
    JobDiscoveryPreview,
    JobDiscoveryRequest,
    JobDiscoveryResponse,
    JobDiscoveryRunRequest,
    JobDiscoveryRunList,
    JobDiscoveryRunResult,
    JobPosting,
    JobPostingList,
    JobSearchLocation,
    JobSearchPreferences,
)


class JobDiscoveryError(Exception):
    pass


class JobDiscoveryDisabledError(JobDiscoveryError):
    pass


class JobDiscoveryConfirmationRequiredError(JobDiscoveryError):
    pass


class JobSearchPreferencesUnavailableError(JobDiscoveryError):
    pass


class JobDiscoveryBudgetError(JobDiscoveryError):
    pass


class JobDiscoveryExecutionError(JobDiscoveryError):
    def __init__(
        self,
        message: str,
        *,
        source: DiscoverySource,
        actor_id: str,
        actor_run_id: str | None = None,
        status: str = "FAILED",
    ) -> None:
        super().__init__(message)
        self.source = source
        self.actor_id = actor_id
        self.actor_run_id = actor_run_id
        self.status = status


@dataclass(frozen=True)
class JobDiscoverySettings:
    enabled: bool = False
    apify_token: str | None = None
    max_budget_usd: Decimal = Decimal("1.00")
    linkedin_actor_id: str = "bebity/linkedin-jobs-scraper"
    indeed_actor_id: str = "borderline/indeed-scraper"
    google_actor_id: str = "apify/google-search-scraper"

    def __post_init__(self) -> None:
        if self.max_budget_usd < Decimal("0.01"):
            raise ValueError("The configured discovery budget must be at least $0.01.")
        if self.max_budget_usd > Decimal("10"):
            raise ValueError("The configured discovery budget cannot exceed $10.")
        if not all(
            (
                self.linkedin_actor_id.strip(),
                self.indeed_actor_id.strip(),
                self.google_actor_id.strip(),
            )
        ):
            raise ValueError("All configured Actor IDs must be non-empty.")


class ActorExecutor(Protocol):
    def run(
        self,
        *,
        source: DiscoverySource,
        actor_id: str,
        actor_input: dict[str, object],
        max_items: int,
        max_total_charge_usd: Decimal,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]: ...


class PostingURLVerifier(Protocol):
    def verify(self, url: HttpUrl) -> URLVerification: ...


class ApifyActorExecutor:
    def __init__(self, token: str) -> None:
        from apify_client import ApifyClient

        self._client = ApifyClient(token)

    def run(
        self,
        *,
        source: DiscoverySource,
        actor_id: str,
        actor_input: dict[str, object],
        max_items: int,
        max_total_charge_usd: Decimal,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        import impit
        from apify_client.errors import ApifyApiError

        try:
            run = self._client.actor(actor_id).call(
                run_input=actor_input,
                max_items=max_items,
                max_total_charge_usd=max_total_charge_usd,
                timeout_secs=180,
                wait_secs=210,
                logger=None,
            )
        except (impit.TimeoutException, TimeoutError):
            raise JobDiscoveryExecutionError(
                "The Actor run timed out before Apify returned a run record.",
                source=source,
                actor_id=actor_id,
                status="TIMED-OUT",
            ) from None
        except (ApifyApiError, impit.RequestError):
            raise JobDiscoveryExecutionError(
                "Apify rejected or could not complete the Actor request.",
                source=source,
                actor_id=actor_id,
            ) from None
        if run is None:
            raise JobDiscoveryExecutionError(
                "The Actor did not finish within the configured wait period.",
                source=source,
                actor_id=actor_id,
                status="TIMED-OUT",
            )
        run_id = run.get("id")
        status = run.get("status", "UNKNOWN")
        if not run_id:
            raise JobDiscoveryExecutionError(
                "The Actor response did not include a run ID.",
                source=source,
                actor_id=actor_id,
                status=str(status),
            )
        if status != "SUCCEEDED":
            raise JobDiscoveryExecutionError(
                f"The Actor run finished with status {status}.",
                source=source,
                actor_id=actor_id,
                actor_run_id=str(run_id),
                status=str(status),
            )
        dataset_id = run.get("defaultDatasetId")
        if not dataset_id:
            raise JobDiscoveryExecutionError(
                "The successful Actor run did not include a result dataset.",
                source=source,
                actor_id=actor_id,
                actor_run_id=str(run_id),
                status="FAILED",
            )
        try:
            page = self._client.dataset(dataset_id).list_items(
                limit=max_items,
                clean=True,
            )
        except (impit.TimeoutException, TimeoutError):
            raise JobDiscoveryExecutionError(
                "The result dataset request timed out.",
                source=source,
                actor_id=actor_id,
                actor_run_id=str(run_id),
                status="TIMED-OUT",
            ) from None
        except (ApifyApiError, impit.RequestError):
            raise JobDiscoveryExecutionError(
                "Apify could not return the Actor result dataset.",
                source=source,
                actor_id=actor_id,
                actor_run_id=str(run_id),
            ) from None
        return run, [
            item for item in page.items if isinstance(item, dict)
        ]


class JobDiscoveryAgent:
    _INDEED_PRICE_PER_RESULT_USD = Decimal("0.005")
    _COUNTRY_CODES = {
        "germany": "de",
        "luxembourg": "lu",
        "united kingdom": "gb",
        "uk": "gb",
        "austria": "at",
        "belgium": "be",
        "bulgaria": "bg",
        "croatia": "hr",
        "cyprus": "cy",
        "czechia": "cz",
        "czech republic": "cz",
        "denmark": "dk",
        "estonia": "ee",
        "finland": "fi",
        "france": "fr",
        "greece": "gr",
        "hungary": "hu",
        "iceland": "is",
        "ireland": "ie",
        "italy": "it",
        "latvia": "lv",
        "liechtenstein": "li",
        "lithuania": "lt",
        "malta": "mt",
        "monaco": "mc",
        "netherlands": "nl",
        "norway": "no",
        "poland": "pl",
        "portugal": "pt",
        "romania": "ro",
        "slovakia": "sk",
        "slovenia": "si",
        "spain": "es",
        "sweden": "se",
        "switzerland": "ch",
        "united states": "us",
        "india": "in",
    }
    _CODE_COUNTRIES = {
        "at": "Austria",
        "be": "Belgium",
        "bg": "Bulgaria",
        "ch": "Switzerland",
        "cy": "Cyprus",
        "cz": "Czechia",
        "de": "Germany",
        "dk": "Denmark",
        "ee": "Estonia",
        "es": "Spain",
        "fi": "Finland",
        "fr": "France",
        "gb": "United Kingdom",
        "gr": "Greece",
        "hr": "Croatia",
        "hu": "Hungary",
        "ie": "Ireland",
        "is": "Iceland",
        "it": "Italy",
        "li": "Liechtenstein",
        "lt": "Lithuania",
        "lu": "Luxembourg",
        "lv": "Latvia",
        "mc": "Monaco",
        "mt": "Malta",
        "nl": "Netherlands",
        "no": "Norway",
        "pl": "Poland",
        "pt": "Portugal",
        "ro": "Romania",
        "se": "Sweden",
        "si": "Slovenia",
        "sk": "Slovakia",
    }
    _EUROPEAN_COUNTRY_CODES = {
        "at",
        "be",
        "bg",
        "ch",
        "cy",
        "cz",
        "de",
        "dk",
        "ee",
        "es",
        "fi",
        "fr",
        "gb",
        "gr",
        "hr",
        "hu",
        "ie",
        "is",
        "it",
        "li",
        "lt",
        "lu",
        "lv",
        "mc",
        "mt",
        "nl",
        "no",
        "pl",
        "pt",
        "ro",
        "se",
        "si",
        "sk",
    }

    def __init__(
        self,
        profile_agent: CandidateProfileAgent,
        repository: SQLiteJobDiscoveryRepository,
        settings: JobDiscoverySettings,
        executor: ActorExecutor | None = None,
        url_verifier: PostingURLVerifier | None = None,
    ) -> None:
        self._profile_agent = profile_agent
        self._repository = repository
        self._settings = settings
        self._executor = executor
        self._url_verifier = url_verifier or SafePostingURLVerifier()

    def get_preferences(self) -> JobSearchPreferences:
        record = self._profile_agent.get()
        source_profile = record.source_profile or {}
        job_preferences = source_profile.get("job_preferences")
        if not isinstance(job_preferences, dict):
            job_preferences = {}
        confirmed = record.candidate_confirmed_details

        titles = [
            title[:200]
            for title in self._string_list(
                job_preferences.get("target_titles")
            )[:20]
        ]
        for title in self._string_list(
            job_preferences.get("also_consider_titles")
        ):
            if (
                len(titles) < 20
                and title.casefold() not in {value.casefold() for value in titles}
            ):
                titles.append(title[:200])
        if not titles:
            raise JobSearchPreferencesUnavailableError(
                "Candidate job-title preferences are not available."
            )

        source_locations = job_preferences.get("target_locations")
        source_location_map: dict[str, list[str]] = {}
        if isinstance(source_locations, list):
            for entry in source_locations:
                if not isinstance(entry, dict):
                    continue
                country = entry.get("country")
                cities = entry.get("cities")
                if isinstance(country, str):
                    source_location_map[country.casefold()[:100]] = [
                        city[:200]
                        for city in self._string_list(cities)[:50]
                    ]

        selected = self._string_list(confirmed.get("preferred_locations"))
        selected_seen = {location.casefold() for location in selected}
        selected.extend(
            location
            for location in self._string_list(
                confirmed.get("relocation_destinations")
            )
            if location.casefold() not in selected_seen
        )
        locations = self._selected_locations(
            selected,
            source_location_map,
        )
        if not locations:
            locations = self._locations_from_source(source_location_map)
        if not locations:
            raise JobSearchPreferencesUnavailableError(
                "Candidate job-location preferences are not available."
            )

        rule = job_preferences.get("remote_eligibility_rule")
        return JobSearchPreferences(
            job_titles=titles,
            locations=locations,
            remote_eligibility_rule=rule[:1000]
            if isinstance(rule, str)
            else None,
        )

    def preview(self, request: JobDiscoveryRequest) -> JobDiscoveryPreview:
        preferences = self.get_preferences()
        plans = self._build_actor_runs(preferences, request)
        if not plans:
            raise JobSearchPreferencesUnavailableError(
                "No supported Actor runs can be built from the preferences."
            )
        allocations = self._allocate_budget(
            request.max_total_charge_usd,
            len(plans),
        )
        source_counts = {
            source: sum(plan[0] == source for plan in plans)
            for source in request.sources
        }
        source_offsets = {source: 0 for source in request.sources}
        actor_previews: list[ActorRunPreview] = []
        for (source, actor_id, actor_input), allocation in zip(
            plans,
            allocations,
            strict=True,
        ):
            run_count = source_counts[source]
            base, remainder = divmod(
                request.max_results_per_source,
                run_count,
            )
            offset = source_offsets[source]
            source_offsets[source] += 1
            max_items = base + (offset < remainder)
            bounded_input = dict(actor_input)
            if source == "indeed":
                max_items = min(
                    max_items,
                    int(
                        allocation
                        / self._INDEED_PRICE_PER_RESULT_USD
                    ),
                )
                bounded_input["maxRows"] = max_items
            actor_previews.append(
                ActorRunPreview(
                    source=source,
                    actor_id=actor_id,
                    input=bounded_input,
                    max_items=max_items,
                    allocated_max_charge_usd=allocation,
                )
            )
        return JobDiscoveryPreview(
            preferences=preferences,
            max_total_charge_usd=request.max_total_charge_usd,
            actor_runs=actor_previews,
        )

    def list_jobs(
        self,
        *,
        source: DiscoverySource | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> JobPostingList:
        return self._repository.get_jobs(
            source=source,
            limit=limit,
            offset=offset,
        )

    def list_runs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> JobDiscoveryRunList:
        return self._repository.get_runs(limit=limit, offset=offset)

    def verify_posting(self, posting_id: int) -> JobPosting:
        posting = self._repository.get_posting(posting_id)
        if posting.status == "expired":
            return posting

        application_status = (
            "pending" if posting.application_url is not None else "not_provided"
        )
        self._repository.update_verification(
            posting_id,
            status="verification_pending",
            posting_url_status="pending",
            application_url_status=application_status,
            evidence=posting.verification_evidence
            + ["Independent HTTPS URL verification started."],
        )

        if posting.source_url is None:
            posting_result = URLVerification(
                status="unavailable",
                http_status=None,
                final_url=None,
                evidence="No posting URL was available to verify.",
            )
        else:
            posting_result = self._url_verifier.verify(posting.source_url)

        application_result = None
        if posting.application_url is not None:
            if posting.application_url == posting.source_url:
                application_result = posting_result
            else:
                application_result = self._url_verifier.verify(
                    posting.application_url
                )

        evidence = posting.verification_evidence + [
            f"Posting URL check: {posting_result.evidence}"
        ]
        if application_result is not None:
            evidence.append(
                f"Application URL check: {application_result.evidence}"
            )
        else:
            evidence.append("No employer application URL was provided.")

        return self._repository.update_verification(
            posting_id,
            status="discovered",
            checked_at=datetime.now(timezone.utc),
            posting_url_status=posting_result.status,
            application_url_status=(
                application_result.status
                if application_result is not None
                else "not_provided"
            ),
            posting_final_url=posting_result.final_url,
            application_final_url=(
                application_result.final_url
                if application_result is not None
                else None
            ),
            posting_http_status=posting_result.http_status,
            application_http_status=(
                application_result.http_status
                if application_result is not None
                else None
            ),
            evidence=evidence,
        )

    def discover(
        self,
        request: JobDiscoveryRunRequest,
    ) -> JobDiscoveryResponse:
        if not request.confirm_live_run:
            raise JobDiscoveryConfirmationRequiredError
        if not self._settings.enabled:
            raise JobDiscoveryDisabledError(
                "Live Job Discovery is disabled by application configuration."
            )
        if not self._settings.apify_token:
            raise JobDiscoveryDisabledError(
                "APIFY_TOKEN is required for live Job Discovery."
            )
        if request.max_total_charge_usd > self._settings.max_budget_usd:
            raise JobDiscoveryBudgetError(
                "The requested budget exceeds the configured application cap."
            )

        preview = self.preview(request)
        executor = self._executor or ApifyActorExecutor(
            self._settings.apify_token
        )
        run_results: list[JobDiscoveryRunResult] = []
        discovered: list[JobPosting] = []

        for actor_run in preview.actor_runs:
            try:
                run, items = executor.run(
                    source=actor_run.source,
                    actor_id=actor_run.actor_id,
                    actor_input=actor_run.input,
                    max_items=actor_run.max_items,
                    max_total_charge_usd=actor_run.allocated_max_charge_usd,
                )
            except JobDiscoveryExecutionError as error:
                failed = JobDiscoveryRunResult(
                    source=error.source,
                    actor_id=error.actor_id,
                    actor_run_id=error.actor_run_id,
                    status=error.status,
                    retrieved_at=datetime.now(timezone.utc),
                    received_count=0,
                    saved_count=0,
                    duplicate_count=0,
                    expired_count=0,
                )
                self._repository.record_run(failed)
                raise

            actor_run_id = run.get("id")
            if not isinstance(actor_run_id, str) or not actor_run_id:
                raise JobDiscoveryExecutionError(
                    "The Actor response did not include a run ID.",
                    source=actor_run.source,
                    actor_id=actor_run.actor_id,
                )
            retrieved_at = datetime.now(timezone.utc)
            all_records = [
                (record, actor_run.source)
                for item in items
                for record in self._extract_records(
                    item=item,
                    source=actor_run.source,
                )
            ]
            records = all_records[: actor_run.max_items]
            postings = [
                posting
                for item, source in records
                if (posting := self._normalize_posting(
                    item=item,
                    source=source,
                    actor_id=actor_run.actor_id,
                    actor_run_id=actor_run_id,
                    retrieved_at=retrieved_at,
                    preferences=preview.preferences,
                ))
                is not None
            ]
            expired_count = sum(
                posting.is_expired is True for posting in postings
            )
            active_postings = [
                posting for posting in postings if posting.is_expired is not True
            ]
            observed = [
                self._repository.save_posting(posting)
                for posting in active_postings
            ]
            duplicate_count = sum(
                posting.duplicate_of is not None for posting in observed
            )
            saved = [
                posting
                for posting in observed
                if posting.duplicate_of is None
            ]
            result = JobDiscoveryRunResult(
                source=actor_run.source,
                actor_id=actor_run.actor_id,
                actor_run_id=actor_run_id,
                status="SUCCEEDED",
                retrieved_at=retrieved_at,
                received_count=len(all_records),
                saved_count=len(saved),
                duplicate_count=duplicate_count,
                expired_count=expired_count,
            )
            self._repository.record_run(result)
            run_results.append(result)
            discovered.extend(saved)

        return JobDiscoveryResponse(
            preferences=preview.preferences,
            runs=run_results,
            jobs=[
                self._repository.get_posting(posting.id)
                for posting in discovered
                if posting.id is not None
            ],
        )

    def _build_actor_runs(
        self,
        preferences: JobSearchPreferences,
        request: JobDiscoveryRequest,
    ) -> list[tuple[DiscoverySource, str, dict[str, object]]]:
        plans: list[tuple[DiscoverySource, str, dict[str, object]]] = []
        if "linkedin" in request.sources:
            title_count = min(
                len(preferences.job_titles),
                max(
                    1,
                    request.max_results_per_source
                    // len(preferences.locations),
                ),
            )
            locations = preferences.locations[
                : request.max_results_per_source
            ]
            titles = preferences.job_titles[:title_count]
            row_count = max(
                1,
                request.max_results_per_source
                // (len(titles) * len(locations)),
            )
            plans.append(
                (
                    "linkedin",
                    self._settings.linkedin_actor_id,
                    {
                        "titles": titles,
                        "locations": [location.name for location in locations],
                        "rows": row_count,
                    },
                )
            )
        if "indeed" in request.sources:
            indeed_plan_count = 0
            for location in preferences.locations:
                if (
                    location.country_code
                    and indeed_plan_count < request.max_results_per_source
                ):
                    query = " OR ".join(
                        f'"{title}"' for title in preferences.job_titles
                    )
                    plans.append(
                        (
                            "indeed",
                            self._settings.indeed_actor_id,
                            {
                                "country": (
                                    "uk"
                                    if location.country_code == "gb"
                                    else location.country_code
                                ),
                                "location": location.name,
                                "query": query,
                                "maxRows": 1,
                            },
                        )
                    )
                    indeed_plan_count += 1
        if "google" in request.sources:
            locations_by_country: dict[
                tuple[str | None, str], list[JobSearchLocation]
            ] = {}
            for location in preferences.locations:
                key = (location.country_code, location.country)
                locations_by_country.setdefault(key, []).append(location)
            groups = list(locations_by_country.items())[
                : request.max_results_per_source
            ]
            query_limits = self._distribute_count(
                request.max_results_per_source,
                len(groups),
            )
            for ((country_code, _), locations), query_limit in zip(
                groups,
                query_limits,
                strict=True,
            ):
                group_queries = [
                    self._google_query(title, location.name)
                    for title in preferences.job_titles
                    for location in locations
                ]
                plans.append(
                    (
                        "google",
                        self._settings.google_actor_id,
                        self._google_input(
                            group_queries[: max(1, query_limit)],
                            country_code,
                        ),
                    )
                )
        return plans

    @staticmethod
    def _distribute_count(total: int, count: int) -> list[int]:
        if count == 0:
            return []
        base, remainder = divmod(total, count)
        return [
            base + (index < remainder)
            for index in range(count)
        ]

    @staticmethod
    def _google_input(
        queries: list[str],
        country_code: str | None,
    ) -> dict[str, object]:
        actor_input: dict[str, object] = {
            "queries": "\n".join(queries),
            "maxPagesPerQuery": 1,
            "aiOverview": {"scrapeFullAiOverview": False},
            "aiModeSearch": {"enableAiMode": False},
            "geminiSearch": {"enableGemini": False},
            "perplexitySearch": {
                "enablePerplexity": False,
                "returnImages": False,
                "returnRelatedQuestions": False,
            },
            "chatGptSearch": {"enableChatGpt": False},
            "copilotSearch": {"enableCopilot": False},
            "maximumLeadsEnrichmentRecords": 0,
            "verifyLeadsEnrichmentEmails": False,
            "websiteContentScraper": {"enable": False},
            "focusOnPaidAds": False,
        }
        if country_code:
            actor_input["countryCode"] = country_code
        return actor_input

    @staticmethod
    def _google_query(title: str, location: str) -> str:
        title_words = title.replace('"', "").split()[:16]
        location_words = location.replace('"', "").split()[:8]
        return (
            f'"{" ".join(title_words)}" jobs '
            f'"{" ".join(location_words)}" '
            "site:greenhouse.io OR site:jobs.lever.co OR site:workday.com"
        )

    @staticmethod
    def _allocate_budget(total: Decimal, count: int) -> list[Decimal]:
        cents = int(total * 100)
        if count < 1 or cents < count:
            raise JobDiscoveryBudgetError(
                "The request budget must allocate at least $0.01 per Actor run."
            )
        base, remainder = divmod(cents, count)
        return [
            Decimal(base + (index < remainder)) / Decimal(100)
            for index in range(count)
        ]

    @classmethod
    def _selected_locations(
        cls,
        selected: list[str],
        source_location_map: dict[str, list[str]],
    ) -> list[JobSearchLocation]:
        locations: list[JobSearchLocation] = []
        for value in selected:
            normalized = value.casefold().strip()
            if normalized in {"europe", "european region"}:
                locations.append(
                    JobSearchLocation(name="Europe", country="Europe")
                )
                continue
            country = cls._canonical_country(normalized)
            if country:
                cities = source_location_map.get(country.casefold(), [])
                if cities:
                    locations.extend(
                        JobSearchLocation(
                            name=city,
                            country=country,
                            country_code=cls._COUNTRY_CODES.get(
                                country.casefold()
                            ),
                        )
                        for city in cities
                    )
                else:
                    locations.append(
                        JobSearchLocation(
                            name=country,
                            country=country,
                            country_code=cls._COUNTRY_CODES.get(
                                country.casefold()
                            ),
                        )
                    )
                continue
            matched_country, matched_city = cls._find_source_city(
                value,
                source_location_map,
            )
            if matched_country and matched_city:
                locations.append(
                    JobSearchLocation(
                        name=matched_city,
                        country=matched_country,
                        country_code=cls._COUNTRY_CODES.get(
                            matched_country.casefold()
                        ),
                    )
                )
        # A country selected by the candidate can appear as "UK" or "United
        # Kingdom"; canonicalization prevents duplicate city searches.
        return cls._unique_locations(locations)[:100]

    @classmethod
    def _locations_from_source(
        cls,
        source_location_map: dict[str, list[str]],
    ) -> list[JobSearchLocation]:
        locations: list[JobSearchLocation] = []
        for country_key, cities in source_location_map.items():
            country = cls._canonical_country(country_key) or country_key.title()
            locations.extend(
                JobSearchLocation(
                    name=city,
                    country=country,
                    country_code=cls._COUNTRY_CODES.get(country.casefold()),
                )
                for city in cities
            )
        return cls._unique_locations(locations)[:100]

    @classmethod
    def _canonical_country(cls, value: str) -> str | None:
        canonical = {
            "india": "India",
            "united kingdom": "United Kingdom",
            "uk": "United Kingdom",
            "luxembourg": "Luxembourg",
            "germany": "Germany",
        }
        return canonical.get(value.casefold())

    @classmethod
    def _find_source_city(
        cls,
        value: str,
        source_location_map: dict[str, list[str]],
    ) -> tuple[str | None, str | None]:
        normalized = value.split(",", 1)[0].strip().casefold()
        for country_key, cities in source_location_map.items():
            country = cls._canonical_country(country_key) or country_key.title()
            for city in cities:
                if city.casefold() == normalized:
                    return country, city
        return None, None

    @staticmethod
    def _unique_locations(
        locations: list[JobSearchLocation],
    ) -> list[JobSearchLocation]:
        unique: dict[tuple[str, str], JobSearchLocation] = {}
        for location in locations:
            unique.setdefault(
                (location.name.casefold(), location.country.casefold()),
                location,
            )
        return list(unique.values())

    @staticmethod
    def _string_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    @classmethod
    def _normalize_posting(
        cls,
        *,
        item: dict[str, Any],
        source: DiscoverySource,
        actor_id: str,
        actor_run_id: str,
        retrieved_at: datetime,
        preferences: JobSearchPreferences,
    ) -> JobPosting | None:
        title = cls._first_text(
            item,
            "title",
            "jobTitle",
            "job_title",
            "positionName",
        )
        personal_info = item.get("personalInfo")
        personal_info = (
            personal_info if isinstance(personal_info, dict) else {}
        )
        title = title or cls._first_text(personal_info, "jobTitle")
        if not title:
            return None
        company = cls._first_text(
            item,
            "company",
            "companyName",
            "employer",
            "sourceEmployerName",
        ) or cls._first_text(personal_info, "companyName")
        location = cls._first_text(
            item,
            "location",
            "jobLocation",
            "formattedLocation",
        ) or cls._first_text(personal_info, "location")
        location, structured_country = cls._location_details(
            item.get("location") if not isinstance(item.get("location"), str) else None,
            location,
        )
        description = cls._first_text(
            item,
            "description",
            "jobDescription",
            "descriptionText",
            "descriptionHtml",
        ) or cls._first_text(personal_info, "rawText")
        source_url = cls._first_url(
            item,
            "url",
            "jobUrl",
            "job_url",
            "jobLink",
            "link",
            "positionUrl",
        )
        application_url = cls._first_url(
            item,
            "applyUrl",
            "apply_url",
            "applicationUrl",
            "application_url",
            "applyLink",
        )
        if source_url is None and application_url is not None:
            source_url = application_url
        posted_at = cls._first_text(
            item,
            "postedAt",
            "posted_at",
            "datePosted",
            "publishedAt",
            "datePublished",
            "date",
            "postedTime",
            "age",
        )
        expires_at = cls._first_text(
            item,
            "expiresAt",
            "expires_at",
            "expirationDate",
            "validThrough",
        )
        expired = cls._expired_status(item, expires_at, retrieved_at)
        workplace_type = cls._workplace_type(item, location, description)
        country = (
            structured_country
            or cls._first_text(item, "country", "countryName")
        )
        employment_type = cls._first_text(
            item,
            "employmentType",
            "employment_type",
            "jobType",
            "type",
            "contractType",
        )
        salary = cls._salary(item)
        evidence = [
            "Source and application details were received from Actor output; "
            "listing validity has not been independently checked."
        ]
        if application_url is None:
            evidence.append(
                "No application URL was returned by the Actor."
            )
        else:
            evidence.append(
                "An application URL was returned; reachability and employer "
                "ownership remain unverified."
            )
        try:
            return JobPosting(
                title=title[:300],
                company=company[:300] if company else None,
                location=location[:300] if location else None,
                country=country[:100] if country else None,
                employment_type=employment_type[:100]
                if employment_type
                else None,
                workplace_type=workplace_type,
                description=description[:10_000] if description else None,
                salary=salary[:500] if salary else None,
                posted_at=posted_at[:100] if posted_at else None,
                expires_at=expires_at[:100] if expires_at else None,
                is_expired=expired,
                status="expired" if expired is True else "discovered",
                location_match=cls._location_match(
                    preferences,
                    location,
                    country,
                    workplace_type,
                ),
                remote_eligibility=cls._remote_eligibility(
                    workplace_type,
                    location,
                    description,
                    country,
                ),
                application_url=application_url,
                source_url=source_url,
                source=source,
                actor_id=actor_id,
                actor_run_id=actor_run_id,
                retrieved_at=retrieved_at,
                verification_evidence=evidence,
            )
        except ValidationError:
            return None

    @staticmethod
    def _extract_records(
        *,
        item: dict[str, Any],
        source: DiscoverySource,
    ) -> list[dict[str, Any]]:
        if source != "google":
            return [item]
        organic_results = item.get("organicResults")
        if not isinstance(organic_results, list):
            return [item]
        return [
            result
            for result in organic_results
            if isinstance(result, dict)
        ]

    @classmethod
    def _location_details(
        cls,
        value: object,
        fallback_location: str | None,
    ) -> tuple[str | None, str | None]:
        if not isinstance(value, dict):
            return fallback_location, None
        city = cls._first_text(
            value,
            "city",
            "formattedAddressLong",
            "formattedAddressShort",
            "fullAddress",
        )
        country = cls._first_text(value, "country", "countryName")
        if country is None:
            country_code = cls._first_text(value, "countryCode")
            if country_code:
                country = cls._CODE_COUNTRIES.get(country_code.casefold())
        if city and country and country.casefold() not in city.casefold():
            city = f"{city}, {country}"
        return city or fallback_location, country

    @classmethod
    def _location_match(
        cls,
        preferences: JobSearchPreferences,
        location: str | None,
        country: str | None,
        workplace_type: str | None,
    ) -> str:
        workplace = (workplace_type or "").casefold()
        if workplace in {"remote", "fully remote", "remote only"}:
            return "remote"
        if not location and not country:
            return "unknown"

        location_text = cls._normalize_location_text(
            " ".join(value for value in (location, country) if value)
        )
        preferred_cities = {
            cls._normalize_location_text(preference.name)
            for preference in preferences.locations
            if preference.country.casefold() != "europe"
            and preference.name.casefold() != preference.country.casefold()
        }
        preferred_countries = {
            cls._normalize_location_text(preference.country)
            for preference in preferences.locations
            if preference.country.casefold() != "europe"
        }
        if any(
            cls._contains_location(location_text, city)
            for city in preferred_cities
        ):
            return "preferred_city"
        if any(
            cls._contains_location(location_text, preferred)
            for preferred in preferred_countries
        ):
            return "preferred_country"

        if any(
            preference.country.casefold() == "europe"
            for preference in preferences.locations
        ):
            country_code = cls._COUNTRY_CODES.get(
                (country or "").casefold()
            )
            if country_code in cls._EUROPEAN_COUNTRY_CODES:
                return "europe_region"
            for code, european_country in cls._CODE_COUNTRIES.items():
                if cls._contains_location(
                    location_text,
                    cls._normalize_location_text(european_country),
                ):
                    return "europe_region"
        return "outside_preferences"

    @staticmethod
    def _normalize_location_text(value: str) -> str:
        return " ".join(
            re.sub(r"[^\w]+", " ", value.casefold()).split()
        )

    @staticmethod
    def _contains_location(text: str, location: str) -> bool:
        return bool(
            location
            and re.search(
                rf"(?<!\w){re.escape(location)}(?!\w)",
                text,
            )
        )

    @staticmethod
    def _first_text(item: dict[str, Any], *keys: str) -> str | None:
        for key in keys:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                values = [
                    item.strip()
                    for item in value
                    if isinstance(item, str) and item.strip()
                ]
                if values:
                    return ", ".join(values)
        return None

    @classmethod
    def _first_url(cls, item: dict[str, Any], *keys: str) -> HttpUrl | None:
        for key in keys:
            value = item.get(key)
            if not isinstance(value, str):
                continue
            try:
                parsed = urlsplit(value.strip())
            except ValueError:
                continue
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                continue
            try:
                return HttpUrl(value.strip())
            except ValidationError:
                continue
        return None

    @staticmethod
    def _is_expired(
        value: str | None,
        retrieved_at: datetime,
    ) -> bool | None:
        if not value:
            return None
        try:
            normalized = value.replace("Z", "+00:00")
            try:
                expires = datetime.fromisoformat(normalized)
            except ValueError:
                expires = datetime.combine(
                    date.fromisoformat(value[:10]),
                    datetime.min.time(),
                    tzinfo=timezone.utc,
                )
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return expires <= retrieved_at
        except ValueError:
            return None

    @classmethod
    def _expired_status(
        cls,
        item: dict[str, Any],
        expires_at: str | None,
        retrieved_at: datetime,
    ) -> bool | None:
        if item.get("expired") is True or item.get("isExpired") is True:
            return True
        date_expired = cls._is_expired(expires_at, retrieved_at)
        if date_expired is True:
            return True
        if item.get("expired") is False or item.get("isExpired") is False:
            return False
        return date_expired

    @staticmethod
    def _workplace_type(
        item: dict[str, Any],
        location: str | None,
        description: str | None,
    ) -> str | None:
        value = JobDiscoveryAgent._first_text(
            item,
            "workplaceType",
            "workplace_type",
            "workArrangement",
            "workType",
        )
        if value:
            return value[:100]
        remote_flag = item.get("isRemote", item.get("remote"))
        text = f"{location or ''} {description or ''}".casefold()
        if remote_flag is False:
            return "not remote"
        if remote_flag is True:
            return "remote"
        if re.search(r"\bhybrid\b", text):
            return "hybrid"
        if re.search(r"\bremote\b", text):
            return "remote"
        if re.search(r"\bon[- ]site\b", text):
            return "on-site"
        return None

    @staticmethod
    def _remote_eligibility(
        workplace_type: str | None,
        location: str | None,
        description: str | None,
        country: str | None = None,
    ) -> str:
        workplace = (workplace_type or "").casefold()
        if workplace and workplace not in {
            "remote",
            "fully remote",
            "remote only",
        }:
            return "not_remote"
        if not workplace:
            return "unknown"
        text = f"{location or ''} {description or ''} {country or ''}".casefold()
        if re.search(
            r"\b(remote from india|india remote|remote\s*(?:-|in)\s*india|"
            r"remote only within india|india-based|based in india|"
            r"india only|located in india|reside in india)\b",
            text,
        ):
            return "eligible"
        if re.search(
            r"\b(us only|usa only|united states only|uk only|"
            r"united kingdom only|canada only|australia only|"
            r"remote[- ]only[- ]in[- ](the[- ])?(us|usa|uk|canada|australia)|"
            r"must be (based|located|resident|residing) in (the )?"
            r"(us|usa|united states|uk|united kingdom|canada|australia)|"
            r"must reside in (the )?(us|usa|united states|uk|"
            r"united kingdom|canada|australia)|"
            r"(us|usa|united states|uk|united kingdom|canada|australia)"
            r" residents only)\b",
            text,
        ):
            return "restricted"
        return "unknown"

    @staticmethod
    def _salary(item: dict[str, Any]) -> str | None:
        salary = item.get("salary")
        if isinstance(salary, str):
            return salary.strip() or None
        if isinstance(salary, (int, float)):
            return str(salary)
        if isinstance(salary, dict):
            parts = [
                str(salary.get(key, salary.get(alias)))
                for key, alias in (
                    ("currency", "salaryCurrency"),
                    ("min", "salaryMin"),
                    ("max", "salaryMax"),
                    ("period", "salaryType"),
                    ("text", "salaryText"),
                )
                if salary.get(key, salary.get(alias)) is not None
            ]
            return " ".join(parts) or None
        parts = [
            f"{name}={item[key]}"
            for key, name in (
                ("salaryCurrency", "currency"),
                ("salaryMin", "minimum"),
                ("salaryMax", "maximum"),
                ("salaryType", "period"),
            )
            if item.get(key) is not None
        ]
        if parts:
            return " ".join(parts)
        return None
