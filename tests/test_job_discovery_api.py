from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from ai_job_search.agents.job_discovery.agent import JobDiscoveryAgent
from ai_job_search.agents.job_discovery.verification import URLVerification
from ai_job_search.main import create_app
from ai_job_search.schemas.job_discovery import (
    JobDiscoveryRunRequest,
    JobPosting,
    JobSearchLocation,
    JobSearchPreferences,
)


def _candidate_source() -> dict[str, object]:
    return {
        "_meta": {"review_status": "pending_candidate_review"},
        "identity": {"full_name": "Candidate Example"},
        "summary": {"professional_summary": "Unconfirmed claim", "confirmed": False},
        "job_preferences": {
            "target_titles": ["Senior QA Automation Engineer"],
            "also_consider_titles": ["Senior SDET"],
            "target_locations": [
                {
                    "country": "India",
                    "cities": ["Bengaluru", "Pune"],
                },
                {
                    "country": "United Kingdom",
                    "cities": ["London", "Manchester"],
                },
            ],
            "remote_eligibility_rule": (
                "Verify whether remote roles accept candidates residing in India."
            ),
        },
    }


def _client(database_path, monkeypatch, *, enabled: bool = False) -> TestClient:
    monkeypatch.setenv("JOB_DISCOVERY_ENABLED", str(enabled).lower())
    monkeypatch.setenv("JOB_DISCOVERY_MAX_BUDGET_USD", "1.00")
    if enabled:
        monkeypatch.setenv("APIFY_TOKEN", "test-token")
    else:
        monkeypatch.delenv("APIFY_TOKEN", raising=False)
    return TestClient(create_app(database_path))


def _create_candidate(client: TestClient) -> None:
    response = client.post(
        "/api/v1/candidate-profile/import",
        json=_candidate_source(),
    )
    assert response.status_code == 201
    response = client.patch(
        "/api/v1/candidate-profile/candidate-details",
        json={
            "preferred_locations": [
                "Bengaluru, India",
                "United Kingdom",
                "Germany",
                "Europe",
            ],
            "relocation_destinations": [
                "United Kingdom",
                "Germany",
                "Europe",
            ],
        },
    )
    assert response.status_code == 200


def test_preferences_use_candidate_agent_and_confirmed_locations(
    tmp_path,
    monkeypatch,
) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        _create_candidate(client)
        response = client.get("/api/v1/job-discovery/preferences")

    assert response.status_code == 200
    preferences = response.json()
    assert preferences["job_titles"] == [
        "Senior QA Automation Engineer",
        "Senior SDET",
    ]
    assert {
        (location["name"], location["country"])
        for location in preferences["locations"]
    } == {
        ("Bengaluru", "India"),
        ("London", "United Kingdom"),
        ("Manchester", "United Kingdom"),
        ("Germany", "Germany"),
        ("Europe", "Europe"),
    }
    assert "India" in preferences["remote_eligibility_rule"]


def test_preview_builds_bounded_actor_inputs_without_running_actors(
    tmp_path,
    monkeypatch,
) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        _create_candidate(client)
        response = client.post(
            "/api/v1/job-discovery/preview",
            json={
                "sources": ["linkedin", "indeed", "google"],
                "max_results_per_source": 15,
                "max_total_charge_usd": "0.10",
            },
        )

    assert response.status_code == 200
    preview = response.json()
    assert len(preview["actor_runs"]) == 9
    assert sum(
        Decimal(run["allocated_max_charge_usd"])
        for run in preview["actor_runs"]
    ) == Decimal("0.10")
    linkedin = next(
        run for run in preview["actor_runs"] if run["source"] == "linkedin"
    )
    assert linkedin["input"]["rows"] == 1
    assert "Bengaluru" in linkedin["input"]["locations"]
    indeed = [
        (
            run["input"]["country"],
            run["input"]["location"],
            run["max_items"],
            run["input"]["maxRows"],
            Decimal(run["allocated_max_charge_usd"]),
        )
        for run in preview["actor_runs"]
        if run["source"] == "indeed"
    ]
    assert indeed == [
        ("in", "Bengaluru", 2, 2, Decimal("0.01")),
        ("uk", "London", 2, 2, Decimal("0.01")),
        ("uk", "Manchester", 2, 2, Decimal("0.01")),
        ("de", "Germany", 2, 2, Decimal("0.01")),
    ]
    assert sum(run[2] for run in indeed) == 8
    assert all(
        Decimal(run[2]) * Decimal("0.005") <= run[4]
        for run in indeed
    )
    google = next(
        run for run in preview["actor_runs"] if run["source"] == "google"
    )
    google_uk = next(
        run
        for run in preview["actor_runs"]
        if run["source"] == "google"
        and run["input"].get("countryCode") == "gb"
    )
    assert google["input"]["maxPagesPerQuery"] == 1
    assert "site:greenhouse.io" in google["input"]["queries"]
    assert google["input"]["countryCode"] == "in"
    assert google_uk["input"]["countryCode"] == "gb"
    assert google["input"]["aiOverview"]["scrapeFullAiOverview"] is False
    assert google["input"]["maximumLeadsEnrichmentRecords"] == 0
    assert google["input"]["websiteContentScraper"]["enable"] is False
    assert sum(
        run["max_items"]
        for run in preview["actor_runs"]
        if run["source"] == "google"
    ) == 15
    google_runs = [
        run for run in preview["actor_runs"] if run["source"] == "google"
    ]
    assert all(
        all(
            len(query.split()) <= 32
            for query in run["input"]["queries"].splitlines()
        )
        for run in google_runs
    )


