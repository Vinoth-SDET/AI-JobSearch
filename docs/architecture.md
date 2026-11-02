# Architecture and API

## Backend

The service is a Python 3.11+ FastAPI application. Pydantic schemas validate API input, agent modules own application behavior, and a SQLite repository persists data. The HTTP API is versioned under `/api/v1`. The SQLite database keeps local development self-contained; storage and agent boundaries allow later components to be added without coupling them to HTTP handlers.

```text
src/ai_job_search/
  agents/
    candidate_profile/    Candidate profile agent
    job_discovery/        Apify execution and discovery persistence
  api/routes/             Versioned HTTP routes
  schemas/                Validated request and response models
  database.py             Candidate profile persistence
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

## Phase 5: Job Discovery Agent (in progress)

The discovery agent reads job-title, target-location, and remote-eligibility preferences through the Candidate Profile Agent. It creates a bounded preview for the reported LinkedIn, Indeed, and Google Search Actors; live execution is separately gated. The Actor IDs and input fields below were checked against the public Apify Store metadata on 2026-11-02. No Actors have been run as part of this acceptance work.

### Discovery API

| Method | Path | Behavior |
|---|---|---|
| `GET` | `/api/v1/job-discovery/preferences` | Read discovery preferences derived from the candidate profile |
| `POST` | `/api/v1/job-discovery/preview` | Preview Actor inputs and per-run charge allocations; no external call |
| `POST` | `/api/v1/job-discovery/runs` | Run requested Actors only when live execution is enabled and `confirm_live_run` is true |
| `GET` | `/api/v1/job-discovery/runs` | Read persisted Actor run summaries |
| `GET` | `/api/v1/jobs` | List persisted normalized job results, with optional source and pagination |
| `POST` | `/api/v1/jobs/{id}/verify` | Independently check the public HTTPS posting URL and, when present, its application URL |

Each live request must state a budget. It is rejected when it exceeds `JOB_DISCOVERY_MAX_BUDGET_USD`; the request budget is split across planned Actor runs and passed to Apify as `max_total_charge_usd`. Result/query limits are also sent in the Actor-specific inputs. LinkedIn title/location combinations and per-combination `rows` are bounded by the requested source result limit; Indeed rows and Google queries are split across planned runs, with one Google page per query. When the result limit is too small to cover every preference, the preview shows the selected Actor inputs. Live runs are disabled by default and all execution tests use a mocked executor. Candidate names, contact details, profile contents, and resume claims are not included in Actor inputs.

### Actor schema review

| Actor | Public input fields used | Output handling | Current listed pricing |
|---|---|---|---|
| [LinkedIn Jobs Scraper](https://apify.com/bebity/linkedin-jobs-scraper) (`bebity/linkedin-jobs-scraper`, community) | `titles`, `locations`, `rows`; each title/location pair is a search. The SDK item cap bounds total returned dataset items. | Maps documented/inferred fields including `title`, `companyName`, `location`, `jobUrl`, `applyUrl`, `description`, salary fields and work-type fields. | Per-event Actor start plus per-job result; company and hiring-contact enrichment costs extra and is not requested. |
| [Indeed jobs scraper](https://apify.com/borderline/indeed-scraper) (`borderline/indeed-scraper`, community) | `country`, `query`, `location`, `maxRows`; each location is a separate bounded run. The Actor's country enum uses `uk` for the United Kingdom; the planner translates the profile's `gb` code. | Handles `location` and `salary` objects, `jobUrl`, `applyUrl`, `datePublished`, `expired`, `isRemote` and `jobType`. | Listed at $0.005 per job result. Per-run result count is capped by the allocated request budget at this listed rate. |
| [Google Search Results Scraper](https://apify.com/apify/google-search-scraper) (`apify/google-search-scraper`, Apify) | Newline-delimited `queries`, `maxPagesPerQuery=1`, and country-specific `countryCode` where available. Its enum accepts `gb`. | Expands each dataset item's `organicResults`; reads result title, URL, snippet/date, and nested `personalInfo` when available. | Per successfully scraped search-results page; optional AI, ads, lead-enrichment and website-content add-ons are explicitly disabled. |

This review confirms the documented input names and current public pricing metadata, not that an Actor's production behavior is compliant, stable, or available. The LinkedIn and Indeed publishers are third parties. Output schemas are inferred from recent successful runs in the Store rather than a versioned contract; actual datasets, pricing, and access must be rechecked before enabling live runs. The Google query builder keeps each query within the Actor's documented 32-word limit.

The Apify SDK's `max_total_charge_usd` caps pay-per-event Actor charges. Its `max_items` caps returned results and pay-per-result charges, but does not necessarily cap Actor work. Actor-specific inputs (`rows`, `maxRows`, and `maxPagesPerQuery`) bound requested work. The Indeed item cap is additionally limited by its currently listed $0.005/result rate and each run's budget allocation; recheck the price before live use. Apify pricing tiers and event rates can change. Google optional paid add-ons are off, and each live request still requires explicit confirmation, a configured token, enablement, and an overall budget no greater than the application cap.

The fixture set under `tests/fixtures/job_discovery/` captures synthetic examples of the current inferred Actor output structures. Acceptance tests assert both source-specific field normalization and a mocked profile-to-search-to-persistence flow; they do not prove live Actor behavior.

Discovery stores the source actor and run ID, retrieval time, normalized fields, posting/application URLs, and evidence. URL tracking parameters are normalized for duplicate checks; normalized title/company/location is a fallback identity. One canonical posting row is kept per duplicate group, with `observed_sources` and `observed_posting_urls` preserving cross-source provenance. Run summaries count duplicate observations separately from newly saved postings. Postings with an evidenced expiration date in the past are excluded; unknown expiration dates are not treated as expired. `location_match` distinguishes preferred city, preferred country, European-region match, remote, outside-preference, and unknown. Remote eligibility is `eligible` only when the listing explicitly indicates India eligibility, `restricted` for recognized country-only restrictions, `not_remote` for explicitly non-remote work, and otherwise `unknown`. Outside-preference results are retained with their classification rather than silently discarded. Location and remote classification are evidence-based labels, not visa or legal eligibility decisions.

Every new record starts as `status=discovered`. The verification endpoint records `verification_pending` while checking URLs, then restores `status=discovered`; URL outcomes are kept independently in `posting_url_status` and `application_url_status` (`reachable`, `expired`, `unavailable`, or pending/not provided). A successful HTTPS response means only that the URL is reachable. A 410 response marks the URL expired, not the vacancy closed. `vacancy_assessment` and `employer_authenticity_assessment` remain `not_assessed`; no implemented check establishes vacancy availability or employer authenticity. The employer application URL is checked and reported separately. Verification only follows a limited number of HTTPS redirects to public IP addresses on port 443; it sends a HEAD request and uses a one-byte ranged GET only when HEAD is unsupported. No page content is downloaded. Visa sponsorship, authentication-gated postings, legal eligibility, and application success are not verified.

Actor run failures and timeouts are sanitized and persisted as run summaries, including attempts where Apify did not return a run ID. Empty datasets are successful runs with zero saved jobs. Actor run results can fail if a third-party Actor schema or behavior changes; failure details avoid echoing Actor input or candidate data.

## Storage and configuration

SQLite stores one normalized JSON profile and, for imported profiles, the original source JSON and confirmation state, plus versioned profile history, constrained to a single candidate. Discovery uses separate `job_discovery_runs` and `job_postings` tables in the same database. `DATABASE_PATH` selects the SQLite file; by default it is `data/ai-job-search.sqlite3`. Database files, local candidate source assets, and local environment files are excluded from Git. Do not commit real candidate data or secrets. The API has no authentication and is intended for local development only. Successful API requests do not log candidate field values.

## Future agent boundaries

Matching, application-material generation, auto-apply, application tracking, and orchestration remain planned; no runtime behavior for those phases is implemented.

See [project requirements](project-requirements.md) for user-provided discovery scope, workflow safeguards, and open decisions.
