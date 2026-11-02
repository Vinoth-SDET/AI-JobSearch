import sqlite3
from datetime import datetime, timezone

from ai_job_search.agents.job_discovery.repository import (
    SQLiteJobDiscoveryRepository,
)
from ai_job_search.schemas.job_discovery import (
    JobDiscoveryRunResult,
    JobPosting,
)


def _posting(
    *,
    source: str = "linkedin",
    actor_run_id: str = "run-1",
    source_url: str = "https://www.jobs.example/role?id=7&utm_source=linkedin",
    company: str = "Acme, Inc.",
) -> JobPosting:
    return JobPosting(
        title="Senior QA Automation Engineer",
        company=company,
        location="Bengaluru, India",
        remote_eligibility="unknown",
        source=source,
        actor_id=f"actor/{source}",
        actor_run_id=actor_run_id,
        source_url=source_url,
        retrieved_at=datetime.now(timezone.utc),
    )


def test_duplicate_detection_normalizes_tracking_and_matches_reposts(
    tmp_path,
) -> None:
    repository = SQLiteJobDiscoveryRepository(tmp_path / "jobs.sqlite3")
    repository.initialize()

    original = repository.save_posting(_posting())
    cross_source_duplicate = repository.save_posting(
        _posting(
            source="indeed",
            actor_run_id="run-2",
            source_url="https://jobs.example/role?id=7&trk=indeed",
            company="Acme Ltd",
        )
    )
    repost = repository.save_posting(
        _posting(
            source="google",
            actor_run_id="run-3",
            source_url="https://careers.example/senior-qa-engineer",
        )
    )

    assert cross_source_duplicate.duplicate_of == original.id
    assert cross_source_duplicate.is_repost is False
    assert repost.duplicate_of == original.id
    assert repost.is_repost is True
    assert repository.get_jobs().total == 3


def test_initialize_migrates_legacy_non_nullable_run_id(tmp_path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE job_discovery_runs (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                actor_run_id TEXT NOT NULL,
                status TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                received_count INTEGER NOT NULL,
                saved_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                expired_count INTEGER NOT NULL,
                UNIQUE (actor_id, actor_run_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO job_discovery_runs VALUES (
                1, 'google', 'apify/google-search-scraper', 'run-old',
                'SUCCEEDED', '2025-01-01T00:00:00+00:00',
                3, 2, 1, 0
            )
            """
        )

    repository = SQLiteJobDiscoveryRepository(database_path)
    repository.initialize()
    repository.record_run(
        JobDiscoveryRunResult(
            source="google",
            actor_id="apify/google-search-scraper",
            status="FAILED",
            retrieved_at=datetime.now(timezone.utc),
            received_count=0,
            saved_count=0,
            duplicate_count=0,
            expired_count=0,
        )
    )

    runs = repository.get_runs()
    assert runs.total == 2
    assert {run.actor_run_id for run in runs.items} == {"run-old", None}


def test_legacy_verification_payload_is_migrated() -> None:
    posting_data = _posting().model_dump(mode="json")
    posting_data["verification_status"] = "pending"

    posting = JobPosting.model_validate(posting_data)

    assert posting.status == "discovered"
    assert "verification_status" not in posting.model_dump()
