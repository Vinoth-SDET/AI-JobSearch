import json
import sqlite3

from fastapi.testclient import TestClient

from ai_job_search.main import create_app


def make_client(database_path) -> TestClient:
    return TestClient(create_app(database_path))


def test_candidate_profile_crud_and_persistence(tmp_path) -> None:
    database_path = tmp_path / "candidate.sqlite3"
    profile = {
        "full_name": "Candidate Example",
        "email": "candidate@example.com",
        "skills": ["Python", "AI agents"],
        "experience": [
            {
                "company": "Example Co",
                "title": "AI Engineer",
                "accomplishments": ["Built an agent"],
            }
        ],
        "links": [
            {"label": "LinkedIn", "url": "https://linkedin.com/in/example"}
        ],
    }

    with make_client(database_path) as client:
        created = client.post("/api/v1/candidate-profile", json=profile)
        assert created.status_code == 201
        assert created.json()["profile"] == {
            "full_name": "Candidate Example",
            "email": "candidate@example.com",
            "phone": None,
            "location": None,
            "headline": None,
            "summary": None,
            "skills": ["Python", "AI agents"],
            "experience": [
                {
                    "company": "Example Co",
                    "title": "AI Engineer",
                    "location": None,
                    "start_date": None,
                    "end_date": None,
                    "description": None,
                    "accomplishments": ["Built an agent"],
                }
            ],
            "education": [],
            "certifications": [],
            "links": [
                {
                    "label": "LinkedIn",
                    "url": "https://linkedin.com/in/example",
                }
            ],
        }
        created_at = created.json()["created_at"]
        assert client.get("/api/v1/candidate-profile").json()["created_at"] == created_at

        updated_profile = profile | {"headline": "Senior AI Engineer"}
        updated = client.put(
            "/api/v1/candidate-profile",
            json=updated_profile,
        )
        assert updated.status_code == 200
        assert updated.json()["profile"]["headline"] == "Senior AI Engineer"
        assert updated.json()["created_at"] == created_at

    with make_client(database_path) as client:
        assert client.get("/api/v1/candidate-profile").json()["profile"][
            "headline"
        ] == "Senior AI Engineer"
        assert client.delete("/api/v1/candidate-profile").status_code == 204
        assert client.get("/api/v1/candidate-profile").status_code == 404


def test_imported_profile_rejects_replacement_until_claims_are_confirmed(
    tmp_path,
) -> None:
    source = {
        "_meta": {"review_status": "pending_candidate_review"},
        "identity": {"full_name": "Candidate Example"},
        "summary": {
            "professional_summary": "Imported summary",
            "confirmed": False,
        },
    }

    with make_client(tmp_path / "candidate.sqlite3") as client:
        imported = client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        )
        assert imported.status_code == 201
        before = imported.json()

        rejected = client.put(
            "/api/v1/candidate-profile",
            json={"full_name": "Changed Name"},
        )
        assert rejected.status_code == 409
        assert client.get("/api/v1/candidate-profile").json() == before

        confirmed = client.post(
            "/api/v1/candidate-profile/review/confirm",
            json={"paths": ["/summary"]},
        )
        assert confirmed.status_code == 200
        replacement = client.put(
            "/api/v1/candidate-profile",
            json={"full_name": "Candidate Example"},
        )
        assert replacement.status_code == 200


def test_profile_history_tracks_changes_and_survives_restart(tmp_path) -> None:
    database_path = tmp_path / "candidate.sqlite3"
    source = {
        "_meta": {"review_status": "pending_candidate_review"},
        "identity": {
            "full_name": "Candidate Example",
            "email": "candidate@example.com",
        },
        "summary": {"professional_summary": "Summary", "confirmed": False},
    }

    with make_client(database_path) as client:
        assert client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        ).status_code == 201
        assert client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={"notice_period": "Immediate"},
        ).status_code == 200
        assert client.post(
            "/api/v1/candidate-profile/review/confirm",
            json={"paths": ["/summary"]},
        ).status_code == 200
        history = client.get("/api/v1/candidate-profile/history")
        assert history.status_code == 200
        assert [item["action"] for item in history.json()["items"]] == [
            "profile_imported",
            "candidate_details_updated",
            "claims_confirmed",
        ]
        assert [item["version"] for item in history.json()["items"]] == [1, 2, 3]
        assert (
            history.json()["items"][1]["record"]["candidate_confirmed_details"][
                "notice_period"
            ]
            == "Immediate"
        )

    with make_client(database_path) as restarted_client:
        assert restarted_client.get(
            "/api/v1/candidate-profile"
        ).json()["source_profile"]["summary"]["confirmed"] is True
        restarted_history = restarted_client.get(
            "/api/v1/candidate-profile/history"
        )
        assert restarted_history.status_code == 200
        assert len(restarted_history.json()["items"]) == 3


