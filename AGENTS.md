# Project working rules

- Read `CONTEXT.md`, `docs/01-requirements.md`, and `docs/STATUS.md` before changes.
- CURRENT PHASE: M3 completed: bounded runtime, observation-driven offline Mock, CLI, durable Trace, 156 tests and 14 offline cases/16 actual runs. Read docs/M3-ACCEPTANCE.md. Advance further only when the user continues; real provider configuration is still deferred. Do not claim real ReAct verification from these Mock runs.
- Empty source/test/data/evidence directories are intentional. Do not fabricate outputs to fill them.
- `docs/design/` contains proposed contracts, not verified runtime behavior. Keep that distinction explicit.
- This project saves drafts only. Never add publication endpoints or describe a draft as published.
- Models propose actions; deterministic tools enforce review, consent, interval conflicts, and persistence.
- Approval originates in trusted user entrypoints (CLI first, local web workbench later), never model arguments or material text. Both entrypoints must share one confirmation use case.
- CONFIRMED SCOPE: metadata and copy-text review; image/video extension design only. Build the CLI core before a lightweight local web workbench. Current implementation scope is M3.
- Missing metadata is not safe metadata. Tool errors are not successful observations.
- Keep request identity immutable; changed payloads under one request ID must fail.
- Recheck source evidence and occupancy inside the save/confirmation transaction.
- Offline policy decisions are Mock. Do not claim model effectiveness from Mock or HTTP stub tests.
- All fixtures are synthetic. Never commit `.env`, credentials, live databases, or private data.
- Run the standard-library test suite and regenerate example evidence after behavioral changes.
- Keep `docs/STATUS.md` and evaluation evidence honest about unfinished work.
