import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ai_job_search.schemas.candidate_profile import (
    CandidateProfile,
    CandidateProfileHistory,
    CandidateProfileHistoryItem,
    CandidateProfileRecord,
)


class ProfileAlreadyExistsError(Exception):
    """Raised when creating a profile while one already exists."""


class ProfileNotFoundError(Exception):
    """Raised when a profile operation requires a profile that is absent."""


class InvalidConfirmationPathError(Exception):
    """Raised when a review path does not identify a pending profile claim."""


class ProfileHasUnconfirmedClaimsError(Exception):
    """Raised when replacing an imported profile with unconfirmed claims."""


class SQLiteProfileRepository:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def initialize(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS candidate_profiles (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        profile_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        source_profile_json TEXT,
                        candidate_confirmed_details_json TEXT,
                        review_status TEXT NOT NULL
                            DEFAULT 'pending_candidate_review'
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS candidate_profile_history (
                        version INTEGER PRIMARY KEY,
                        action TEXT NOT NULL,
                        profile_json TEXT NOT NULL,
                        source_profile_json TEXT,
                        candidate_confirmed_details_json TEXT,
                        review_status TEXT NOT NULL,
                        profile_created_at TEXT NOT NULL,
                        profile_updated_at TEXT NOT NULL,
                        changed_at TEXT NOT NULL
                    )
                    """
                )
                history_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(candidate_profile_history)"
                    )
                }
                for column in ("profile_created_at", "profile_updated_at"):
                    if column not in history_columns:
                        connection.execute(
                            f"ALTER TABLE candidate_profile_history "
                            f"ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                        )
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(candidate_profiles)"
                    )
                }
                if "source_profile_json" not in columns:
                    connection.execute(
                        "ALTER TABLE candidate_profiles "
                        "ADD COLUMN source_profile_json TEXT"
                    )
                if "review_status" not in columns:
                    connection.execute(
                        "ALTER TABLE candidate_profiles "
                        "ADD COLUMN review_status TEXT NOT NULL "
                        "DEFAULT 'pending_candidate_review'"
                    )
                if "candidate_confirmed_details_json" not in columns:
                    connection.execute(
                        "ALTER TABLE candidate_profiles "
                        "ADD COLUMN candidate_confirmed_details_json TEXT"
                    )
                history_count = connection.execute(
                    "SELECT COUNT(*) FROM candidate_profile_history"
                ).fetchone()[0]
                if history_count == 0:
                    row = connection.execute(
                        "SELECT 1 FROM candidate_profiles WHERE id = 1"
                    ).fetchone()
                    if row is not None:
                        self._record_history(
                            connection,
                            "profile_migrated",
                            self._now(),
                        )

    def create(self, profile: CandidateProfile) -> CandidateProfileRecord:
        now = self._now()
        with closing(self._connect()) as connection:
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO candidate_profiles
                            (
                                id,
                                profile_json,
                                created_at,
                                updated_at,
                                source_profile_json,
                                candidate_confirmed_details_json,
                                review_status
                            )
                        VALUES (1, ?, ?, ?, NULL, NULL, 'pending_candidate_review')
                        """,
                        (self._serialize(profile), now, now),
                    )
                    self._record_history(connection, "profile_created", now)
            except sqlite3.IntegrityError as error:
                if self._profile_exists():
                    raise ProfileAlreadyExistsError from error
                raise
        return self.get()

    def import_profile(
        self,
        profile: CandidateProfile,
        source_profile: dict[str, object],
    ) -> CandidateProfileRecord:
        now = self._now()
        with closing(self._connect()) as connection:
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO candidate_profiles
                            (
                                id,
                                profile_json,
                                created_at,
                                updated_at,
                                source_profile_json,
                                candidate_confirmed_details_json,
                                review_status
                            )
                        VALUES (
                            1,
                            ?,
                            ?,
                            ?,
                            ?,
                            NULL,
                            'pending_candidate_review'
                        )
                        """,
                        (
                            self._serialize(profile),
                            now,
                            now,
                            json.dumps(source_profile),
                        ),
                    )
                    self._record_history(connection, "profile_imported", now)
            except sqlite3.IntegrityError as error:
                if self._profile_exists():
                    raise ProfileAlreadyExistsError from error
                raise
        return self.get()

    def get(self) -> CandidateProfileRecord:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    profile_json,
                    created_at,
                    updated_at,
                    source_profile_json,
                    candidate_confirmed_details_json,
                    review_status
                FROM candidate_profiles
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            raise ProfileNotFoundError
        source_profile = (
            json.loads(row["source_profile_json"])
            if row["source_profile_json"] is not None
            else None
        )
        candidate_confirmed_details = (
            json.loads(row["candidate_confirmed_details_json"])
            if row["candidate_confirmed_details_json"] is not None
            else {}
        )
        return CandidateProfileRecord(
            profile=CandidateProfile.model_validate_json(row["profile_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            review_status=row["review_status"],
            source_profile=source_profile,
            unconfirmed_paths=self._unconfirmed_paths(source_profile),
            candidate_confirmed_details=candidate_confirmed_details,
        )

    def replace(self, profile: CandidateProfile) -> CandidateProfileRecord:
        now = self._now()
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    """
                    SELECT source_profile_json
                    FROM candidate_profiles
                    WHERE id = 1
                    """
                ).fetchone()
                if row is None:
                    raise ProfileNotFoundError
                if row["source_profile_json"] is not None:
                    source_profile = json.loads(row["source_profile_json"])
                    if self._unconfirmed_paths(source_profile):
                        raise ProfileHasUnconfirmedClaimsError
                result = connection.execute(
                    """
                    UPDATE candidate_profiles
                    SET
                        profile_json = ?,
                        updated_at = ?,
                        source_profile_json = NULL,
                        candidate_confirmed_details_json = NULL,
                        review_status = 'pending_candidate_review'
                    WHERE id = 1
                    """,
                    (self._serialize(profile), now),
                )
                if result.rowcount:
                    self._record_history(connection, "profile_replaced", now)
        return self.get()

    def update_candidate_confirmed_details(
        self,
        details: dict[str, object],
    ) -> CandidateProfileRecord:
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    """
                    SELECT candidate_confirmed_details_json
                    FROM candidate_profiles
                    WHERE id = 1
                    """
                ).fetchone()
                if row is None:
                    raise ProfileNotFoundError
                existing = (
                    json.loads(row["candidate_confirmed_details_json"])
                    if row["candidate_confirmed_details_json"] is not None
                    else {}
                )
                existing.update(details)
                connection.execute(
                    """
                    UPDATE candidate_profiles
                    SET candidate_confirmed_details_json = ?, updated_at = ?
                    WHERE id = 1
                    """,
                    (json.dumps(existing), self._now()),
                )
                self._record_history(
                    connection,
                    "candidate_details_updated",
                    self._now(),
                )
        return self.get()

    def confirm_paths(self, paths: list[str]) -> CandidateProfileRecord:
        with closing(self._connect()) as connection:
            with connection:
                row = connection.execute(
                    """
                    SELECT source_profile_json
                    FROM candidate_profiles
                    WHERE id = 1
                    """
                ).fetchone()
                if row is None:
                    raise ProfileNotFoundError
                if row["source_profile_json"] is None:
                    raise InvalidConfirmationPathError

                source_profile = json.loads(row["source_profile_json"])
                targets: list[dict[str, object]] = []
                for path in paths:
                    target = self._resolve_confirmation_target(
                        source_profile,
                        path,
                    )
                    if (
                        not isinstance(target, dict)
                        or target.get("confirmed") is not False
                    ):
                        raise InvalidConfirmationPathError
                    targets.append(target)
                for target in targets:
                    target["confirmed"] = True

                unconfirmed_paths = self._unconfirmed_paths(source_profile)
                review_status = (
                    "confirmed"
                    if not unconfirmed_paths
                    else "pending_candidate_review"
                )
                metadata = source_profile.get("_meta")
                if isinstance(metadata, dict):
                    metadata["review_status"] = review_status

                connection.execute(
                    """
                    UPDATE candidate_profiles
                    SET
                        source_profile_json = ?,
                        review_status = ?,
                        updated_at = ?
                    WHERE id = 1
                    """,
                    (
                        json.dumps(source_profile),
                        review_status,
                        self._now(),
                    ),
                )
                self._record_history(
                    connection,
                    "claims_confirmed",
                    self._now(),
                )
        return self.get()

    def get_history(self) -> CandidateProfileHistory:
        with closing(self._connect()) as connection:
            profile_exists = connection.execute(
                "SELECT 1 FROM candidate_profiles WHERE id = 1"
            ).fetchone()
            if profile_exists is None:
                raise ProfileNotFoundError
            rows = connection.execute(
                """
                SELECT
                    version,
                    action,
                    profile_json,
                    source_profile_json,
                    candidate_confirmed_details_json,
                    review_status,
                    COALESCE(NULLIF(profile_created_at, ''), changed_at)
                        AS profile_created_at,
                    COALESCE(NULLIF(profile_updated_at, ''), changed_at)
                        AS profile_updated_at,
                    changed_at
                FROM candidate_profile_history
                ORDER BY version
                """
            ).fetchall()

        items = []
        for row in rows:
            source_profile = (
                json.loads(row["source_profile_json"])
                if row["source_profile_json"] is not None
                else None
            )
            candidate_confirmed_details = (
                json.loads(row["candidate_confirmed_details_json"])
                if row["candidate_confirmed_details_json"] is not None
                else {}
            )
            items.append(
                CandidateProfileHistoryItem(
                    version=row["version"],
                    action=row["action"],
                    changed_at=row["changed_at"],
                    record=CandidateProfileRecord(
                        profile=CandidateProfile.model_validate_json(
                            row["profile_json"]
                        ),
                        created_at=row["profile_created_at"],
                        updated_at=row["profile_updated_at"],
                        review_status=row["review_status"],
                        source_profile=source_profile,
                        unconfirmed_paths=self._unconfirmed_paths(source_profile),
                        candidate_confirmed_details=candidate_confirmed_details,
                    ),
                )
            )
        return CandidateProfileHistory(items=items)

    def delete(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                result = connection.execute(
                    "SELECT 1 FROM candidate_profiles WHERE id = 1"
                ).fetchone()
                if result is None:
                    raise ProfileNotFoundError
                connection.execute("DELETE FROM candidate_profile_history")
                result = connection.execute(
                    "DELETE FROM candidate_profiles WHERE id = 1"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _profile_exists(self) -> bool:
        with closing(self._connect()) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM candidate_profiles WHERE id = 1"
                ).fetchone()
                is not None
            )

    @staticmethod
    def _record_history(
        connection: sqlite3.Connection,
        action: str,
        changed_at: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT
                profile_json,
                source_profile_json,
                candidate_confirmed_details_json,
                review_status,
                created_at,
                updated_at
            FROM candidate_profiles
            WHERE id = 1
            """
        ).fetchone()
        if row is None:
            raise ProfileNotFoundError
        version = connection.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM candidate_profile_history"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO candidate_profile_history (
                version,
                action,
                profile_json,
                source_profile_json,
                candidate_confirmed_details_json,
                review_status,
                profile_created_at,
                profile_updated_at,
                changed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version,
                action,
                row["profile_json"],
                row["source_profile_json"],
                row["candidate_confirmed_details_json"],
                row["review_status"],
                row["created_at"],
                row["updated_at"],
                changed_at,
            ),
        )

    @classmethod
    def _unconfirmed_paths(cls, value: object, path: str = "") -> list[str]:
        paths: list[str] = []
        if isinstance(value, dict):
            if value.get("confirmed") is False and path:
                paths.append(path)
            for key, child in value.items():
                if key == "confirmed":
                    continue
                child_path = f"{path}/{cls._escape_json_pointer(str(key))}"
                paths.extend(cls._unconfirmed_paths(child, child_path))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                paths.extend(cls._unconfirmed_paths(child, f"{path}/{index}"))
        return paths

    @classmethod
    def _resolve_confirmation_target(
        cls,
        source_profile: dict[str, object],
        path: str,
    ) -> object:
        current: object = source_profile
        try:
            for component in path[1:].split("/"):
                key = cls._unescape_json_pointer(component)
                if isinstance(current, dict):
                    current = current[key]
                elif isinstance(current, list):
                    current = current[int(key)]
                else:
                    raise KeyError(key)
        except (IndexError, KeyError, ValueError) as error:
            raise InvalidConfirmationPathError from error
        return current

    @staticmethod
    def _escape_json_pointer(value: str) -> str:
        return value.replace("~", "~0").replace("/", "~1")

    @staticmethod
    def _unescape_json_pointer(value: str) -> str:
        return value.replace("~1", "/").replace("~0", "~")

    @staticmethod
    def _serialize(profile: CandidateProfile) -> str:
        return json.dumps(profile.model_dump(mode="json"))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
