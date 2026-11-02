import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from ai_job_search.agents.job_discovery.agent import JobDiscoveryAgent
from ai_job_search.agents.job_discovery.verification import URLVerification
from ai_job_search.main import create_app
from ai_job_search.schemas.job_discovery import JobSearchPreferences

FIXTURES = Path(__file__).parent / "fixtures" / "job_discovery"
LINKEDIN_JOB = json.loads((FIXTURES / "linkedin_job.json").read_text())
INDEED_JOB = json.loads((FIXTURES / "indeed_job.json").read_text())
GOOGLE_RESULTS = json.loads(
    (FIXTURES / "google_search_results.json").read_text()
)
PREFERENCES = JobSearchPreferences(
    job_titles=["Senior QA Automation Engineer", "Senior SDET"],
    locations=[
        {
            "name": "Bengaluru",
            "country": "India",
            "country_code": "in",
        },
        {
            "name": "United Kingdom",
            "country": "United Kingdom",
            "country_code": "gb",
        },
        {
            "name": "Germany",
            "country": "Germany",
            "country_code": "de",
        },
        {
            "name": "Europe",
            "country": "Europe",
        },
    ],
)


def _normalize(item: dict[str, object], source: str):
    return JobDiscoveryAgent._normalize_posting(
        item=item,
        source=source,
        actor_id=f"fixtures/{source}",
        actor_run_id=f"{source}-fixture-run",
        retrieved_at=datetime.now(timezone.utc),
        preferences=PREFERENCES,
    )


def _candidate_source() -> dict[str, object]:
    return {
        "_meta": {"review_status": "pending_candidate_review"},
        "identity": {"full_name": "Candidate Example"},
        "summary": {
            "professional_summary": "Unconfirmed claim",
            "confirmed": False,
        },
        "job_preferences": {
            "target_titles": ["Senior QA Automation Engineer"],
            "also_consider_titles": ["Senior SDET"],
            "target_locations": [
                {"country": "India", "cities": ["Bengaluru"]},
                {"country": "United Kingdom", "cities": ["London"]},
                {"country": "Germany", "cities": ["Berlin"]},
            ],
            "remote_eligibility_rule": (
                "Only consider remote jobs that accept applicants residing in India."
            ),
        },
    }


