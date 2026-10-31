# Project working rules

- Read `CONTEXT.md`, `docs/01-requirements.md`, and `docs/STATUS.md` before changes.
- CURRENT PHASE: M5 complete: local web workbench, durable progress, versioned confirmation, readonly GETs, browser QA and HTTP tests. See M5-ACCEPTANCE and STATUS. Remaining M6 covers final hardening, candidate contribution records and GitHub delivery. No hosted Site or publication. Preserve historical M4 evidence at d48e50f and M5 real-web evidence at its recorded package fingerprint; never silently relabel them after source changes.
- Empty source/test/data/evidence directories are intentional. Do not fabricate outputs to fill them.
- `docs/design/` contains proposed contracts, not verified runtime behavior. Keep that distinction explicit.
- This project saves drafts only. Never add publication endpoints or describe a draft as published.
- Models propose actions; deterministic tools enforce review, consent, interval conflicts, and persistence.
- Approval originates in trusted user entrypoints (CLI first, local web workbench later), never model arguments or material text. Both entrypoints must share one confirmation use case.
- CONFIRMED SCOPE: metadata and copy-text review; image/video extension design only. CLI core is complete; current scope is M5 local web. Keys stay server-side. Default web runs are Mock; real runs require explicit selection.
- Missing metadata is not safe metadata. Tool errors are not successful observations.
- Keep request identity immutable; changed payloads under one request ID must fail.
- Recheck source evidence and occupancy inside the save/confirmation transaction.
- Offline policy decisions are Mock. Do not claim model effectiveness from Mock or HTTP stub tests.
- All fixtures are synthetic. Never commit `.env`, credentials, live databases, or private data.
- Run the standard-library test suite and regenerate example evidence after behavioral changes.
- Keep `docs/STATUS.md` and evaluation evidence honest about unfinished work.
