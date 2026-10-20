# Your first chatbot with Local RAG Starter

Build a local chatbot that answers from a fictional handbook and shows supporting passages. No paid AI key, Google account, or Supabase account is required. You will install tools, download two models, start a database, upload a document, and check an answer.

## 1. Install the prerequisites

A **terminal** is the application where you enter commands. Open Terminal on macOS, your terminal on Linux, or **PowerShell** on Windows. Copy only the commands inside a code block, one line at a time. Wait for each command to finish; stop and check errors before continuing. Do not type the code-block language labels.

| Tool | Why you need it | Installation |
| --- | --- | --- |
| Git | Downloads the source code | [Official installers for your OS](https://git-scm.com/install/) |
| Python **3.12** | Runs the application | Use the managed installation below, or an existing Python 3.12 installation |
| Docker with Compose | Runs PostgreSQL and pgvector | [Docker installation choices](https://docs.docker.com/compose/install/); open Docker Desktop after installing on macOS/Windows |
| Ollama | Runs the answer and embedding models | [Official download](https://ollama.com/download); choose your operating system |

Use a computer supported by these tools and leave several GB free for models, Python packages, and the database image. Generation speed and available memory vary by hardware. Internet is needed for installation and model downloads; the default chat and upload path uses local services afterward. Optional online connectors need internet.

### Install Python 3.12 if you do not have it

This project requires 3.12, not simply the newest Python release. [uv](https://docs.astral.sh/uv/getting-started/installation/) can install a managed Python without replacing your system Python. It is a setup helper, not an application dependency. Its [Python guide](https://docs.astral.sh/uv/guides/install-python/) describes the managed distributions.

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows PowerShell:**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

These are the upstream installer commands; review the linked installation instructions if you prefer a package manager or downloaded binary. Close and reopen the terminal after installation so it can find `uv`. Then, on either platform:

```text
uv --version
uv python install 3.12
```

You will create the project's environment using uv in step 2. If Python 3.12 is already installed, you can skip uv and use the standard Python alternative in that step.

### Check the other tools

**Both platforms:**

```text
git --version
docker --version
docker compose version
ollama --version
docker info
```

Expect version information. `docker info` must connect to a running engine; start Docker Desktop or the Linux Docker service if it cannot. Ollama may warn that its server is not running yet; you will start it in step 4. A “command not found” error means the tool is missing or you need to reopen the terminal.

Check [Docker Desktop license terms](https://docs.docker.com/subscription-billing/desktop-license/) for company use. Linux Docker Engine with the Compose plugin is another option.

## 2. Download the project and create its environment

Run these commands from the folder where you want to keep your projects. `git clone` creates a new `local-rag-starter` folder; `cd` enters it.

**Both platforms:**

```text
git clone https://github.com/matcalabs002-sketch/local-rag-starter.git
cd local-rag-starter
```

A **virtual environment** is a private set of Python packages for this project. It keeps dependencies separate from other applications.

If you installed uv in step 1, create it with:

```text
uv venv --python 3.12 --seed .venv
```

Alternatively, with an existing Python 3.12 installation, use **one** of these creation commands instead:

**macOS / Linux:**

```bash
python3.12 -m venv .venv
```

**Windows PowerShell:**

```powershell
py -3.12 -m venv .venv
```

Now activate the environment. Activation applies only to the current terminal.

**macOS / Linux:**

```bash
source .venv/bin/activate
```

**Windows PowerShell:**

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can avoid changing execution policies: use `.\.venv\Scripts\python.exe` wherever the remaining instructions say `python`. You do not need activation when you use that full executable path.

**Both platforms, after activation:**

```text
python --version
python -m pip install -r requirements.txt
```

Expect `Python 3.12.x` and a successful installation. The lock constrains exact dependency versions while the base install excludes Google packages and development tools.

## 3. Generate settings and start PostgreSQL

Keep this terminal as your **application terminal**. Run every project command from the repository root, where `app.py` and `compose.yaml` are located.

**Both platforms:**

```text
python -m rag setup
docker compose up -d --wait
docker compose ps
```

`setup` creates `.env` with a generated database password and matching connection URL. **Do not copy `.env.example` first.** It documents available settings, but the recommended setup command needs to create a new `.env`. If configuration already exists, setup preserves it and asks you to edit explicitly.

Expect a running, healthy `db` service. The database listens at `127.0.0.1:55432`; `127.0.0.1` means your own computer. Data persists in a Docker volume across container restarts. Keep `.env` private and do not paste its contents into issues or screenshots.

If port 55432 is occupied, before starting your new database edit **both** `POSTGRES_PORT` and the port inside `DATABASE_URL` to the same available number. Preserve the generated password. Do not change that password after creating the volume without also changing PostgreSQL's password.

## 4. Start Ollama and download the models

You need **two terminals**:

| Terminal | What runs there |
| --- | --- |
| Application | Model downloads, initialization, then Streamlit |
| Model server | `ollama serve`, left running |

The default endpoint is port **11435**. The app never starts or stops Ollama automatically.

### Model server terminal

Open a second terminal and enter the block for your OS. No Python activation or project folder is needed in this terminal.

**macOS / Linux:**

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama serve
```

**Windows PowerShell:**

```powershell
$env:OLLAMA_HOST = "127.0.0.1:11435"
ollama serve
```

Expect server output showing it is listening. This command stays running; leave the terminal open.

### Application terminal

Return to the first terminal, where your environment is activated. Download both models through the same endpoint:

**macOS / Linux:**

```bash
OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3:4b
OLLAMA_HOST=127.0.0.1:11435 ollama pull nomic-embed-text:v1.5
OLLAMA_HOST=127.0.0.1:11435 ollama list
```

**Windows PowerShell:**

```powershell
$env:OLLAMA_HOST = "127.0.0.1:11435"
ollama pull qwen3:4b
ollama pull nomic-embed-text:v1.5
ollama list
```

Expect both exact model names in the list. The answer model writes responses; the embedding model turns passages and questions into comparable numeric vectors. Downloads may take time and several GB; the app does not download models on your behalf.

### If Ollama already runs on 11434

You can reuse it instead of starting the second server. Edit `.env` to set `OLLAMA_URL=http://127.0.0.1:11434`. In the application terminal set `OLLAMA_HOST` to `127.0.0.1:11434` using your OS syntax above, then pull/list the two models through that endpoint. Do not mix a server on 11434 with downloads or app settings pointing to 11435.

## 5. Initialize and open the workspace

**Both platforms, application terminal:**

```text
python -m rag init
python -m rag check
```

Initialization creates the application schema in the configured database; it preserves existing source data. It does not create a missing PostgreSQL database or download models.

Expect:

```text
OK    Configuration
OK    Database schema
OK    Active index
OK    Selected models
```

Fix any `ERROR` before continuing. Then launch:

```text
python -m streamlit run app.py
```

Open [http://127.0.0.1:8503](http://127.0.0.1:8503). Leave the application terminal running.

| Page | What to do there |
| --- | --- |
| Chat | Ask questions, start conversations, read source passages |
| Sources | Upload, replace, remove, refresh sources, inspect recent activity |
| Settings | Check connections, select models, rebuild/recover indexes, connect optional integrations |

If port 8503 is occupied, use `python -m streamlit run app.py --server.port 8506` and open `http://127.0.0.1:8506` instead.

## 6. Upload the sample and check an answer

1. Open **Sources**.
2. Select `samples/welcome-handbook.txt` from your cloned repository.
3. Click **Index documents** and wait for completion.
4. Confirm the document is listed with searchable passages. Inspect Recent activity if indexing fails.
5. Open **Chat** and ask **What is the project code?**
6. Expect **ORCHID-742** and a supporting source passage. Expand the passage and compare its text with the answer.

![Fictional sample conversation](docs/images/chat-desktop.png)

Try these checks in order:

| Question | Expected result |
| --- | --- |
| What is the project code? | ORCHID-742, with a source |
| How many days do clients have to request a refund? | 14 calendar days, with a source |
| And how long does the review take? | Three business days; the follow-up refers to refunds |
| What is the CEO's personal mobile phone number? | An explicit missing-information response |

A new conversation starts with empty history. General greetings do not require document evidence. Factual questions use current retrieved passages; the model is not trained on your uploads. Read the [architecture walkthrough](docs/ARCHITECTURE.md) to follow each stage.

Citation checks confirm passage identity and current evidence, not the truth of every sentence. Inspect source text for important answers. Local models can still make mistakes.

## 7. Add, replace, or remove your own documents

Supported uploads: **text PDF, DOCX, UTF-8 TXT, Markdown, CSV**. Scanned/image-only PDFs need OCR elsewhere first; encrypted PDFs are unsupported. The default file limit is 50 MiB, with additional text/passage limits to keep work bounded.

Start with non-sensitive test documents. An unchanged upload is detected. To replace a document, edit a copy of the sample, retain its original filename, enable the replacement checkbox, and upload it again. Try changing ORCHID-742 to LOTUS-319, then ask for the current code. A failed replacement preserves the previous complete searchable version.

To remove an upload, expand it in Sources, confirm removal, and click **Remove document**. Removal deletes its searchable copies across retained indexes. Old conversation text remains conversation history; it is not current evidence. Unreferenced original files may remain until you explicitly run `python -m rag cleanup` after stopping Streamlit. Cleanup is maintenance, not a backup or undo command.

## 8. Stop and start again

To stop: press **Ctrl+C** in the application terminal and in a manually started Ollama server terminal. From the project folder run:

```text
docker compose stop
```

This keeps the database volume and private originals. **Do not use `docker compose down -v` for an ordinary shutdown: it deletes the database volume.**

To restart later:

1. Open Docker Desktop or start the Docker engine.
2. Open a terminal in `local-rag-starter` and activate `.venv` using step 2.
3. Run `docker compose up -d --wait`.
4. Start Ollama as in step 4, or confirm your existing server is running. Downloaded models remain available; you do not need to pull them each time.
5. Run `python -m rag check`, then `python -m streamlit run app.py`.

Do not rerun setup or change the generated password on every launch. `deactivate` exits the Python environment after stopping the app.

## 9. Customize and back up

Open `.env` in a text editor. It is a settings file, not a terminal script. Environment variables already set in your shell override `.env`; absent settings use code defaults. [.env.example](.env.example) lists all supported variables. Restart Streamlit or reload after editing settings.

| Goal | Where to change it |
| --- | --- |
| Change answer model | Settings; choose a model available on the selected provider |
| Change embeddings or passage sizes | Settings → Advanced → Rebuild index |
| Change local endpoint or retrieval/context limits | `.env` |
| Change original storage folder | `RAG_DATA_DIR` in `.env`; migrate the existing originals separately |
| Add Drive, websites, remote PostgreSQL, paid APIs | [Optional integration guide](docs/INTEGRATIONS.md) |

Embeddings must use a matching provider, model, dimensions, and chunk configuration. Rebuild prepares a separate index before switching the active one. Failed builds keep the previous active index; recovery is allowed only when source versions match the current library. Keep the existing working configuration until you understand this process.

### Create a local backup

Stop Streamlit first and avoid imports or other writers until the backup finishes. Keep PostgreSQL running for the database dump. From the repository root, save `.env`, a database dump, and the **whole configured `RAG_DATA_DIR`**, including originals and private settings. The defaults below use `.private`. Store backups outside Git and protect them as private data.

**macOS / Linux:**

```bash
mkdir -p .private/backup
docker compose exec -T db pg_dump -U rag -d rag -Fc -f /tmp/local-rag-backup.dump
docker compose cp db:/tmp/local-rag-backup.dump .private/backup/database.dump
cp .env .private/backup/settings.env
```

**Windows PowerShell:**

```powershell
New-Item -ItemType Directory -Force .private/backup
docker compose exec -T db pg_dump -U rag -d rag -Fc -f /tmp/local-rag-backup.dump
docker compose cp db:/tmp/local-rag-backup.dump .private/backup/database.dump
Copy-Item .env .private/backup/settings.env
```

Copy `.private` (or your configured data directory) to secure backup storage outside this checkout. Using container copy avoids PowerShell binary-redirection issues. For a remote/native database use its own backup tools and configured database name instead of these Compose commands.

To restore safely, use a **new** database/volume: copy the dump into its PostgreSQL container, restore with `pg_restore -U rag -d rag --no-owner`, restore the matching original files and private settings, and point `.env` at that database with its actual credentials. Run `python -m rag check` before starting the app. See the [PostgreSQL restore reference](https://www.postgresql.org/docs/17/app-pgrestore.html); never trial a restore over your only working library. A database-only backup cannot rebuild uploads whose originals are missing.

## 10. Use an existing PostgreSQL server

Docker is optional if you already administer PostgreSQL 17 with [pgvector](https://github.com/pgvector/pgvector) installed. This is an alternative to step 3's Compose commands; beginners should use Compose first.

Create a dedicated `rag` role and `rag` database using your PostgreSQL administration tools. Have an administrator enable `vector` in an `extensions` schema in that database. The application role must own its `python_rag` schema and have the privileges needed by initialization. Run against the dedicated database only:

```sql
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
```

Set `DATABASE_URL` in the generated `.env` to that database's real URL, preserving privacy and URL-encoding special characters in the password. The Compose-specific `POSTGRES_PASSWORD` and `POSTGRES_PORT` are unused when you do not run Compose. Continue with Ollama, `python -m rag init`, and `python -m rag check`. Remote Supabase setup has additional TLS and session-pool requirements documented in [Integrations](docs/INTEGRATIONS.md).

## 11. Troubleshoot a failed step

| Symptom | What to check |
| --- | --- |
| Python is not 3.12 | Recreate `.venv` using `uv venv --python 3.12 --seed .venv`, then activate it and reinstall |
| No module named rag or streamlit | Enter the repository root, activate its `.venv`, install `requirements.txt` |
| PowerShell blocks activation | Use `.\.venv\Scripts\python.exe` in place of `python`; no policy change is needed |
| Setup says .env exists | Existing settings were preserved; edit that file rather than overwriting credentials |
| Cannot connect to Docker | Start Docker Desktop/the engine; confirm `docker info` works |
| Database authentication fails | `.env` must match the existing volume's database password; changing the file alone cannot reset PostgreSQL |
| Database port occupied | Change `POSTGRES_PORT` and the port in `DATABASE_URL` together; recreate only this project's container, preserving its volume |
| Ollama address already in use | Check the existing server; do not start two servers on the same endpoint |
| Selected models check fails | Match `OLLAMA_URL` and `OLLAMA_HOST`, then use `ollama list` on that endpoint; pull exact model names |
| First answer is slow | The model may be loading; check server output and available memory; do not assume a fixed response time |
| No readable text | Use supported UTF-8 text or a text PDF; OCR/encrypted PDFs are not included |
| Index settings differ | Restore the active configuration or rebuild through Settings |
| Original missing | Restore the matching private original files before rebuilding |
| Another sync is running | Wait for the writer lock; do not bypass it |
| Failed import/replacement | Read Sources → Recent activity; inspect the specific failure before retrying |
| Test database rejected | Full tests require a disposable loopback database ending in `_test`; follow Contributing |

For help, open a [GitHub issue](https://github.com/matcalabs002-sketch/local-rag-starter/issues) with your OS, Python version, failing step, and sanitized error. Never include `.env`, credentials, personal documents, or private conversation screenshots. Report security issues using [SECURITY.md](SECURITY.md).

## 12. Next steps

Read [Architecture](docs/ARCHITECTURE.md) to understand the implementation, [Contributing](CONTRIBUTING.md) to run isolated tests, and [Validation](VALIDATION.md) to see what has actually been verified. On GitHub, choose **Use this template** to start your own repository. Keep the MIT license and test any new formats or providers before advertising them.

This starter is a local single-user tool with no public authentication. A hosted multi-user product requires additional design and verification.