def test_invalid_candidate_detail_update_does_not_corrupt_profile(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        created = client.post(
            "/api/v1/candidate-profile",
            json={"full_name": "Candidate Example", "email": "candidate@example.com"},
        )
        assert created.status_code == 201
        before = client.get("/api/v1/candidate-profile").json()

        invalid = client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={
                "notice_period": "Immediate",
                "target_compensation": {"amount_lpa": -32},
            },
        )
        assert invalid.status_code == 422
        assert client.get("/api/v1/candidate-profile").json() == before


def test_successful_api_requests_do_not_log_candidate_values(
    tmp_path,
    caplog,
) -> None:
    private_email = "private.candidate@example.com"
    with make_client(tmp_path / "candidate.sqlite3") as client:
        assert client.post(
            "/api/v1/candidate-profile",
            json={"full_name": "Private Candidate", "email": private_email},
        ).status_code == 201
        assert client.get("/api/v1/candidate-profile").status_code == 200

    assert private_email not in caplog.text
    assert "Private Candidate" not in caplog.text


def test_create_conflict_and_missing_update_or_delete(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        assert client.put(
            "/api/v1/candidate-profile",
            json={"full_name": "Candidate Example"},
        ).status_code == 404
        assert client.delete("/api/v1/candidate-profile").status_code == 404

        profile = {"full_name": "Candidate Example"}
        assert client.post("/api/v1/candidate-profile", json=profile).status_code == 201
        assert client.post("/api/v1/candidate-profile", json=profile).status_code == 409


def test_invalid_profile_is_rejected(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        for profile in (
            {"full_name": "   "},
            {"full_name": "Candidate Example", "email": "not-an-email"},
            {
                "full_name": "Candidate Example",
                "links": [{"label": "LinkedIn", "url": "javascript:alert(1)"}],
            },
            {"full_name": "Candidate Example", "unrecognized": "value"},
        ):
            response = client.post("/api/v1/candidate-profile", json=profile)
            assert response.status_code == 422


def test_profile_requires_a_name(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        assert client.post(
            "/api/v1/candidate-profile",
            json={"skills": ["Python"]},
        ).status_code == 422


def test_import_preserves_source_and_marks_claims_pending(tmp_path) -> None:
    source = {
        "_meta": {
            "schema_version": "0.1",
            "review_status": "pending_candidate_review",
        },
        "identity": {
            "full_name": "Candidate Example",
            "email": "candidate@example.com",
            "current_city": "Hosur",
            "current_country": "India",
            "linkedin_url": "linkedin.com/in/candidate",
        },
        "summary": {
            "headline": "Senior QA Engineer",
            "professional_summary": "Experienced quality engineer.",
            "total_experience_years": "12+",
            "confirmed": False,
        },
        "employment_history": [
            {
                "company": "Example Co",
                "title": "QA Engineer",
                "start_date": "2022-01",
                "end_date": "present",
                "achievements": [
                    {
                        "text": "Improved regression execution",
                        "metric": "35%",
                        "confirmed": False,
                    }
                ],
            }
        ],
        "skills": [
            {
                "name": "Selenium",
                "category": "automation",
                "confirmed": False,
            }
        ],
        "job_preferences": {"target_titles": ["Senior SDET"]},
    }

    with make_client(tmp_path / "candidate.sqlite3") as client:
        imported = client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        )
        assert imported.status_code == 201
        record = imported.json()
        assert record["review_status"] == "pending_candidate_review"
        assert record["source_profile"] == source
        assert record["unconfirmed_paths"] == [
            "/summary",
            "/employment_history/0/achievements/0",
            "/skills/0",
        ]
        assert record["profile"]["full_name"] == "Candidate Example"
        assert record["profile"]["location"] == "Hosur, India"
        assert record["profile"]["skills"] == ["Selenium"]
        assert record["profile"]["experience"][0]["accomplishments"] == [
            "Improved regression execution (35%)"
        ]


def test_candidate_confirms_only_selected_claims(tmp_path) -> None:
    source = {
        "_meta": {"review_status": "pending_candidate_review"},
        "identity": {"full_name": "Candidate Example"},
        "summary": {"professional_summary": "Quality engineer.", "confirmed": False},
        "skills": [{"name": "Selenium", "confirmed": False}],
    }

    with make_client(tmp_path / "candidate.sqlite3") as client:
        assert client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        ).status_code == 201

        invalid_batch = client.post(
            "/api/v1/candidate-profile/review/confirm",
            json={"paths": ["/summary", "/missing"]},
        )
        assert invalid_batch.status_code == 422
        assert client.get("/api/v1/candidate-profile").json()[
            "source_profile"
        ]["summary"]["confirmed"] is False

        partial = client.post(
            "/api/v1/candidate-profile/review/confirm",
            json={"paths": ["/summary"]},
        )
        assert partial.status_code == 200
        assert partial.json()["review_status"] == "pending_candidate_review"
        assert partial.json()["source_profile"]["summary"]["confirmed"] is True
        assert partial.json()["source_profile"]["skills"][0]["confirmed"] is False

        complete = client.post(
            "/api/v1/candidate-profile/review/confirm",
            json={"paths": ["/skills/0"]},
        )
        assert complete.status_code == 200
        assert complete.json()["review_status"] == "confirmed"
        assert complete.json()["source_profile"]["_meta"]["review_status"] == "confirmed"
        assert complete.json()["unconfirmed_paths"] == []


def test_profile_import_validates_input_and_rejects_duplicate(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        assert client.post(
            "/api/v1/candidate-profile/import",
            json={"identity": {"full_name": "  "}},
        ).status_code == 422
        source = {"identity": {"full_name": "Candidate Example"}}
        assert client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        ).status_code == 201
        assert client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        ).status_code == 409


