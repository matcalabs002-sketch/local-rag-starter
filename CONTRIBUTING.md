# Contributing

Start with the README setup and use fictional documents. Do not use personal or company source material in fixtures, screenshots, or issue reports.

Install the locked development environment with `pip install -r requirements-dev.txt`. Before proposing a change, run `ruff check .`, `python -m pytest tests`, `python -m pip check`, and `pip-audit -r requirements-lock.txt --disable-pip --no-deps`. Database checks must use a disposable loopback database ending in `_test`.

Add regression tests alongside the relevant files in `tests/`. Cover failure paths: incomplete snapshots, rejected model output, failed publication, lock loss, and changed evidence. For prompt or model changes, run `PYTHONPATH=. python tests/run_local_eval.py` with `TEST_DATABASE_URL` set to a disposable test database and inspect its recorded answers.

Update CHANGELOG.md for behavior changes using WHAT, WHY, and WATCH FOR. Keep refactoring separate from behavior changes. Do not add an integration to the advertised feature list until its success and failure paths are implemented and verified.

Dependencies live in pyproject.toml. Regenerate the lock with:

```bash
pip-compile --all-extras --strip-extras --no-emit-index-url --no-emit-trusted-host --output-file=requirements-lock.txt pyproject.toml
```

After changing TUTORIAL.md or guide screenshots, run `python build_guide.py` and commit START-HERE.html. `python scripts/package_release.py` builds a source archive from a fixed allowlist, excluding private state and development environments. Review the archive before sharing it.

This repository does not require proprietary credentials, project-specific agent memory, or a particular editor. Use the documented Python commands on your platform; platform CI jobs are evidence only after they actually run.

## Run the complete database suite locally

Stop the workspace while running tests if your computer has limited resources. Keep the ordinary application database separate. With the README's local Compose database running, create a **new disposable** database:

```text
docker compose exec -T db createdb -U rag rag_test
```

If it already exists, use it only if it was created for disposable tests. These tests truncate application tables in that database. Never rename or repoint your ordinary library just to satisfy the test guard.

Set the test URL without displaying your generated password. These commands read the private `.env`, replace only its database name, and put the result in the current shell's environment.

**macOS / Linux, activated environment:**

```bash
export TEST_DATABASE_URL="$(python -c 'from dotenv import dotenv_values; from urllib.parse import urlsplit, urlunsplit; u=urlsplit(dotenv_values(".env")["DATABASE_URL"]); print(urlunsplit(u._replace(path="/rag_test")))')"
python -m pytest tests
```

**Windows PowerShell, activated environment:**

```powershell
$env:TEST_DATABASE_URL = @'
from dotenv import dotenv_values
from urllib.parse import urlsplit, urlunsplit
url = urlsplit(dotenv_values(".env")["DATABASE_URL"])
print(urlunsplit(url._replace(path="/rag_test")))
'@ | python -
python -m pytest tests
```

The guard rejects remote hosts and names not ending in `_test`. Expected: all tests pass with no integration skips. For unit tests without PostgreSQL, use `python -m pytest tests -m "not integration"` instead.

To evaluate actual Ollama answers, confirm the local models are running and retain that disposable `TEST_DATABASE_URL`. The evaluator resets its library again:

**macOS / Linux:**

```bash
PYTHONPATH=. python tests/run_local_eval.py
```

**Windows PowerShell:**

```powershell
$env:PYTHONPATH = "."
python tests/run_local_eval.py
```

Inspect the fictional outputs in ignored `.private/local-evaluation.json`. A passing run reports all real-model cases and conversation isolation; this small corpus is not a general accuracy or security guarantee. Optional provider contracts use mocks and do not establish live cloud availability.