def test_live_run_requires_explicit_confirmation_and_enablement(
    tmp_path,
    monkeypatch,
) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        _create_candidate(client)
        body = {
            "sources": ["google"],
            "max_results_per_source": 2,
            "max_total_charge_usd": "0.10",
        }
        confirmation_missing = client.post(
            "/api/v1/job-discovery/runs",
            json=body,
        )
        disabled = client.post(
            "/api/v1/job-discovery/runs",
            json=body | {"confirm_live_run": True},
        )

    assert confirmation_missing.status_code == 409
    assert disabled.status_code == 503


def test_live_run_normalizes_jobs_and_marks_duplicates_and_expired(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "jobs.sqlite3"
    with _client(
        database_path,
        monkeypatch,
        enabled=True,
    ) as client:
        _create_candidate(client)
        agent = client.app.state.job_discovery_agent
        agent.get_preferences = lambda: JobSearchPreferences(
            job_titles=["Senior SDET"],
            locations=[
                JobSearchLocation(
                    name="Bengaluru",
                    country="India",
                    country_code="in",
                )
            ],
        )

        class FakeExecutor:
            def run(
                self,
                *,
                source,
                actor_id,
                actor_input,
                max_items,
                max_total_charge_usd,
            ):
                assert source == "google"
                assert actor_input["maxPagesPerQuery"] == 1
                assert max_items == 10
                assert max_total_charge_usd == Decimal("0.10")
                return (
                    {"id": "run-123", "status": "SUCCEEDED"},
                    [
                        {
                            "title": "Senior SDET",
                            "companyName": "Example Corp",
                            "location": "Remote",
                            "description": "Remote from India",
                            "url": "https://jobs.example/role/1?utm_source=google",
                            "applyUrl": "https://careers.example/apply/1",
                        },
                        {
                            "title": "Senior SDET",
                            "companyName": "Example Corp",
                            "location": "Remote",
                            "description": "Remote from India",
                            "url": "https://other.example/role/1",
                        },
                        {
                            "title": "Expired role",
                            "companyName": "Expired Corp",
                            "location": "London",
                            "expiresAt": "2000-01-01",
                            "url": "https://jobs.example/expired",
                        },
                    ],
                )

        agent._executor = FakeExecutor()
        class FakeVerifier:
            def verify(self, url):
                if str(url).startswith("https://careers.example"):
                    return URLVerification(
                        status="unavailable",
                        http_status=404,
                        final_url=str(url),
                        evidence="The URL returned HTTP 404.",
                    )
                return URLVerification(
                    status="reachable",
                    http_status=200,
                    final_url=str(url),
                    evidence="The URL returned HTTP 200.",
                )

        agent._url_verifier = FakeVerifier()
        response = client.post(
            "/api/v1/job-discovery/runs",
            json={
                "sources": ["google"],
                "max_results_per_source": 10,
                "max_total_charge_usd": "0.10",
                "confirm_live_run": True,
            },
        )
        persisted = client.get("/api/v1/jobs")
        persisted_runs = client.get("/api/v1/job-discovery/runs")
        verify_response = client.post(
            f"/api/v1/jobs/{response.json()['jobs'][0]['id']}/verify"
        )

    assert response.status_code == 200
    result = response.json()
    assert result["runs"][0]["received_count"] == 3
    assert result["runs"][0]["saved_count"] == 1
    assert result["runs"][0]["duplicate_count"] == 1
    assert result["runs"][0]["expired_count"] == 1
    assert result["jobs"][0]["remote_eligibility"] == "eligible"
    assert result["jobs"][0]["status"] == "discovered"
    assert result["jobs"][0]["location_match"] == "remote"
    assert result["jobs"][0]["application_url"] == "https://careers.example/apply/1"
    assert len(result["jobs"]) == 1
    assert persisted.status_code == 200
    assert persisted.json()["total"] == 1
    assert persisted_runs.status_code == 200
    assert persisted_runs.json()["total"] == 1
    assert persisted_runs.json()["items"][0]["actor_run_id"] == "run-123"
    assert verify_response.status_code == 200
    verified = verify_response.json()
    assert verified["status"] == "discovered"
    assert verified["posting_url_status"] == "reachable"
    assert verified["posting_http_status"] == 200
    assert verified["application_url_status"] == "unavailable"
    assert verified["application_http_status"] == 404
    assert verified["vacancy_assessment"] == "not_assessed"
    assert verified["employer_authenticity_assessment"] == "not_assessed"
    assert verified["verification_checked_at"] is not None
    assert persisted.json()["items"][0]["is_repost"] is True
    assert all(
        posting["title"] != "Expired role"
        for posting in persisted.json()["items"]
    )
    with _client(database_path, monkeypatch) as restarted_client:
        assert restarted_client.get(
            "/api/v1/job-discovery/runs"
        ).json()["total"] == 1


def test_missing_candidate_profile_returns_not_found(tmp_path, monkeypatch) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        response = client.get("/api/v1/job-discovery/preferences")

    assert response.status_code == 404


def test_budget_must_cover_every_actor_run(tmp_path, monkeypatch) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        _create_candidate(client)
        response = client.post(
            "/api/v1/job-discovery/preview",
            json={
                "sources": ["linkedin", "indeed", "google"],
                "max_results_per_source": 10,
                "max_total_charge_usd": "0.01",
            },
        )

    assert response.status_code == 422


def test_actor_error_is_sanitized_and_persisted(tmp_path, monkeypatch) -> None:
    with _client(
        tmp_path / "jobs.sqlite3",
        monkeypatch,
        enabled=True,
    ) as client:
        _create_candidate(client)
        agent = client.app.state.job_discovery_agent

        class FailingExecutor:
            def run(self, *, source, actor_id, **kwargs):
                raise agent_error()

        def agent_error():
            from ai_job_search.agents.job_discovery.agent import (
                JobDiscoveryExecutionError,
            )

            return JobDiscoveryExecutionError(
                "The Actor run timed out.",
                source="google",
                actor_id="apify/google-search-scraper",
                status="TIMED-OUT",
            )

        agent._executor = FailingExecutor()
        agent.get_preferences = lambda: JobSearchPreferences(
            job_titles=["Senior SDET"],
            locations=[
                JobSearchLocation(name="Bengaluru", country="India", country_code="in")
            ],
        )
        response = client.post(
            "/api/v1/job-discovery/runs",
            json={
                "sources": ["google"],
                "max_results_per_source": 4,
                "max_total_charge_usd": "0.10",
                "confirm_live_run": True,
            },
        )
        runs = client.get("/api/v1/job-discovery/runs")

    assert response.status_code == 502
    assert "token" not in response.text.casefold()
    assert runs.status_code == 200
    assert runs.json()["total"] == 1
    assert runs.json()["items"][0]["status"] == "TIMED-OUT"
    assert runs.json()["items"][0]["actor_run_id"] is None


def test_empty_actor_dataset_is_a_successful_empty_result(
    tmp_path,
    monkeypatch,
) -> None:
    with _client(
        tmp_path / "jobs.sqlite3",
        monkeypatch,
        enabled=True,
    ) as client:
        _create_candidate(client)
        agent = client.app.state.job_discovery_agent
        agent.get_preferences = lambda: JobSearchPreferences(
            job_titles=["Senior SDET"],
            locations=[
                JobSearchLocation(name="Bengaluru", country="India", country_code="in")
            ],
        )

        class EmptyExecutor:
            def run(self, *, source, actor_id, **kwargs):
                return (
                    {"id": "empty-run", "status": "SUCCEEDED"},
                    [],
                )

        agent._executor = EmptyExecutor()
        response = client.post(
            "/api/v1/job-discovery/runs",
            json={
                "sources": ["google"],
                "max_results_per_source": 4,
                "max_total_charge_usd": "0.10",
                "confirm_live_run": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["jobs"] == []
    assert response.json()["runs"][0]["status"] == "SUCCEEDED"
    assert response.json()["runs"][0]["received_count"] == 0
    assert response.json()["runs"][0]["saved_count"] == 0


def test_normalizes_documented_indeed_output_and_location_eligibility() -> None:
    preferences = JobSearchPreferences(
        job_titles=["Senior SDET"],
        locations=[
            JobSearchLocation(name="Bengaluru", country="India", country_code="in"),
            JobSearchLocation(name="Europe", country="Europe"),
        ],
    )
    posting = JobDiscoveryAgent._normalize_posting(
        item={
            "title": "Senior SDET",
            "companyName": "Example GmbH",
            "location": {
                "city": "Bengaluru",
                "country": "India",
                "countryCode": "in",
            },
            "descriptionText": "Selenium automation role",
            "jobUrl": "https://jobs.example/role/42",
            "applyUrl": "https://careers.example/apply/42",
            "jobType": ["fulltime"],
            "isRemote": False,
            "salary": {
                "salaryCurrency": "INR",
                "salaryMin": 100000,
                "salaryMax": 120000,
                "salaryType": "yearly",
            },
            "datePublished": "2026-10-30",
            "expired": False,
        },
        source="indeed",
        actor_id="borderline/indeed-scraper",
        actor_run_id="indeed-42",
        retrieved_at=datetime.now(timezone.utc),
        preferences=preferences,
    )

    assert posting is not None
    assert posting.location == "Bengaluru, India"
    assert posting.country == "India"
    assert posting.location_match == "preferred_city"
    assert posting.remote_eligibility == "not_remote"
    assert posting.employment_type == "fulltime"
    assert "INR" in posting.salary
    assert "100000" in posting.salary
    assert posting.posted_at == "2026-10-30"
    assert posting.is_expired is False


def test_explicit_actor_expiration_and_remote_restrictions() -> None:
    now = datetime.now(timezone.utc)
    assert JobDiscoveryAgent._expired_status(
        {"expired": True},
        None,
        now,
    )
    assert (
        JobDiscoveryAgent._remote_eligibility(
            "remote",
            "Remote - India",
            None,
        )
        == "eligible"
    )
    assert (
        JobDiscoveryAgent._remote_eligibility(
            "remote",
            "Remote, US only",
            None,
        )
        == "restricted"
    )
    assert (
        JobDiscoveryAgent._remote_eligibility(
            "remote",
            "Remote",
            None,
        )
        == "unknown"
    )
    assert (
        JobDiscoveryAgent._remote_eligibility(
            "onsite",
            "Not remote",
            None,
        )
        == "not_remote"
    )


def test_google_grouped_results_are_expanded_to_job_records() -> None:
    records = JobDiscoveryAgent._extract_records(
        source="google",
        item={
            "organicResults": [
                {
                    "title": "Senior SDET",
                    "url": "https://jobs.example/sdet",
                    "description": "Open role",
                },
                {"title": "QA Engineer", "url": "https://jobs.example/qa"},
            ]
        },
    )
    assert len(records) == 2
    assert records[0]["title"] == "Senior SDET"


def test_expired_posting_is_excluded_before_verification(tmp_path, monkeypatch) -> None:
    with _client(
        tmp_path / "jobs.sqlite3",
        monkeypatch,
        enabled=True,
    ) as client:
        _create_candidate(client)
        agent = client.app.state.job_discovery_agent
        agent.get_preferences = lambda: JobSearchPreferences(
            job_titles=["Senior SDET"],
            locations=[
                JobSearchLocation(name="Bengaluru", country="India", country_code="in")
            ],
        )

        class ExpiredExecutor:
            def run(self, *, source, actor_id, **kwargs):
                return (
                    {"id": "expired-run", "status": "SUCCEEDED"},
                    [
                        {
                            "title": "Expired role",
                            "expired": True,
                            "url": "https://jobs.example/expired",
                        }
                    ],
                )

        agent._executor = ExpiredExecutor()
        response = client.post(
            "/api/v1/job-discovery/runs",
            json={
                "sources": ["google"],
                "max_results_per_source": 4,
                "max_total_charge_usd": "0.10",
                "confirm_live_run": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["jobs"] == []
    assert response.json()["runs"][0]["expired_count"] == 1


def test_verifying_missing_posting_returns_not_found(tmp_path, monkeypatch) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        response = client.post("/api/v1/jobs/999/verify")

    assert response.status_code == 404


def test_http_gone_does_not_claim_vacancy_is_closed(tmp_path, monkeypatch) -> None:
    with _client(tmp_path / "jobs.sqlite3", monkeypatch) as client:
        agent = client.app.state.job_discovery_agent
        posting = agent._repository.save_posting(
            JobPosting(
                title="Senior SDET",
                remote_eligibility="unknown",
                source="google",
                actor_id="apify/google-search-scraper",
                actor_run_id="gone-fixture",
                source_url="https://jobs.example/gone-role",
                retrieved_at=datetime.now(timezone.utc),
            )
        )

        class GoneVerifier:
            def verify(self, url):
                return URLVerification(
                    status="expired",
                    http_status=410,
                    final_url=str(url),
                    evidence="Fixture URL returned HTTP 410.",
                )

        agent._url_verifier = GoneVerifier()
        response = client.post(f"/api/v1/jobs/{posting.id}/verify")

    assert response.status_code == 200
    assert response.json()["status"] == "discovered"
    assert response.json()["posting_url_status"] == "expired"
    assert response.json()["vacancy_assessment"] == "not_assessed"
    assert response.json()["employer_authenticity_assessment"] == "not_assessed"
