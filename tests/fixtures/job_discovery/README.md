# Job discovery fixtures

These synthetic records mirror fields in the public Actor output schemas checked
on 2026-11-02. They use fictional employers and reserved `.example` URLs; they
are not scraped listings and must not be used to infer current vacancies.

- `linkedin_job.json`: inferred LinkedIn Jobs Scraper record fields.
- `indeed_job.json`: inferred Indeed scraper fields, including structured
  `location` and `salary` objects.
- `google_search_results.json`: Google Search Scraper's grouped
  `organicResults`, including its nested `personalInfo` structure.

The Store output schemas are inferred from recent successful runs, not
versioned contracts. Update these fixtures only when the corresponding public
Actor output schema or representative sanitized run evidence changes.
