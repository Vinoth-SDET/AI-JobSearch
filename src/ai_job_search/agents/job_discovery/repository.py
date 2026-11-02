import json
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from datetime import datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_job_search.schemas.job_discovery import (
    DiscoverySource,
    JobDiscoveryRunList,
    JobDiscoveryRunResult,
    JobPosting,
    JobPostingList,
)

VerificationJobStatus = Literal[
    "verification_pending",
    "verified",
    "expired",
    "unavailable",
]


class JobPostingNotFoundError(Exception):
    pass


class SQLiteJobDiscoveryRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_discovery_runs (
                        id INTEGER PRIMARY KEY,
                        source TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        actor_run_id TEXT,
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
                run_columns = connection.execute(
                    "PRAGMA table_info(job_discovery_runs)"
                ).fetchall()
                run_id_required = any(
                    column["name"] == "actor_run_id"
                    and column["notnull"]
                    for column in run_columns
                )
                if run_id_required:
                    connection.execute(
                        """
                        ALTER TABLE job_discovery_runs
                        RENAME TO job_discovery_runs_legacy
                        """
                    )
                    connection.execute(
                        """
                        CREATE TABLE job_discovery_runs (
                            id INTEGER PRIMARY KEY,
                            source TEXT NOT NULL,
                            actor_id TEXT NOT NULL,
                            actor_run_id TEXT,
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
                        INSERT INTO job_discovery_runs
                        SELECT * FROM job_discovery_runs_legacy
                        """
                    )
                    connection.execute(
                        "DROP TABLE job_discovery_runs_legacy"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_postings (
                        id INTEGER PRIMARY KEY,
                        title TEXT NOT NULL,
                        company_key TEXT NOT NULL,
                        location_key TEXT NOT NULL,
                        source_key TEXT NOT NULL,
                        title_company_location_key TEXT NOT NULL,
                        source TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        actor_run_id TEXT NOT NULL,
                        retrieved_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_job_postings_retrieved
                    ON job_postings(retrieved_at DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_job_postings_identity
                    ON job_postings(source_key, title_company_location_key)
                    """
                )
                self._deduplicate_legacy_postings(connection)

    @classmethod
    def _deduplicate_legacy_postings(
        cls,
        connection: sqlite3.Connection,
    ) -> None:
        rows = connection.execute(
            """
            SELECT id, source_key, title_company_location_key, payload_json
            FROM job_postings
            ORDER BY id
            """
        ).fetchall()
        canonical_ids: dict[str, int] = {}
        canonical_payloads: dict[int, dict[str, object]] = {}
        canonical_source_keys: dict[int, str] = {}

        for row in rows:
            source_key = row["source_key"]
            identity_key = row["title_company_location_key"]
            canonical_id = (
                canonical_ids.get(f"url:{source_key}") if source_key else None
            )
            if canonical_id is None and identity_key != '["","",""]':
                canonical_id = canonical_ids.get(f"identity:{identity_key}")

            payload = json.loads(row["payload_json"])
            if canonical_id is None:
                canonical_id = row["id"]
                observed_sources = payload.setdefault(
                    "observed_sources",
                    [payload["source"]],
                )
                if payload["source"] not in observed_sources:
                    observed_sources.append(payload["source"])
                observed_urls = payload.setdefault(
                    "observed_posting_urls",
                    (
                        [payload["source_url"]]
                        if payload.get("source_url")
                        else []
                    ),
                )
                if (
                    payload.get("source_url")
                    and payload["source_url"] not in observed_urls
                ):
                    observed_urls.append(payload["source_url"])
                connection.execute(
                    "UPDATE job_postings SET payload_json = ? WHERE id = ?",
                    (json.dumps(payload), canonical_id),
                )
                canonical_payloads[canonical_id] = payload
                canonical_source_keys[canonical_id] = source_key
            else:
                canonical = canonical_payloads[canonical_id]
                observed_sources = canonical.setdefault(
                    "observed_sources",
                    [canonical["source"]],
                )
                for observed_source in [
                    payload["source"],
                    *payload.get("observed_sources", []),
                ]:
                    if observed_source not in observed_sources:
                        observed_sources.append(observed_source)
                observed_urls = canonical.setdefault(
                    "observed_posting_urls",
                    (
                        [canonical["source_url"]]
                        if canonical.get("source_url")
                        else []
                    ),
                )
                duplicate_urls = [
                    *(
                        [payload["source_url"]]
                        if payload.get("source_url")
                        else []
                    ),
                    *payload.get("observed_posting_urls", []),
                ]
                for observed_url in duplicate_urls:
                    if observed_url not in observed_urls:
                        observed_urls.append(observed_url)
                is_repost = bool(
                    source_key
                    and canonical_source_keys[canonical_id] != source_key
                )
                canonical["is_repost"] = (
                    canonical.get("is_repost", False)
                    or payload.get("is_repost", False)
                    or is_repost
                )
                connection.execute(
                    "UPDATE job_postings SET payload_json = ? WHERE id = ?",
                    (json.dumps(canonical), canonical_id),
                )
                connection.execute(
                    "DELETE FROM job_postings WHERE id = ?",
                    (row["id"],),
                )

            if source_key:
                canonical_ids[f"url:{source_key}"] = canonical_id
            if identity_key != '["","",""]':
                canonical_ids[f"identity:{identity_key}"] = canonical_id

    def record_run(self, result: JobDiscoveryRunResult) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO job_discovery_runs (
                        source,
                        actor_id,
                        actor_run_id,
                        status,
                        retrieved_at,
                        received_count,
                        saved_count,
                        duplicate_count,
                        expired_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(actor_id, actor_run_id) DO UPDATE SET
                        status = excluded.status,
                        retrieved_at = excluded.retrieved_at,
                        received_count = excluded.received_count,
                        saved_count = excluded.saved_count,
                        duplicate_count = excluded.duplicate_count,
                        expired_count = excluded.expired_count
                    """,
                    (
                        result.source,
                        result.actor_id,
                        result.actor_run_id,
                        result.status,
                        result.retrieved_at.isoformat(),
                        result.received_count,
                        result.saved_count,
                        result.duplicate_count,
                        result.expired_count,
                    ),
                )

    def save_posting(self, posting: JobPosting) -> JobPosting:
        serialized = posting.model_dump(mode="json", exclude={"id"})
        serialized["observed_sources"] = [posting.source]
        serialized["observed_posting_urls"] = (
            [str(posting.source_url)] if posting.source_url else []
        )
        title_key = self._normalize(posting.title)
        company_key = self._normalize_company(posting.company or "")
        location_key = self._normalize(posting.location or "")
        source_key = self._normalize_url(
            str(posting.source_url or posting.application_url or "")
        )
        identity_key = json.dumps(
            (title_key, company_key, location_key),
            separators=(",", ":"),
        )

        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = None
                if source_key:
                    existing = connection.execute(
                        """
                        SELECT id, payload_json, source_key
                        FROM job_postings
                        WHERE source_key = ?
                        ORDER BY id
                        LIMIT 1
                        """,
                        (source_key,),
                    ).fetchone()
                if existing is None and all((title_key, company_key, location_key)):
                    existing = connection.execute(
                        """
                        SELECT id, payload_json, source_key
                        FROM job_postings
                        WHERE title_company_location_key = ?
                        ORDER BY id
                        LIMIT 1
                        """,
                        (identity_key,),
                    ).fetchone()

                if existing is not None:
                    canonical = json.loads(existing["payload_json"])
                    observed_sources = canonical.setdefault(
                        "observed_sources",
                        [canonical["source"]],
                    )
                    if posting.source not in observed_sources:
                        observed_sources.append(posting.source)
                    observed_urls = canonical.setdefault(
                        "observed_posting_urls",
                        (
                            [canonical["source_url"]]
                            if canonical.get("source_url")
                            else []
                        ),
                    )
                    source_url = str(posting.source_url) if posting.source_url else None
                    if source_url and source_url not in observed_urls:
                        observed_urls.append(source_url)
                    is_repost = bool(
                        source_key
                        and existing["source_key"] != source_key
                    )
                    canonical["is_repost"] = (
                        canonical.get("is_repost", False) or is_repost
                    )
                    connection.execute(
                        "UPDATE job_postings SET payload_json = ? WHERE id = ?",
                        (
                            json.dumps(canonical),
                            existing["id"],
                        ),
                    )
                    canonical["duplicate_of"] = existing["id"]
                    canonical["is_repost"] = is_repost
                    return JobPosting.model_validate(canonical)

                cursor = connection.execute(
                    """
                    INSERT INTO job_postings (
                        title,
                        company_key,
                        location_key,
                        source_key,
                        title_company_location_key,
                        source,
                        actor_id,
                        actor_run_id,
                        retrieved_at,
                        payload_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        title_key,
                        company_key,
                        location_key,
                        source_key,
                        identity_key,
                        posting.source,
                        posting.actor_id,
                        posting.actor_run_id,
                        posting.retrieved_at.isoformat(),
                        json.dumps(serialized),
                    ),
                )
                posting_id = cursor.lastrowid
                serialized["id"] = posting_id
                connection.execute(
                    "UPDATE job_postings SET payload_json = ? WHERE id = ?",
                    (json.dumps(serialized), posting_id),
                )
        return JobPosting.model_validate(serialized)

    def get_jobs(
        self,
        *,
        source: DiscoverySource | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> JobPostingList:
        with closing(self._connect()) as connection:
            if source is None:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM job_postings
                    ORDER BY retrieved_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
                total = connection.execute(
                    "SELECT COUNT(*) FROM job_postings"
                ).fetchone()[0]
            else:
                rows = connection.execute(
                    """
                    SELECT payload_json
                    FROM job_postings
                    WHERE source = ?
                    ORDER BY retrieved_at DESC, id DESC
                    LIMIT ? OFFSET ?
                    """,
                    (source, limit, offset),
                ).fetchall()
                total = connection.execute(
                    "SELECT COUNT(*) FROM job_postings WHERE source = ?",
                    (source,),
                ).fetchone()[0]
        return JobPostingList(
            items=[
                JobPosting.model_validate(json.loads(row["payload_json"]))
                for row in rows
            ],
            total=total,
        )

    def get_posting(self, posting_id: int) -> JobPosting:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT payload_json FROM job_postings WHERE id = ?",
                (posting_id,),
            ).fetchone()
        if row is None:
            raise JobPostingNotFoundError
        return JobPosting.model_validate(json.loads(row["payload_json"]))

    def update_verification(
        self,
        posting_id: int,
        *,
        status: VerificationJobStatus,
        checked_at: datetime | None = None,
        posting_url_status: str | None = None,
        application_url_status: str | None = None,
        posting_final_url: str | None = None,
        application_final_url: str | None = None,
        posting_http_status: int | None = None,
        application_http_status: int | None = None,
        evidence: list[str] | None = None,
    ) -> JobPosting:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT payload_json FROM job_postings WHERE id = ?",
                    (posting_id,),
                ).fetchone()
                if row is None:
                    raise JobPostingNotFoundError
                serialized = json.loads(row["payload_json"])
                serialized["status"] = status
                if checked_at is not None:
                    serialized["verification_checked_at"] = (
                        checked_at.isoformat()
                    )
                elif status == "verification_pending":
                    serialized["verification_checked_at"] = None
                if posting_url_status is not None:
                    serialized["posting_url_status"] = posting_url_status
                if application_url_status is not None:
                    serialized["application_url_status"] = (
                        application_url_status
                    )
                if status != "verification_pending":
                    serialized["posting_final_url"] = posting_final_url
                    serialized["application_final_url"] = (
                        application_final_url
                    )
                    serialized["posting_http_status"] = posting_http_status
                    serialized["application_http_status"] = (
                        application_http_status
                    )
                else:
                    serialized["posting_final_url"] = None
                    serialized["application_final_url"] = None
                    serialized["posting_http_status"] = None
                    serialized["application_http_status"] = None
                if evidence is not None:
                    serialized["verification_evidence"] = evidence
                if status == "expired":
                    serialized["is_expired"] = True
                connection.execute(
                    "UPDATE job_postings SET payload_json = ? WHERE id = ?",
                    (json.dumps(serialized), posting_id),
                )
        return JobPosting.model_validate(serialized)

    def get_runs(self, *, limit: int = 50, offset: int = 0) -> JobDiscoveryRunList:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM job_discovery_runs
                ORDER BY retrieved_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM job_discovery_runs"
            ).fetchone()[0]
        return JobDiscoveryRunList(
            items=[
                JobDiscoveryRunResult(
                    source=row["source"],
                    actor_id=row["actor_id"],
                    actor_run_id=row["actor_run_id"],
                    status=row["status"],
                    retrieved_at=row["retrieved_at"],
                    received_count=row["received_count"],
                    saved_count=row["saved_count"],
                    duplicate_count=row["duplicate_count"],
                    expired_count=row["expired_count"],
                )
                for row in rows
            ],
            total=total,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(
            "".join(character if character.isalnum() else " " for character in normalized).split()
        )

    @classmethod
    def _normalize_company(cls, value: str) -> str:
        normalized = cls._normalize(value)
        normalized = " ".join(
            word
            for word in normalized.split()
            if word
            not in {
                "inc",
                "incorporated",
                "llc",
                "ltd",
                "limited",
                "corp",
                "corporation",
                "plc",
                "gmbh",
            }
        )
        return normalized

    @classmethod
    def _normalize_url(cls, value: str) -> str:
        if not value:
            return ""

        parsed = urlsplit(value)
        host = (parsed.hostname or "").casefold()
        if host.startswith("www."):
            host = host[4:]
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port
        if port is not None and not (
            (parsed.scheme.casefold() == "https" and port == 443)
            or (parsed.scheme.casefold() == "http" and port == 80)
        ):
            host = f"{host}:{port}"
        query = urlencode(
            sorted(
                (
                    (key, val)
                    for key, val in parse_qsl(
                        parsed.query,
                        keep_blank_values=True,
                    )
                    if not key.casefold().startswith("utm_")
                    and key.casefold()
                    not in {
                        "trk",
                        "trackingid",
                    }
                ),
                key=lambda pair: (pair[0].casefold(), pair[1].casefold()),
            )
        )
        path = parsed.path.rstrip("/")
        return urlunsplit(
            (parsed.scheme.casefold(), host, path, query, "")
        ).rstrip("/")
