# Project requirements and decisions

This document records the user's supplied requirements summary. Candidate JSON and PDF resume are retained locally but excluded from Git. Other reported assets and previous research are not treated as imported source data until their files are provided. Recommendations are labeled as proposed until explicitly confirmed.

## Candidate profile

The candidate supplied the updated resume PDF and `candidate_profile.json`; both are retained locally under `assets/prepared/candidate/` and excluded from Git. The JSON is based on the PDF and records `pending_candidate_review`. Its assertions are not treated as candidate-confirmed simply because they were imported.

Other information reported as available but not yet supplied:

- LinkedIn headline, About section, employment descriptions, and skills
- AI agent development experience and project details
- Enterprise API Automation Suite details

### Candidate-provided details

- Automation experience duration: **8 years**; the source profile's 12+ years is overall experience.
- Current residence: **Hosur, Tamil Nadu, India**; preferred work/relocation location: **Bengaluru, India**.
- Notice period: **Immediate**.
- Target compensation: **32 LPA, INR annually**; fixed vs. total compensation basis is unspecified.
- Preferred locations/relocation destinations: **Bengaluru, United Kingdom, Luxembourg, Germany, and Europe**.

These updates are saved locally in the candidate profile's confirmed-details overlay and kept separate from the imported resume-derived source.

### Still unconfirmed or excluded

The candidate said to ignore employment-gap explanations, resume metrics, and whether the AI-agent projects were independent. Leave these source claims unconfirmed and do not use them in application materials. Coforge chronology also remains pending confirmation. The source JSON's other `confirmed` flags remain false until explicitly confirmed through the review API. Null values remain unknown. The PDF is retained as a source but is not currently parsed by the application.

## Job discovery requirements

### Search scope reported by the user

- Primary location: India; Bengaluru preferred; other cities in the source profile include Pune, Hyderabad, and Chennai
- International locations: United Kingdom, Luxembourg, Germany, and broader Europe
- Remote work: India-remote roles; verify whether remote vacancies accept candidates based in India
- Primary roles: Senior QA Automation Engineer and Senior SDET
- Leadership roles: QA Automation Lead and Test Automation Lead
- AI-related roles: AI Quality Engineer, AI Test Engineer, and AI Automation Engineer
- Level: Senior / Lead
- Core technologies: Selenium, Java, TestNG, REST Assured, and API testing
- Developing technologies: Playwright and TypeScript

### Reported Apify research (provisional; original test evidence pending)

| Source or purpose | Actor | Reported status |
|---|---|---|
| LinkedIn | `bebity/linkedin-jobs-scraper` | Tested |
| Indeed | `borderline/indeed-scraper` | Tested |
| Indeed | `kaix/indeed-scraper` | Tested; insufficient evidence |
| Google Search / ATS discovery | `apify/google-search-scraper` | Tested |
| LinkedIn alternative | `valig` | Researched |
| LinkedIn alternative | `curious_coder` | Researched |

The reported strategy recommends LinkedIn as primary, Indeed as secondary, and Google Search for ATS discovery. These are research-stage recommendations only, not production integrations or endorsement of any actor's current access/compliance behavior. Import the original research, test outputs, Actor input/output examples, and applicable site terms before enabling production Actor integrations.

Phase 5 now contains previewable, mocked discovery execution and persistence based on these Actor IDs. Their documented input names and current public pricing metadata were checked on 2026-11-02, but no live Actor run or output-dataset check was performed; output mappings remain inferred and community Actor behavior can change. The platform implements independent HTTPS URL reachability checks for posting and application URLs, but does not confirm vacancy validity, employer ownership, work authorization, or sponsorship. Live execution remains disabled by default; see [architecture and API](architecture.md#phase-5-job-discovery-agent-in-progress).

### Discovery behavior and limitations

- Duplicate and reposted observations are retained with a reference to the first record; matching uses normalized URLs and title/company/location.
- Original posting and application URLs are retained and can be checked for public HTTPS reachability; this is not proof of an active vacancy or employer ownership.
- Expired listings with explicit actor evidence or past expiration dates are excluded from saved results.
- Remote listings are labeled eligible only when India eligibility is explicit, restricted for recognized country-only restrictions, otherwise unknown; this heuristic does not determine legal work eligibility.
- Salary and employment type are extracted when present in Actor output.
- Source Actor, execution ID when returned, and retrieval timestamp are recorded.
- Visa-sponsorship verification is not implemented and remains separate from discovery.

## Application workflow

The following is the user's supplied recommended baseline, pending explicit confirmation:

| Activity | Proposed handling |
|---|---|
| Find jobs, extract descriptions, calculate match scores, and track applications | Automated |
| Verify postings | Automated, retaining evidence |
| Analyze descriptions | AI-assisted |
| Tailor resume, draft cover letter, and prepare application answers | AI-generated drafts for each selected vacancy |
| Fill forms | Browser automation |
| Legal declarations and final submission | Require candidate confirmation; final submission always requires approval |
| Application status updates | Automated where supported |

Generated application materials must remain drafts until reviewed. The system must not invent candidate experience, metrics, eligibility, or legal answers.

## Platform decisions

Proposed defaults from the supplied summary; not yet confirmed:

- Single candidate/user initially
- Local development in VS Code
- Python and FastAPI backend
- SQLite initially; consider PostgreSQL if needed later
- Apify API and Python SDK for discovery integration
- Configurable Claude/OpenAI provider for future AI features; provider not selected
- Playwright for future browser automation
- Email notifications; provider and configuration not selected
- Retain application history and generated documents until manually deleted
- UK and Luxembourg remain in search scope
- Local development first; secure authentication is required before any deployment

Never put API tokens, passwords, browser cookies, or other credentials in source control or prepared assets. Configure integrations through local environment variables or a suitable secret manager.

## Source material still needed

The summary is not a replacement for the source assets. Provide or copy into `assets/prepared/` the resume, profile JSON, LinkedIn content, agent project details, Enterprise API Automation Suite details, original Apify research/test results, search queries, filters, and workflow requirements. See [prepared asset intake](../assets/prepared/README.md).