def test_existing_profile_database_is_migrated_without_data_loss(tmp_path) -> None:
    database_path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE candidate_profiles (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO candidate_profiles
                (id, profile_json, created_at, updated_at)
            VALUES (1, ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')
            """,
            (json.dumps({"full_name": "Candidate Example"}),),
        )

    with make_client(database_path) as client:
        response = client.get("/api/v1/candidate-profile")
        assert response.status_code == 200
        assert response.json()["profile"]["full_name"] == "Candidate Example"
        assert response.json()["review_status"] == "pending_candidate_review"
        assert response.json()["source_profile"] is None
        history = client.get("/api/v1/candidate-profile/history")
        assert history.status_code == 200
        assert [item["action"] for item in history.json()["items"]] == [
            "profile_migrated"
        ]


def test_candidate_provided_details_are_stored_separately(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        source = {
            "_meta": {"review_status": "pending_candidate_review"},
            "identity": {
                "full_name": "Candidate Example",
                "current_city": "Hosur",
                "current_state": "Tamil Nadu",
                "current_country": "India",
            },
            "summary": {
                "automation_experience_years": None,
                "confirmed": False,
            },
            "employment_history": [
                {
                    "company": "Example Co",
                    "title": "QA Engineer",
                    "achievements": [{"text": "Improved quality", "confirmed": False}],
                }
            ],
        }
        assert client.post(
            "/api/v1/candidate-profile/import",
            json=source,
        ).status_code == 201

        updated = client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={
                "automation_experience_years": "8 years",
                "current_location": "Hosur, Tamil Nadu, India",
                "preferred_locations": [
                    "Bengaluru, India",
                    "United Kingdom",
                    "Luxembourg",
                    "Germany",
                    "Europe",
                ],
                "notice_period": "Immediate",
                "target_compensation": {
                    "amount_lpa": 32,
                    "currency": "INR",
                    "period": "annual",
                },
                "relocation_destinations": [
                    "Bengaluru, India",
                    "United Kingdom",
                    "Luxembourg",
                    "Germany",
                    "Europe",
                ],
            },
        )
        assert updated.status_code == 200
        record = updated.json()
        assert record["candidate_confirmed_details"]["automation_experience_years"] == "8 years"
        assert record["candidate_confirmed_details"]["current_location"] == (
            "Hosur, Tamil Nadu, India"
        )
        assert record["candidate_confirmed_details"]["target_compensation"] == {
            "amount_lpa": 32.0,
            "currency": "INR",
            "period": "annual",
            "basis": "unspecified",
        }
        assert record["review_status"] == "pending_candidate_review"
        assert record["source_profile"]["summary"]["confirmed"] is False
        assert record["unconfirmed_paths"] == [
            "/summary",
            "/employment_history/0/achievements/0",
        ]


def test_candidate_details_require_an_existing_profile_and_valid_values(tmp_path) -> None:
    with make_client(tmp_path / "candidate.sqlite3") as client:
        assert client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={"notice_period": "Immediate"},
        ).status_code == 404
        assert client.post(
            "/api/v1/candidate-profile",
            json={"full_name": "Candidate Example"},
        ).status_code == 201
        assert client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={"target_compensation": {"amount_lpa": -1}},
        ).status_code == 422
        assert client.patch(
            "/api/v1/candidate-profile/candidate-details",
            json={"unrecognized": "value"},
        ).status_code == 422
