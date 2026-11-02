# Prepared asset intake

The candidate supplied `candidate_profile.json` and the updated resume. They are stored locally in `candidate/` and excluded from Git because they contain personal information. A summary of earlier job-discovery research and preferences has been supplied and is recorded in [project requirements](../../docs/project-requirements.md); original actor research and test results have not yet been transferred. No candidate facts or detailed research findings have been fabricated.

The resume PDF and candidate JSON have been retained as supplied. The remaining source materials are:

- LinkedIn profile information
- AI agent development experience and project details
- Job discovery research
- Apify actor research and testing results
- Job-search queries and filtering strategies

The current profile API does not yet load these source files; it accepts validated profile JSON through its API. Asset ingestion and a review/confirmation flow remain Phase 4 work.

Review the contents for personal data and secrets. Candidate files are excluded from version control by `.gitignore`. The Candidate Profile Agent imports validated JSON through `POST /api/v1/candidate-profile/import`; imported claims remain pending until explicitly confirmed. The API does not parse the PDF yet. Its behavior and schema are documented in [the architecture guide](../../docs/architecture.md) and exposed at `/docs` when the service is running.
