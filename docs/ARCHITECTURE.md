# Local RAG Starter architecture

## The idea in plain language

**Retrieval-augmented generation (RAG)** gives a language model relevant reference material before asking it to answer. Here, a document becomes overlapping text passages. An embedding model represents each passage as a numeric vector. When you ask a question, the same model embeds the question and PostgreSQL finds nearby passage vectors. The answer model receives a bounded selection of those passages, then the app checks its cited passage numbers and saves the conversation.

The system does not fine-tune a model. Originals let you rebuild the index; embeddings make retrieval possible; retrieved passage text gives the answer model evidence. These are different responsibilities.

## Components and service boundaries

```mermaid
flowchart TB
    Browser[Browser: Chat, Sources, Settings] --> App[Streamlit application / Python rag package]
    App --> Files[Private original files and local settings]
    App --> Ollama[Local Ollama server: answer and embedding models]
    App --> DB[(PostgreSQL 17 + pgvector)]
    App -. optional .-> Drive[Google Drive API]
    App -. optional .-> Web[Public HTTPS websites]
    App -. explicitly selected .-> Paid[OpenAI or Anthropic API]
```

| Component | Default location | Responsibility |
| --- | --- | --- |
| Browser and Streamlit | `127.0.0.1:8503` | Workspace and progress/errors; no separate React frontend or HTTP API layer |
| Ollama | `127.0.0.1:11435` | `qwen3:4b` answers; `nomic-embed-text:v1.5` embeddings |
| PostgreSQL/pgvector | `127.0.0.1:55432` via Compose | Searchable passages/vectors, source registry, index generations, conversations, activity |
| Original file storage | `RAG_DATA_DIR`, default `.private` | Content-addressed immutable upload originals and private workspace settings |
| Configuration | Private `.env` plus environment | Connections, model choices, limits, private storage path |

With the default providers, document extraction, embedding, retrieval, and generation run on your computer. Installation downloads software/models. Optional connectors send requests to their configured services; selecting a cloud model sends its request data to that provider. Supabase moves PostgreSQL storage to the configured remote host. There is no implicit paid fallback.

`.env.example` is documentation, never runtime configuration. Environment variables override `.env`; absent keys use typed code defaults. The UI persists selected settings privately; restart/reload and active-index checks ensure configuration must match the searchable embedding pipeline.

## Document ingestion

```mermaid
sequenceDiagram
    actor User
    participant UI as Sources page
    participant Upload as Upload service
    participant Files as Private original store
    participant Model as Embedding model
    participant DB as PostgreSQL
    User->>UI: Select file and index (or confirm replacement)
    UI->>Upload: Name and bounded file bytes
    Upload->>Upload: Validate name and byte limits
    Upload->>DB: Acquire dedicated writer lock, check versions
    Upload->>Upload: Extract text and split into passages
    Upload->>Model: Embed passages
    Model-->>Upload: Validated vectors
    Upload->>Files: Preserve immutable original by SHA-256
    Upload->>DB: Transaction: publish upload reference and passages
    DB-->>Upload: Commit complete document
    Upload-->>UI: Result or actionable error
```

Text extraction uses pypdf, docx2txt, UTF-8 decoding, and CSV handling. Preview and indexing use the same recursive splitter. Defaults are 1,000-character passages with 150-character overlap, 50 MiB per upload, and additional bounded text/passage counts.

Filenames are labels, never trusted filesystem paths. A generated document ID identifies an upload; SHA-256 of its bytes identifies its version and original blob. Identical content is unchanged; a changed upload with the same name requires explicit replacement. Embedding or publication failure keeps the previous complete searchable document. An unreferenced blob from a failed operation can be removed through explicit cleanup.

Google Drive follows the source-adapter contract, while websites use a bounded crawl and scoped reconciliation. Neither connector can delete local uploads. See [Integrations](INTEGRATIONS.md) for their actual limits.

## Question answering

```mermaid
sequenceDiagram
    actor User
    participant Chat as Chat service
    participant Model as Configured models
    participant DB as PostgreSQL
    User->>Chat: Question in selected conversation
    opt Follow-up needs recent context
        Chat->>DB: Read recent exchange
        Chat->>Model: Rewrite into a standalone search query
        Model-->>Chat: Validated query
    end
    Chat->>Model: Embed search query
    Model-->>Chat: Query vector
    Chat->>DB: Check pipeline identity and retrieve in one snapshot
    DB-->>Chat: Exact cosine-ranked passages and library revision
    alt No passages
        Chat->>Chat: Explicit missing-information reply
    else Passages available
        Chat->>Model: Bounded evidence and question, request structured answer
        Model-->>Chat: Answer text and citation IDs
        Chat->>Chat: Validate schema and supplied citation IDs
    end
    Chat->>DB: Save turn only if evidence revision is still current
    DB-->>Chat: Persisted turn or explicit stale-evidence error
    Chat-->>User: Answer and inspectable sources, or actionable error
```

The default retrieval limit is five passages with a 12,000-character evidence budget. Retrieval is exact cosine search, intended for small libraries; it does not use approximate indexes, hybrid search, or a reranker. Basic greetings have direct conversational replies and bypass factual retrieval.

A question embedding and document embeddings must share the same provider, model, dimensions, and chunk configuration. Equal dimensions alone do not make two models compatible. Pipeline identity is checked inside the retrieval snapshot. If evidence changes while the model is answering, saving fails explicitly rather than presenting a stale answer as current.

