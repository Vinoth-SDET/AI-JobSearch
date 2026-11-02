# Architecture and API

## Backend

The service is a Python 3.11+ FastAPI application. Pydantic schemas validate API input, agent modules own application behavior, and a SQLite repository persists data. The HTTP API is versioned under `/api/v1`. The SQLite database keeps local development self-contained; storage and agent boundaries allow later components to be added without coupling them to HTTP handlers.

```text
src/ai_job_search/
  agents/                 Agent implementations and future placeholders
  api/                    Versioned HTTP routes
  schemas/                Validated request and response models
  database.py             SQLite persistence
  main.py                 Application factory and lifecycle
tests/
assets/prepared/          Research and candidate materials, when supplied
docs/
```

## Phase 4: Candidate Profile Agent

The implemented API validates, imports, creates, reads, replaces, deletes, and selectively confirms one candidate profile. The JSON importer retains the source record (including pending-confirmation flags) and maps supported fields into the normalized profile. Confirmation is explicit and claim-by-claim. The agent does not infer missing resume details, call an LLM, access LinkedIn, or contact job sites.

### Profile API

Base path: `/api/v1/candidate-profile`

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/v1/candidate-profile` | Create the profile; returns `409` if one already exists |
| `POST` | `/api/v1/candidate-profile/import` | Validate and import the structured candidate profile JSON; starts in pending review |
| `GET` | `/api/v1/candidate-profile` | Read the profile; returns `404` if none exists |
| `PUT` | `/api/v1/candidate-profile` | Replace the complete profile; returns `404` if none exists |
| `DELETE` | `/api/v1/candidate-profile` | Delete the profile; returns `404` if none exists |
| `POST` | `/api/v1/candidate-profile/review/confirm` | Confirm selected pending claims using JSON Pointer paths |
| `PATCH` | `/api/v1/candidate-profile/candidate-details` | Save candidate-provided details separately from imported, unconfirmed source claims |
| `GET` | `/api/v1/candidate-profile/history` | Read versioned profile snapshots and review/detail changes |

Create and replace request bodies use the `CandidateProfile` schema: `full_name` is required; contact details, location, headline, summary, skills, work experience, education, certifications, and links are optional. Unknown fields and malformed email/HTTP(S) URLs are rejected with `422`.

The import endpoint accepts the structured profile JSON format with an `identity.full_name`. It preserves the original source object and its `confirmed` flags alongside a normalized profile. Imports and edits begin in `pending_candidate_review`; the response lists unconfirmed claim paths. To confirm claims, send paths identifying the containing claim object (for example, `/skills/0` or `/employment_history/0/achievements/0`) to the review endpoint. Invalid batches are rejected atomically. The profile review status becomes `confirmed` only after all explicitly flagged claims are confirmed. Values marked `null` in the source remain unknown; confirmation does not fill them in.

Full-profile replacement with `PUT` is rejected with `409` while an imported source has unconfirmed claims. Confirm each pending source claim before replacing the normalized profile; candidate-provided updates use the separate `PATCH` endpoint and do not clear pending source claims.

The candidate-details endpoint records direct candidate-provided updates separately from the original imported source; this preserves the original resume-derived values and avoids automatically confirming unrelated claims. It currently records automation experience, current location, preferred locations, notice period, target compensation, and relocation destinations. For LPA compensation, the amount is annual in INR; compensation basis (for example, fixed or total CTC) remains unspecified unless provided. See the OpenAPI schema at `/docs` for exact field definitions. Successful writes return the profile, source (if imported), explicitly supplied candidate details, review status, outstanding claim paths, and UTC creation/update timestamps.

The history endpoint stores and returns versioned snapshots for profile creation/import, candidate detail changes, claim confirmations, and profile replacement. Initial profiles found during database migration receive a baseline history version. History snapshots include personal data and are available only on the local, unauthenticated development API; deleting the profile also deletes its history.

## Storage and configuration

SQLite stores one normalized JSON profile and, for imported profiles, the original source JSON and confirmation state, plus versioned profile history, constrained to a single candidate. `DATABASE_PATH` selects the SQLite file; by default it is `data/ai-job-search.sqlite3`. Database files, local candidate source assets, and local environment files are excluded from Git. Do not commit real candidate data or secrets. The API has no authentication and is intended for local development only. Successful API requests do not log candidate field values.

## Future agent boundaries

Folders for job discovery, matching, application-material generation, auto-apply, and orchestration are planning placeholders only. They contain no runtime behavior; their implementation scope and phase assignments remain to be defined.

See [project requirements](project-requirements.md) for user-provided discovery scope, workflow safeguards, and open decisions.
