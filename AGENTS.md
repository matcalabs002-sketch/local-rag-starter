# Starter-kit development

Status (2026-10-20): Local RAG Starter is published as a public MIT GitHub template with fresh history, with a twelve-step beginner guide, five rendered architecture diagrams, refreshed fictional screenshots, 124 passing local tests, nine real-model cases plus conversation isolation, fresh-environment/browser acceptance, tested backup/restore, and clean dependency/source/history scans. Verification boundaries are in VALIDATION.md.

- Default workflow: uploads → direct extraction → shared splitter → Ollama → local PostgreSQL/pgvector → citation-checked chat.
- Keep Chat, Sources, and Settings as the three workspace destinations. Activity belongs inside Sources; tutorials and architecture belong in documentation.
- Keep private configuration, originals, models, logs, and credentials out of Git and release packages. Do not reuse another workspace's private database.
- Use one dedicated session-lock connection for each writer operation. Never reconnect a lost writer session automatically.
- Publish document pointers and passages transactionally. Activate rebuilt indexes only after complete snapshot/version checks. Reconcile only the affected source kind/group.
- Check embedding pipeline identity as well as dimensions. Current evidence and validated citations are required for factual answers.
- Do not add automatic paid fallback or advertise an adapter as live-tested when only mocked contracts pass.
- Before behavioral changes, read CHANGELOG.md. Record WHAT, WHY, and WATCH FOR afterward. Separate refactoring commits from new behavior.
- Run `ruff check .` and `python -m pytest tests`. Destructive checks require a disposable loopback database ending in `_test`; never use the ordinary app database.
- Regenerate START-HERE.html after TUTORIAL.md or guide screenshot changes.
- Release archives use `python scripts/package_release.py`. Review their contents and scan history before publication.

Next steps: maintain the hosted checks linked in VALIDATION.md, complete physical Safari/Firefox checks, and manually verify the full Windows Ollama/Docker first run before claiming that coverage. Public repository: https://github.com/matcalabs002-sketch/local-rag-starter. The existing private application and its source history are preserved separately.
