# Project working rules

- Read `CONTEXT.md`, `docs/01-requirements.md`, and `docs/STATUS.md` before changes.
- CURRENT PHASE: M2 completed. Real SQLite/tools, source merge/conflicts, confirmation, idempotency, revalidation, faults, concurrency tests and manual evidence are implemented; see docs/M2-ACCEPTANCE.md. Do not start M3 Agent/CLI or web until the user advances the stage. Real model configuration remains deferred.
- Empty source/test/data/evidence directories are intentional. Do not fabricate outputs to fill them.
- `docs/design/` contains proposed contracts, not verified runtime behavior. Keep that distinction explicit.
- This project saves drafts only. Never add publication endpoints or describe a draft as published.
- Models propose actions; deterministic tools enforce review, consent, interval conflicts, and persistence.
- Approval originates in trusted user entrypoints (CLI first, local web workbench later), never model arguments or material text. Both entrypoints must share one confirmation use case.
- CONFIRMED SCOPE: metadata and copy-text review; image/video extension design only. Build the CLI core before a lightweight local web workbench. Current implementation scope is M2.
- Missing metadata is not safe metadata. Tool errors are not successful observations.
- Keep request identity immutable; changed payloads under one request ID must fail.
- Recheck source evidence and occupancy inside the save/confirmation transaction.
- Offline policy decisions are Mock. Do not claim model effectiveness from Mock or HTTP stub tests.
- All fixtures are synthetic. Never commit `.env`, credentials, live databases, or private data.
- Run the standard-library test suite and regenerate example evidence after behavioral changes.
- Keep `docs/STATUS.md` and evaluation evidence honest about unfinished work.
