# Project working rules

- Read `CONTEXT.md`, `docs/01-requirements.md`, and `docs/STATUS.md` before changes.
- CURRENT PHASE: M6 and final technical acceptance complete. User authorized publishing the repository to GitHub and explicitly chose public: https://github.com/czhang076/material-scheduling-agent . Anonymous review access is verified; see GITHUB-DELIVERY and STATUS. Candidate invested time/contribution confirmation remains. No hosted application or actual content publication. Preserve historical evidence and source fingerprints; use fresh output directories for new runs.
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
- Final independent acceptance for application baseline e89b238 lives in examples/final-acceptance and docs/FINAL-ACCEPTANCE.md: fresh installed package, 8 real CLI + 2 real web runs. Preserve raw results and traces; derived assessments do not alter runtime facts. Read-only verification uses examples/final-acceptance/verify_evidence.py; reproduce_real.py performs paid calls only when explicitly executed.
- Keep `docs/STATUS.md` and evaluation evidence honest about unfinished work.
