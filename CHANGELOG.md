# Changelog

## 2026-10-20 — Local RAG Starter publication documentation

**WHAT:** Adopted the Local RAG Starter display name without changing Python imports or the distribution name. Added clone-to-first-answer documentation, complete platform-specific terminal steps, prerequisite installation, restart/backup guidance, an architecture walkthrough with component/sequence/database diagrams, and GitHub project links. Source archives now use local-rag-starter.zip. Standalone-guide document links resolve to the public documentation when downloaded separately. Prepared publication from the release allowlist with fresh Git history.

**WHY:** A reusable public template must explain installation and architecture without requiring knowledge of the original application. Original private history and user state must stay outside the public repository.

**WATCH FOR:** Keep setup generation separate from manual .env copying; preserve matching database passwords/volumes and Ollama endpoints across terminals. Do not publish ordinary workspace data or claim Windows/macOS end-to-end setup was manually verified by unit CI. Regenerate START-HERE.html after tutorial changes and review the allowlist before publishing.

## 2026-10-20 — Apple-inspired Streamlit workspace

**WHAT:** Redesigned Chat, Sources, and Settings with platform system typography, short page titles, a restrained translucent sidebar, full-width selected navigation, a blue accent, grouped white controls, readable status summaries, and a unified chat composer. Added immediate press feedback and explicit reduced-motion, reduced-transparency, increased-contrast, and keyboard-focus states. Refreshed fictional desktop/mobile screenshots and the standalone guide. Installed the requested upstream Apple design skill as `apple-design-emil` alongside the existing local skill.

**WHY:** The earlier editorial styling and default widget hierarchy did not feel like a cohesive application. The redesign applies familiar app navigation, deliberate grouping, and immediate feedback while keeping the Streamlit starter lightweight.

**WATCH FOR:** Preserve the native radio inputs when styling navigation; hide only the drawn circles. Keep Material icon fonts intact when applying the system text stack. Do not add transparency to every panel or introduce animation delays into real work. Never use ordinary workspace documents or conversations in public screenshots. The moved worktree and editable installation were repaired locally; future moves require updating both references and restarting the server.


## 2026-10-20 — New chat reliably switches conversations

**WHAT:** The New chat button queues its action before the conversation selector is instantiated, creates exactly one session, and selects it on the next render. Added a failing-then-passing regression test and made the disposable UI fixture clear sessions between cases.

**WHY:** The earlier button attempted to overwrite the selector's state after rendering it. Streamlit rejected the update, leaving the old conversation selected even when a new database session had been created.

**WATCH FOR:** Do not assign the conversation widget's session key after instantiating the selector. Keep the action request separate from the widget state, consume it once, and verify the new conversation has empty history.


## 2026-10-20 — Literal source labels and explicit capabilities

**WHAT:** Escaped untrusted source names in Markdown-enabled labels and rendered website addresses as literal text. Provider controls now read the implemented capability catalog directly rather than silently falling back to legacy interfaces.

**WHY:** A document title must not load a remote image or become an injected link. Broken capability discovery must be visible instead of presenting a misleading provider list.

**WATCH FOR:** Keep source text and model answers in literal text widgets, escape filenames used in formatted labels, and use only the declared adapter capabilities for provider choices.

## 2026-10-20 — Minimal reproducible runtime installation

**WHAT:** The default requirements file uses the complete lock as version constraints and installs only the base application. Development tools, Google packages, and documentation tooling install through the explicit development requirements or extras.

**WHY:** A local upload chatbot should not install account connectors and verification tools it does not use. One complete lock still pins the versions for every supported installation profile.

**WATCH FOR:** Keep runtime requirements as constraints plus the editable base project. Do not change them back to installing every extra from the lock. The development requirements deliberately request dev, drive, and docs extras for CI.

## 2026-10-20 — Readability cleanup

**WHAT:** Formatted Python source and tests consistently and removed unused legacy source-table helpers from the UI utility module. No pipeline behavior changed.

**WHY:** The original compact statements made the ingestion, transaction, and error paths harder for developers to review. Old table adapters no longer served the three-page workspace.

**WATCH FOR:** Keep this refactor separate from behavioral changes. The full 117-test database-backed suite passes before and after the cleanup.

## 2026-10-20 — Free local RAG starter

**WHAT:** Added a fully local default using uploaded documents, Ollama, and local PostgreSQL/pgvector; portable setup/init/check/sync/cleanup commands; typed configuration; immutable upload originals and transactional index publication; optional Drive and website connectors; source-aware rebuild/recovery; three-page workspace; reproducible dependencies, CI, contribution/security guides, fictional portfolio materials, and an allowlisted release archive. The legacy public widget, Mac-only launchers, duplicated test configuration, and stale evaluation/performance reports are excluded from this release. Replaced deprecated LangChain document loaders with direct format extraction while retaining the shared text splitter.

**WHY:** The previous application required Google Drive and Supabase for ordinary use, mixed setup and UI concerns, and carried portfolio-specific functionality. Developers need a clone-to-first-answer path without paid APIs or proprietary credentials. Existing transactional and citation safeguards remain valuable and are preserved.

**WATCH FOR:** Do not load .env.example at runtime, reuse the private library's configuration, reconcile across source kinds, publish an original-file pointer separately from passages, or remove blobs referenced by retained generations. Environment overrides must match an activated embedding/chunk configuration. Keep all writer operations under the dedicated advisory-lock connection and all destructive checks in disposable loopback *_test databases. The starter has no public authentication or cloud spending cap.

## 2026-10-20 — Guard embedding identity and independent remote sync

**WHAT:** Retrieval verifies the complete embedding/chunk pipeline identity inside its consistent database snapshot, in addition to vector dimensions. Website refresh runs without a Drive folder and continues when Drive sign-in fails. Preview and indexing share one splitter. Rebuild confirmation and answer retry controls survive Streamlit reruns. Failed activity writes emit sanitized operator warnings and cannot relabel a saved answer as failed; rebuild/recovery notices refresh the displayed active settings.

**WHY:** Different models can produce equal-length vectors with incompatible meanings. Google configuration must not gate an independent website connector. Duplicated splitters and ephemeral form controls could misrepresent behavior or prevent a requested action.

**WATCH FOR:** Checking settings only before query embedding leaves a race with index activation; retain the in-snapshot guard. Do not restore Google-only worker readiness or a confirmation checkbox trapped inside a disabled-submit form.

The original workspace preserves private-app history. This changelog describes the starter; the public template begins with fresh Git history.