def _client(database_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("JOB_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("JOB_DISCOVERY_MAX_BUDGET_USD", "1.00")
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    return TestClient(create_app(database_path))


def test_linkedin_fixture_normalizes_job_fields() -> None:
    posting = _normalize(LINKEDIN_JOB, "linkedin")

    assert posting is not None
    assert posting.title == "Senior QA Automation Engineer"
    assert posting.company == "Acme Incorporated"
    assert posting.location == "Bengaluru, Karnataka, India"
    assert posting.employment_type == "Full-time"
    assert posting.workplace_type == "On-site"
    assert "Selenium" in posting.description
    assert posting.salary == "INR 2,000,000 - 3,200,000"
    assert posting.posted_at == "2026-11-01"
    assert str(posting.application_url) == "https://careers.example/acme/qa-42"


def test_indeed_fixture_normalizes_nested_location_and_salary() -> None:
    posting = _normalize(INDEED_JOB, "indeed")

    assert posting is not None
    assert posting.company == "Acme Inc."
    assert posting.location == "Bengaluru, India"
    assert posting.country == "India"
    assert posting.employment_type == "fulltime"
    assert posting.remote_eligibility == "not_remote"
    assert "INR" in posting.salary
    assert "2000000" in posting.salary
    assert posting.posted_at == "2026-11-01"


def test_google_fixture_expands_group_and_uses_personal_info() -> None:
    records = JobDiscoveryAgent._extract_records(
        source="google",
        item=GOOGLE_RESULTS,
    )

    assert len(records) == 3
    posting = _normalize(records[0], "google")
    restricted_remote = _normalize(records[1], "google")
    outside_location = _normalize(records[2], "google")

    assert posting is not None
    assert posting.title == "Senior QA Automation Engineer | Acme"
    assert posting.company == "Acme Inc."
    assert posting.location == "Bengaluru, India"
    assert posting.posted_at == "Nov 1, 2026"
    assert restricted_remote is not None
    assert restricted_remote.remote_eligibility == "restricted"
    assert restricted_remote.location_match == "remote"
    assert outside_location is not None
    assert outside_location.location_match == "outside_preferences"


def test_mocked_discovery_persists_unique_jobs_and_separate_assessments(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "jobs.sqlite3"
    with _client(database_path, monkeypatch) as client:
        profile = client.post(
            "/api/v1/candidate-profile/import",
            json=_candidate_source(),
        )
        assert profile.status_code == 201
        details = client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={
                "preferred_locations": [
                    "Bengaluru, India",
                    "United Kingdom",
                    "Germany",
                    "Europe",
                ],
            },
        )
        assert details.status_code == 200
        agent = client.app.state.job_discovery_agent

        class FixtureExecutor:
            def __init__(self) -> None:
                self.calls: list[tuple[str, dict[str, object]]] = []
                self.run_number = 0

            def run(
                self,
                *,
                source,
                actor_id,
                actor_input,
                max_items,
                max_total_charge_usd,
            ):
                self.calls.append((source, actor_input))
                self.run_number += 1
                items = {
                    "linkedin": [LINKEDIN_JOB],
                    "indeed": [INDEED_JOB],
                    "google": [GOOGLE_RESULTS],
                }[source]
                return (
                    {
                        "id": f"fixture-run-{self.run_number}",
                        "status": "SUCCEEDED",
                    },
                    items,
                )

        class FixtureVerifier:
            def verify(self, url):
                if str(url).startswith("https://careers.example"):
                    return URLVerification(
                        status="unavailable",
                        http_status=404,
                        final_url=str(url),
                        evidence="Fixture application URL returned HTTP 404.",
                    )
                return URLVerification(
                    status="reachable",
                    http_status=200,
                    final_url=str(url),
                    evidence="Fixture posting URL returned HTTP 200.",
                )

        executor = FixtureExecutor()
        agent._executor = executor
        agent._url_verifier = FixtureVerifier()
        response = client.post(
            "/api/v1/job-discovery/runs",
            json={
                "sources": ["linkedin", "indeed", "google"],
                "max_results_per_source": 12,
                "max_total_charge_usd": "0.50",
                "confirm_live_run": True,
            },
        )
        assert response.status_code == 200, response.text
        assert {source for source, _ in executor.calls} == {
            "linkedin",
            "indeed",
            "google",
        }
        inputs = json.dumps([actor_input for _, actor_input in executor.calls])
        assert "Senior QA Automation Engineer" in inputs
        assert "Bengaluru" in inputs
        assert "Candidate Example" not in inputs
        assert "Unconfirmed claim" not in inputs

        discovered = client.get("/api/v1/jobs")
        summaries = client.get("/api/v1/job-discovery/runs")
        assert discovered.status_code == 200
        assert summaries.status_code == 200
        postings = discovered.json()["items"]
        assert discovered.json()["total"] == 3
        assert {
            tuple(posting["observed_sources"])
            for posting in postings
            if posting["title"] == "Senior QA Automation Engineer"
        } == {("linkedin", "indeed", "google")}

        restricted = next(
            posting
            for posting in postings
            if posting["title"] == "Remote SDET | Northstar"
        )
        outside = next(
            posting
            for posting in postings
            if posting["title"] == "QA Engineer | West Coast Systems"
        )
        assert restricted["remote_eligibility"] == "restricted"
        assert outside["location_match"] == "outside_preferences"
        assert summaries.json()["total"] == len(executor.calls)
        assert sum(
            run["duplicate_count"] for run in summaries.json()["items"]
        ) >= 2
        assert sum(
            run["saved_count"] for run in summaries.json()["items"]
        ) == discovered.json()["total"]

        posting_id = next(
            posting["id"]
            for posting in postings
            if posting["title"] == "Senior QA Automation Engineer"
        )
        verification = client.post(f"/api/v1/jobs/{posting_id}/verify")
        assert verification.status_code == 200
        verified = verification.json()
        assert verified["status"] == "discovered"
        assert verified["posting_url_status"] == "reachable"
        assert verified["application_url_status"] == "unavailable"
        assert verified["vacancy_assessment"] == "not_assessed"
        assert verified["employer_authenticity_assessment"] == "not_assessed"

    with _client(database_path, monkeypatch) as restarted_client:
        persisted = restarted_client.get("/api/v1/jobs")

    assert persisted.status_code == 200
    assert persisted.json()["total"] == 3
    canonical = next(
        posting
        for posting in persisted.json()["items"]
        if posting["title"] == "Senior QA Automation Engineer"
    )
    assert set(canonical["observed_sources"]) == {
        "linkedin",
        "indeed",
        "google",
    }
    assert canonical["posting_url_status"] == "reachable"
    assert canonical["vacancy_assessment"] == "not_assessed"
    assert canonical["employer_authenticity_assessment"] == "not_assessed"