Structured output is validated using Pydantic contracts. Unknown citation numbers are rejected; an answer with no citations becomes the missing-information response. **Citation identity is not factual entailment**: a valid citation does not prove every generated claim follows from it. Source instructions are treated as untrusted, with measured but incomplete prompt-injection mitigation.

## Data model

All application tables live in the `python_rag` schema. The central relationships below are actual foreign keys; the diagram omits operational columns for readability.

```mermaid
erDiagram
    library ||--o{ uploaded_documents : owns
    index_generations ||--o{ generation_documents : contains
    index_generations ||--o{ generation_chunks : contains
    generation_documents ||--o{ generation_chunks : has_passages
    sessions ||--o{ turns : contains

    library {
        boolean id PK
        text pipeline_id
        bigint revision
    }
    uploaded_documents {
        text id PK
        boolean library_id FK
        text name
        text version
        bigint size
    }
    index_generations {
        uuid id PK
        text pipeline_id
        text status
        text embedding_model
        int embedding_dimensions
    }
    generation_documents {
        uuid generation_id PK,FK
        text id PK
        text version
        text source_kind
        text source_group
    }
    generation_chunks {
        bigint id PK
        uuid generation_id FK
        text file_id FK
        int position
        text content
        jsonb metadata
        vector embedding
    }
    sessions {
        uuid id PK
        text title
    }
    turns {
        uuid id PK
        uuid session_id FK
        text question
        text answer
        jsonb sources
    }
```

`uploaded_documents` is the current local-upload registry. Its IDs and versions correspond logically to local entries in `generation_documents`; that correspondence is enforced by application publication/rebuild checks, not a direct foreign key between these two tables. Each generation can also contain Drive and website documents. Passage lookup uses the composite generation/document identity.

Additional tables record remote website configuration, exclusions, sync status, and activity. Legacy `documents`/`chunks` tables remain for migration compatibility; generation tables are the active search path. `schema.sql` is the source of truth. Deleting a document removes searchable copies across retained generations; old saved conversation text is separate from current evidence.

## Atomic updates and recovery

Only one index generation is active. A rebuild stages uploaded originals and all configured remote sources into a separate generation, then rechecks complete membership and versions before activation. Failed builds leave the previous active index available. Recovery to a previous generation is allowed only when its source versions match the current library; it cannot resurrect removed uploads.

Ordinary database operations use a connection pool. Writers acquire the same advisory lock using a dedicated physical session. A lost lock connection is never silently reconnected. Upload references and passages publish transactionally. Remote source reconciliation is scoped to its source kind/group and only proceeds after a complete snapshot.

| Failure | Visible behavior and recovery |
| --- | --- |
| Unreadable upload or embedding failure | Explicit source/activity error; previous replacement remains searchable |
| Incomplete remote snapshot | No destructive reconciliation; retry after fixing connectivity |
| Changed evidence during answer | Answer is not saved; retry against current evidence |
| Failed index rebuild | Existing active generation remains; fix error before retrying |
| Embedding configuration mismatch | Retrieval is rejected; restore matching settings or rebuild |
| Lost writer connection | Operation fails; do not reconnect and continue without its lock |
| Missing original file | Rebuild fails visibly; restore matching private storage from backup |
| Unreferenced original | Explicit cleanup removes it; referenced retained-generation blobs stay |

Remote refresh runs while the application is open. `python -m rag sync` is the explicit non-UI alternative, not a separately provisioned background worker. Drive sign-in failure does not block independently configured website refresh.

## Code map and extension points

| Module | Responsibility |
| --- | --- |
| `app.py`, `rag/workspace/` | Streamlit entry point, Chat/Sources/Settings presentation |
| `rag/config.py`, `rag/__main__.py` | Typed settings and setup/init/check/sync/cleanup commands |
| `rag/uploads.py`, `rag/loaders.py` | Immutable originals, extraction, shared splitting, upload publication |
| `rag/sources.py`, `rag/drive.py` | Source protocol and Drive adapter |
| `rag/models.py`, `rag/types.py` | Provider capabilities, requests, structured model/data contracts |
| `rag/chat.py` | Follow-up handling, retrieval, answer validation, persistence orchestration |
| `rag/store.py`, `rag/schema.sql` | Database operations, locks, transactions, generations, source registry |
| `rag/sync.py`, `rag/websites.py`, `rag/reindex.py` | Source refresh, bounded crawl, complete index rebuild/recovery |

**New source:** implement `snapshot`, `download`, and `verify` with stable IDs, string versions, bounded reads, and complete snapshots. Include it in rebuild sources and source-scoped reconciliation. Test incomplete snapshots and version changes before enabling deletion.

**New model:** add a declared capability and adapter request/response validation. Verify dimensions, structured output, missing facts, citation identity, and the fictional real-model evaluation. Do not advertise live provider support based only on mocked tests.

**New storage:** PostgreSQL is the sole backend. Add an interface when a second implementation is working and verified; the starter intentionally avoids unused abstraction layers.

**Changed prompt or retrieval:** retain source boundaries and citation validation, run the binary evaluation, and inspect recorded answers. Do not rely on model self-evaluation alone.

## Operational boundary

This is a private, single-user tool with no public authentication, tenant separation, or hosted spending enforcement. Back up PostgreSQL and private original/settings storage together, with writers stopped for a consistent copy. Physical device checks and optional live integrations have separate verification limits in [Validation](../VALIDATION.md).
