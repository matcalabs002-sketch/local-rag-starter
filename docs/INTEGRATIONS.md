# Optional integrations

The default upload workflow requires none of these accounts. Use a separate library for public or portfolio data; never connect a public application to a private corpus.

## Google Drive

1. Install the extra: `pip install -c requirements-lock.txt -e '.[drive]'`. It is not required by the default upload installation.
2. Create a Google Cloud project, enable Drive API, configure the OAuth consent screen and permitted test users, and create a **Desktop app** OAuth client.
3. Set `DRIVE_FOLDER_ID` in `.env` to one directly monitored folder. Reload the app.
4. Open **Settings → Optional → Connect Google Drive**. Upload the downloaded OAuth client JSON, save it, then connect Google in the browser.
5. In Sources, refresh Drive and inspect recent activity.

OAuth tokens stay under ignored private storage. The grant is read-only for the Google account; application queries are limited to the selected folder. Nested folders are unsupported. Google Docs are exported as text; other supported types match the upload formats. Drive IDs identify files and versions remain strings.

Once attached, a library retains its Drive folder binding. Switching folders requires a separate library; do not edit database ownership records to bypass the check. Removing the folder setting does not authorize deleting its existing indexed documents.

## Public websites

In **Sources → Optional sources**, enter an HTTPS starting URL and a page limit. The crawler follows links on the same host, respects `robots.txt`, rejects private/local addresses and unsafe redirects, and imports readable HTML only. It does not execute JavaScript, sign in, or bypass access controls.

The limit defines the bounded crawl, not a promise to index every page of the website. A successful refresh replaces that source's bounded page set. Failed crawls keep the previous complete copy and display an error. Removing a website removes its indexed copy, not the website itself.

## Supabase

Use a deliberately selected project; this starter does not reuse another workspace's configuration.

Set `DATABASE_URL` from **Connect → Session pooler**, on port **5432**, and set `SUPABASE_PROJECT_URL`. Percent-encode reserved characters in the password portion of the connection URL. Set `DATABASE_CA_FILE` to the downloaded project CA certificate if the system certificate bundle cannot validate it. TLS remains `verify-full`; never disable verification to fix a certificate error.

Run `python -m rag init` against that explicit configuration. It creates only the `python_rag` schema and pgvector extension, with migration support for the earlier private app. Back up the database before any optional upgrade. Local starter testing never targets this remote project.

## Optional paid models

Set keys in `.env` and select a supported answer model in Settings. Currently declared adapters:

| Provider | Chat models | Embeddings | Verification |
| --- | --- | --- | --- |
| Ollama | `qwen3:4b` | `nomic-embed-text:v1.5` | Real local evaluation plus adapter tests |
| OpenAI | `gpt-4o-mini`, `gpt-4.1-mini` | `text-embedding-3-small` | Mock contract tests; live availability unverified |
| Anthropic | `claude-3-5-haiku-latest` | None | Mock contract tests; live availability unverified |

Cloud model IDs may be retired by their providers. Confirm availability before selecting one. Changing embeddings requires an explicit full rebuild. Paid embedding rebuilds send source passages to the selected provider and can incur charges. There is no automatic paid fallback, no included API credits, and no spending cap in the private starter.
