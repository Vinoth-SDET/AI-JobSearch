# Project requirements and decisions

This document records the user's supplied requirements summary. Candidate JSON and PDF resume are retained locally but excluded from Git. Other reported assets and previous research are not treated as imported source data until their files are provided. Recommendations are labeled as proposed until explicitly confirmed.

## Candidate profile

The candidate supplied the updated resume PDF and `candidate_profile.json`; both are retained locally under `assets/prepared/candidate/` and excluded from Git. The JSON is based on the PDF and records `pending_candidate_review`. Its assertions are not treated as candidate-confirmed simply because they were imported.

Other information reported as available but not yet supplied:

- LinkedIn headline, About section, employment descriptions, and skills
- AI agent development experience and project details
- Enterprise API Automation Suite details

### Candidate-provided details

- Automation experience duration is candidate-provided as **8 years**; the source JSON's overall 12+ years total remains a separate claim.
- Coforge employment chronology (the supplied JSON lists June 2022 to present; candidate confirmation is still pending)
- Current residence is **Hosur, Tamil Nadu, India**; **Bengaluru** is a preferred work and relocation location, not the current residence.
- Candidate-provided notice period: **Immediate**.
- Candidate-provided compensation target: **32 LPA (INR, annual)**. Fixed/total CTC basis was not specified.
- Candidate-provided preferred locations and relocation destinations: **Bengaluru, United Kingdom, Luxembourg, Germany, and Europe**.

- Automation experience: **8 years** (candidate-confirmed; overall experience remains the separate 12+ years stated in the source profile).
- Current residence: **Hosur, Tamil Nadu, India**.
- Preferred work location: **Bengaluru, India**.
- Notice period: **Immediate**.
- Target compensation: **32 LPA, INR annually**. Fixed versus total compensation basis is unspecified.
- Preferred locations/relocation destinations: **Bengaluru, United Kingdom, Luxembourg, Germany, and Europe**.

These updates are saved locally in the candidate profile's confirmed-details overlay and kept separate from the imported resume-derived source.

### Still unconfirmed or excluded

The candidate said to ignore employment-gap explanations, resume metrics, and whether the AI-agent projects were independent. Leave these source claims unconfirmed and do not use them in application materials. Coforge chronology also remains pending confirmation. The source JSON's other `confirmed` flags remain false until explicitly confirmed through the review API. Null values remain unknown. The PDF is retained as a source but is not currently parsed by the application.

## Job discovery requirements

### Search scope reported by the user

- Primary location: India; Indian cities include Bengaluru and Hyderabad
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

The reported strategy recommends LinkedIn as primary, Indeed as secondary, and Google Search for ATS discovery. These are research-stage recommendations only, not production integrations or endorsement of any actor's current access/compliance behavior. Import the original research, test outputs, actor input/output examples, and applicable site terms before implementing discovery.

### Discovery behavior required in a future phase

- Detect duplicate and reposted vacancies
- Verify and retain the original employer application URL
- Exclude expired vacancies
- Distinguish India-eligible remote jobs from country-restricted remote roles
- Extract salary and employment type when available
- Record source actor, execution ID, and retrieval timestamp
- Keep visa-sponsorship verification separate from vacancy discovery

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
- Apify API and Python SDK for future discovery integration
- Configurable Claude/OpenAI provider for future AI features; provider not selected
- Playwright for future browser automation
- Email notifications; provider and configuration not selected
- Retain application history and generated documents until manually deleted
- UK and Luxembourg remain in search scope
- Local development first; secure authentication is required before any deployment

Never put API tokens, passwords, browser cookies, or other credentials in source control or prepared assets. Configure integrations through local environment variables or a suitable secret manager.

## Source material still needed

The summary is not a replacement for the source assets. Provide or copy into `assets/prepared/` the resume, profile JSON, LinkedIn content, agent project details, Enterprise API Automation Suite details, original Apify research/test results, search queries, filters, and workflow requirements. See [prepared asset intake](../assets/prepared/README.md).
