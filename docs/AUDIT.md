# Audit: private library to developer starter

Audit date: 2026-10-20. Scope: the Python repository, its five existing commits, and the surrounding n8n deliverables. Private credential values were not printed or copied into the starter worktree.

## Baseline

The earlier app used Streamlit, Ollama, Google Drive OAuth, Supabase/PostgreSQL, pgvector, LangChain document loaders, and a recursive text splitter. It also included a separate ASGI portfolio widget and theme editor. Its 99-test suite produced 90 passes and nine skipped database cases; whole-project Ruff passed. The repository was clean and unpublished.

The surrounding n8n workflows are independent, inactive deliverables. Their unpacked distribution copies duplicate the root workflow, SQL, setup, validation, and test files byte-for-byte. They are not dependencies of the Python application and are not included in this starter.

## Valuable functionality preserved

Transactional document replacement; complete Drive snapshots before deletion; bounded website crawling; source/version checks; dedicated connection-level writer locking; pooled reads; pending/active/previous index generations; structured provider adapters; citation validation; persistent isolated conversations; and current-evidence revision checks.

## Findings and disposition

| Finding | Impact | Change |
| --- | --- | --- |
| Drive and Supabase required for ordinary setup | Prevented an account-free local first run | Local uploads and local PostgreSQL are the default |
| Google sign-in gated the remote worker | Websites could not refresh independently | Optional Drive and website refresh run independently |
| `.env.example` loaded at runtime | Documentation placeholders could become effective configuration | Runtime reads environment, `.env`, then code defaults |
| Ollama endpoint and operational limits scattered | Customization required unrelated edits | Centralized typed settings and endpoint-aware clients |
| Vector dimensions checked without model identity | Equal-size incompatible models could be searched together | Pipeline identity checked in the retrieval snapshot |
| 763-line entry point mixed rendering/setup/pipeline controls | Made changes difficult to review and extend | Thin entry point and focused page modules |
| Duplicate chunk-preview implementations | Preview could disagree with ingestion | One shared extraction/splitting implementation |
| Deprecated community loader bundle | Unnecessary dependency surface | Direct format libraries; retained the splitter |
| Mac-only process management and setup | Blocked a portable developer path | Standard virtualenv/Streamlit commands and portable Python CLI |
| Six destinations plus widget editor | Diluted the core starter | Chat, Sources, Settings; activity nested in Sources; widget deferred |
| Duplicate pytest configuration and narrow CI lint | Configuration could diverge and core code escape lint | Canonical pyproject configuration and full-project CI |
| Old screenshots/evaluation/performance materials | Could imply outdated product state or verification | Replaced with fictional current UI and explicit validation limits |
| Ignored private configuration and OAuth state exist in original workspace | Copying the folder could disclose credentials or data | Clean worktree and positive-allowlist source packaging |

## Security evidence

Targeted pattern inspection of all five existing commits found fixtures and generated connection strings rather than confirmed real credentials. Gitleaks subsequently scanned the full original Git history without findings. The final package and new history are scanned separately during release verification; see VALIDATION.md.

Local tests target disposable loopback databases ending in `_test`. No production service, existing private database, or Google account was changed for validation. Dependency auditing, archive inspection, and browser/model evidence are recorded separately so static checks are not confused with live integration verification.
