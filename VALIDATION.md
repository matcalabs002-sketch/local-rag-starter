# Local RAG Starter — validation

Date: 2026-10-20. All database verification uses new local storage and fictional documents. No production database or private Drive corpus is used.

## Completed evidence

- The refactor's full suite passes with disposable PostgreSQL 17 and pgvector, including the original transaction/retrieval cases and new upload, configuration, source isolation, rollback, pipeline identity, and lost-lock checks. The verified full suite contains 123 passing tests with none skipped.
- Full-project Ruff and dependency consistency checks pass. The resolved dependency lock is audited separately from application tests.
- Real Ollama (`qwen3:4b`, `nomic-embed-text:v1.5`, 768 dimensions) passes nine binary answer cases plus conversation isolation: known onboarding/project/refund facts, refund follow-up, missing information, user instruction override, malicious source instructions, source update, and source deletion. Inspectable fictional answers are recorded in docs/evaluation.json.
- Chromium completes a real local upload and a cited chatbot answer. Desktop at 1440 px and mobile viewport at 390 px have no document-level horizontal overflow. Screenshots contain only the fictional handbook.
- The original five-commit Git history passed Gitleaks. Current source/archive and final commit history are checked as part of final packaging.

## Verification boundaries

- Optional Google Drive, website-network failure paths, and paid-provider adapters have automated contract/failure tests; this refactor does not claim new live Google, Supabase, OpenAI, or Anthropic verification.
- Local model checks measure a small fixed fictional corpus. Valid citations do not prove factual entailment or comprehensive prompt-injection resistance.
- Hosted CI now exercises Linux database verification and Windows/macOS unit tests; publication outcomes and Windows corrections are recorded below. Complete interactive Linux/Windows first runs, physical mobile Safari, Firefox, and public deployment remain unverified.
- PostgreSQL is the only implemented vector store. There is no public authentication, multi-user deployment, hosted spending enforcement, OCR, hybrid retrieval, or reranking.
- Performance depends on hardware, model warmth, source size, and network conditions; recorded local timings are observations, not service guarantees.

## Final release verification

- **123 tests pass**, with disposable PostgreSQL/pgvector and no skipped cases.
- Full-project Ruff, Python compilation, `pip check`, and dependency auditing of the complete pinned lock pass; no known dependency vulnerabilities were reported.
- Gitleaks scans of the complete original Git history and the source ZIP report no secrets. The ZIP contains no `.env`, `.private`, virtual environment, log, original upload, model cache, or Git metadata.
- A fresh unpacked ZIP was installed into a new virtual environment, configured with a generated password and an isolated database on an alternate loopback port, initialized, checked, and used for an actual sample upload and cited answer. No cloud account configuration was supplied; the base runtime installation excludes Google and development packages. Temporary acceptance files, database volume, and services were removed afterward.
- Browser checks cover local upload, a cited answer, a real rebuild to 500/50 chunk settings, and recovery to the retained index. Chat, Sources, and Settings show no horizontal overflow at 390 px; Chromium reports no console errors. Desktop screenshot width is 1440 px.
- `build_guide.py` regenerates the standalone guide from current tutorial content and fictional screenshots.

The ordinary local preview is intentionally left available separately from the disposable test database. Its library is private and may contain user documents. Public screenshots and acceptance checks use separate fictional-only storage. At that verification stage, no repository publication or public deployment had occurred.

## Apple-inspired redesign verification

- Full disposable-database suite: **123 passed**, including HTML escaping/status presentation and the failing-then-passing New chat regression.
- The native radio group remains keyboard-navigable across Chat, Sources, and Settings.
- Chromium verifies all three destinations without horizontal overflow at **320 px, 390 px, and 1440 px**. Mobile navigation is checked after its native close transition settles.
- A fresh conversation in a separate fictional demo library answers the refund-review question from actual Ollama inference and exposes its citation. No ordinary workspace data appears in release screenshots.
- Reduced-motion emulation yields a zero-second button transition. Reduced-transparency/increased-contrast emulation removes sidebar blur. Physical device accessibility checks remain outstanding.
- The preview at port 8504 is restarted against the existing workspace configuration. RAG ingestion, model prompts, database schema, index safeguards, and provider selection are unchanged.

## GitHub publication preparation — 2026-10-20

- The public display name is **Local RAG Starter**; Python imports and distribution identity are unchanged. Publication uses a separate allowlisted checkout and fresh history, preserving the original repositories.
- **123 tests pass**, full-project Ruff and `pip check` pass, and local documentation/image links resolve. The generated guide embeds its image, links to GitHub documents when downloaded alone, and displays all twelve tutorial steps without desktop/mobile horizontal overflow.
- A fresh Python 3.12 environment installs the pinned base runtime from cached wheels during a host network outage, with no Google/development packages. A new Compose project on loopback port 55433 uses a generated password and separate volume. Setup, initialization, four readiness checks, actual browser upload, a cited ORCHID-742 answer, and the missing-phone-number response pass. This offline cache-assisted installation does not claim a new online download test.
- The fresh checkout passes all nine real-Ollama binary cases and conversation isolation using its separate disposable `publication_test` database. The ordinary workspace and its private documents/conversations are not used.
- A Gitleaks source-only allowlist scan reports no secrets. The scan excludes generated private settings and installed packages; final Git history is scanned before push.
- After network recovery, all **five Mermaid diagrams parse and render**, the dependency advisory refresh reports **no known vulnerabilities**, and dependency consistency passes. Browser checks of Chat, Sources, and Settings at 1440/390 px pass without horizontal overflow or page errors; refreshed screenshots use the isolated fictional library. The public MIT template is published at [matcalabs002-sketch/local-rag-starter](https://github.com/matcalabs002-sketch/local-rag-starter); a fresh GitHub clone contains no private state. Public README, screenshot, and architecture pages load in Chromium.

- The documented container-based database dump and copy commands were exercised against the fictional acceptance library. Restoring into a new disposable database preserved its document and passages; the ordinary library was not touched.

- The first hosted CI run passed Linux verification, macOS unit tests, and Gitleaks. Windows exposed private-writer newline translation plus oversized test IDs and native-path assumptions. These are corrected with an additional UTF-8/line-ending regression; the follow-up hosted result is recorded separately.

## Published template and hosted verification

Repository: [Local RAG Starter](https://github.com/matcalabs002-sketch/local-rag-starter), public, MIT, `main`, template enabled. Public history starts with the reviewed starter; original private-app commits, configuration, originals, and conversations were not pushed.

The Windows fixes pass **124 local database-backed tests**. Hosted evidence for the corrected source is recorded on the [workflow page](https://github.com/matcalabs002-sketch/local-rag-starter/actions/workflows/ci.yml), which reports the latest branch result. Linux runs the complete PostgreSQL/pgvector suite, lint, dependency consistency/auditing, and guide reproducibility. Windows/macOS run unit tests; the separate secret job scans public history. Read individual job conclusions rather than inferring an end-to-end OS installation from unit checks.

The isolated acceptance container, volume, settings, and fictional runtime data were removed after verification. The existing local workspace remains separate and available. The standalone guide and allowlisted source ZIP match the published documentation.
