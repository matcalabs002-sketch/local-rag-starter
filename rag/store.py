"""Postgres operations. Sync holds one connection-level lock for its entire run."""

from contextlib import contextmanager
from importlib.resources import files as resource_files
from urllib.parse import urlparse
from uuid import uuid4
from threading import Lock
import certifi
import numpy as np
import psycopg
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pgvector.psycopg import register_vector
from .config import ADVISORY_LOCK_ID, RagError, Settings, TOP_K, pipeline_id
from .types import Source, WebsiteSource
from .connection import connection_message

_POOLS = {}
_POOLS_LOCK = Lock()


def _pool_key(settings):
    return (settings.database_url, settings.ca_file)


def _pool(settings):
    key = _pool_key(settings)
    with _POOLS_LOCK:
        if key not in _POOLS:
            local = urlparse(settings.database_url).hostname in ("localhost", "127.0.0.1", "::1")
            ssl = (
                {"sslmode": "disable"}
                if local
                else {"sslmode": "verify-full", "sslrootcert": settings.ca_file or certifi.where()}
            )
            _POOLS[key] = ConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=4,
                timeout=10,
                kwargs=dict(
                    autocommit=True,
                    row_factory=dict_row,
                    connect_timeout=10,
                    options="-c statement_timeout=30000",
                    **ssl,
                ),
                open=True,
            )
        return _POOLS[key]


class Store:
    def __init__(self, settings: Settings, connection=None):
        self.settings, self.connection = settings, connection

    @contextmanager
    def connect(self, vector=True):
        if self.connection is not None:
            yield self.connection
            return
        self.settings.validate()
        try:
            with _pool(self.settings).connection() as conn:
                conn.execute("set search_path=python_rag,public,extensions")
                if vector:
                    try:
                        register_vector(conn)
                    except psycopg.ProgrammingError:
                        raise RagError("The vector extension is missing. Create library tables in Setup.") from None
                yield conn
        except RagError:
            raise
        except (psycopg.Error, TimeoutError) as error:
            raise RagError(connection_message(error)) from None

    @contextmanager
    def direct_connection(self, vector=True):
        """A dedicated physical session for advisory locks and schema setup."""
        self.settings.validate()
        local = urlparse(self.settings.database_url).hostname in ("localhost", "127.0.0.1", "::1")
        ssl = (
            {"sslmode": "disable"}
            if local
            else {"sslmode": "verify-full", "sslrootcert": self.settings.ca_file or certifi.where()}
        )
        try:
            conn = psycopg.connect(
                self.settings.database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=10,
                options="-c statement_timeout=30000",
                **ssl,
            )
        except psycopg.Error as error:
            raise RagError(connection_message(error)) from None
        try:
            conn.execute("set search_path=python_rag,public,extensions")
            if vector:
                try:
                    register_vector(conn)
                except psycopg.ProgrammingError:
                    raise RagError("The vector extension is missing. Create library tables in Setup.") from None
            yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.direct_connection(vector=False) as conn:
            conn.execute(resource_files("rag").joinpath("schema.sql").read_text())
            with conn.transaction():
                if not conn.execute("select id from python_rag.library where id").fetchone():
                    current = pipeline_id(self.settings)
                    conn.execute(
                        "insert into python_rag.library(id,folder_id,pipeline_id) values(true,%s,%s)", ("", current)
                    )
                    conn.execute(
                        """update python_rag.index_generations set pipeline_id=%s,
                        embedding_provider=%s,embedding_model=%s,embedding_dimensions=%s,
                        chunk_size=%s,chunk_overlap=%s where status='active' """,
                        (
                            current,
                            self.settings.embedding_provider,
                            self.settings.embedding_model,
                            self.settings.embedding_dimensions,
                            self.settings.chunk_size,
                            self.settings.chunk_overlap,
                        ),
                    )

    def ready(self):
        with self.connect(vector=False) as conn:
            if not conn.execute("select to_regclass('python_rag.sync_status') as t").fetchone()["t"]:
                raise RagError("Your connection works. Create library tables in Setup next.")

    @contextmanager
    def sync_lock(self):
        # No automatic reconnect: a lost lock connection must also abort all its writes.
        with self.direct_connection() as conn:
            if not conn.execute("select pg_try_advisory_lock(%s) as ok", (ADVISORY_LOCK_ID,)).fetchone()["ok"]:
                raise RagError("Another sync is already running. Wait for it to finish.")
            try:
                yield Store(self.settings, conn)
            finally:
                if not conn.closed and not conn.broken:
                    conn.execute("select pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))

    def bind(self, folder, pipeline):
        with self.connect() as conn, conn.transaction():
            conn.execute(
                "insert into python_rag.library(id,folder_id,pipeline_id) values(true,%s,%s) on conflict do nothing",
                (folder, pipeline),
            )
            row = conn.execute("select * from python_rag.library where id").fetchone()
            if not row["folder_id"] and folder:
                conn.execute("update python_rag.library set folder_id=%s where id", (folder,))
            elif row["folder_id"] != folder:
                raise RagError(
                    "This library belongs to a different Drive folder. Use a separate database or deliberately reset the Python library."
                )
            if row["pipeline_id"] != pipeline:
                raise RagError("The embedding or splitter settings changed. A deliberate full reindex is required.")

    def bind_folder(self, folder):
        """Validate ownership while allowing a pending generation to use new settings."""
        with self.connect() as conn:
            row = conn.execute("select folder_id from python_rag.library where id").fetchone()
            if not row:
                raise RagError("Run one normal sync before rebuilding the search index.")
            if row["folder_id"] != folder:
                raise RagError(
                    "This library belongs to a different Drive folder. Use a separate database or deliberately reset the Python library."
                )

    def reconcile(self, ids):
        with self.connect() as conn, conn.transaction():
            generation = self._active_id(conn)
            result = conn.execute(
                """delete from python_rag.generation_documents
                where generation_id=%s and source_kind='drive' and not(id=any(%s::text[]))""",
                (generation, list(ids)),
            )
            if result.rowcount:
                conn.execute("update python_rag.library set revision=revision+1 where id")
            self._refresh_generation_counts(conn, generation)

    def versions(self):
        with self.connect() as conn:
            generation = self._active_id(conn)
            return {
                r["id"]: r["version"]
                for r in conn.execute(
                    "select id,version from python_rag.generation_documents where generation_id=%s and source_kind='drive'",
                    (generation,),
                )
            }

    def replace(self, file, chunks, vectors):
        if not chunks or len(chunks) != len(vectors):
            raise RagError("A document did not finish processing. Its previous version was kept.")
        with self.connect() as conn, conn.transaction():
            generation = self._active_id(conn)
            dimensions = conn.execute(
                "select embedding_dimensions from python_rag.index_generations where id=%s", (generation,)
            ).fetchone()["embedding_dimensions"]
            if any(len(vector) != dimensions for vector in vectors):
                raise RagError(
                    f"The embedding model returned vectors that do not match this index ({dimensions} values required)."
                )
            conn.execute(
                """insert into python_rag.generation_documents
                (generation_id,id,name,version,mime_type,url,source_kind,source_group)
                values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(generation_id,id) do update set
                name=excluded.name,version=excluded.version,mime_type=excluded.mime_type,url=excluded.url,
                source_kind=excluded.source_kind,source_group=excluded.source_group,indexed_at=now(),error=null""",
                (
                    generation,
                    file.id,
                    file.name,
                    file.version,
                    file.mime_type,
                    file.url,
                    getattr(file, "source_kind", "drive"),
                    getattr(file, "source_group", None),
                ),
            )
            conn.execute(
                "delete from python_rag.generation_chunks where generation_id=%s and file_id=%s", (generation, file.id)
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """insert into python_rag.generation_chunks
                    (generation_id,file_id,position,content,metadata,embedding) values(%s,%s,%s,%s,%s,%s)""",
                    [
                        (generation, file.id, i, c.text, Jsonb(c.metadata), np.asarray(v, dtype=np.float32))
                        for i, (c, v) in enumerate(zip(chunks, vectors))
                    ],
                )
            conn.execute("update python_rag.library set revision=revision+1 where id")
            self._refresh_generation_counts(conn, generation)

    def assert_pipeline(self, settings):
        active = self.active_generation()
        if not active or active["pipeline_id"] != pipeline_id(settings):
            raise RagError(
                "The embedding or chunk settings differ from the active index. Rebuild in Settings before importing or chatting."
            )

    def uploads(self):
        with self.connect(vector=False) as conn:
            return conn.execute(
                "select id,name,version,mime_type,size from python_rag.uploaded_documents order by name"
            ).fetchall()

    def publish_upload(self, file, chunks, vectors):
        """Publish the original-file pointer and searchable chunks in one transaction."""
        with self.connect() as conn, conn.transaction():
            Store(self.settings, conn).replace(file, chunks, vectors)
            conn.execute(
                """insert into python_rag.uploaded_documents(id,name,version,mime_type,size)
                values(%s,%s,%s,%s,%s) on conflict(id) do update set
                name=excluded.name,version=excluded.version,mime_type=excluded.mime_type,size=excluded.size""",
                (file.id, file.name, file.version, file.mime_type, file.size),
            )

    def remove_upload(self, file_id):
        with self.connect(vector=False) as conn, conn.transaction():
            if not conn.execute(
                "delete from python_rag.uploaded_documents where id=%s returning id", (file_id,)
            ).fetchone():
                raise RagError("The uploaded document was not found. Refresh Sources.")
            # Remove all retained copies so recovery cannot resurrect a deleted upload.
            conn.execute("delete from python_rag.generation_documents where id=%s and source_kind='local'", (file_id,))
            for row in conn.execute("select id from python_rag.index_generations"):
                self._refresh_generation_counts(conn, row["id"])
            conn.execute("update python_rag.library set revision=revision+1 where id")

    def counts(self):
        with self.connect(vector=False) as conn:
            generation = self._active_id(conn)
            return conn.execute(
                """select
                (select count(*) from python_rag.generation_documents where generation_id=%s) as documents,
                (select count(*) from python_rag.generation_chunks where generation_id=%s) as chunks""",
                (generation, generation),
            ).fetchone()

    def documents(self):
        with self.connect(vector=False) as conn:
            generation = self._active_id(conn)
            return conn.execute(
                """select d.id,d.name,d.version,d.mime_type,d.url,d.source_kind,d.source_group,
                d.indexed_at,d.error,
                count(c.id)::integer as chunk_count,g.id as generation_id,g.embedding_model
                from python_rag.generation_documents d
                join python_rag.index_generations g on g.id=d.generation_id
                left join python_rag.generation_chunks c on c.generation_id=d.generation_id and c.file_id=d.id
                where d.generation_id=%s group by d.id,d.name,d.version,d.mime_type,d.url,d.source_kind,
                d.source_group,d.indexed_at,d.error,g.id,g.embedding_model
                order by d.name""",
                (generation,),
            ).fetchall()

    def add_website_source(self, start_url, max_pages=10):
        from .websites import MAX_SITE_PAGES, canonical_url

        normalized = canonical_url(start_url)
        maximum = max(1, min(int(max_pages), MAX_SITE_PAGES))
        with self.connect(vector=False) as conn, conn.transaction():
            row = conn.execute("select id from python_rag.website_sources where start_url=%s", (normalized,)).fetchone()
            if row:
                conn.execute(
                    """update python_rag.website_sources set max_pages=%s,enabled=true,status='pending',
                    last_error=null,updated_at=now() where id=%s""",
                    (maximum, row["id"]),
                )
                site_id = str(row["id"])
            else:
                site_id = str(uuid4())
                conn.execute(
                    """insert into python_rag.website_sources(id,start_url,max_pages)
                    values(%s,%s,%s)""",
                    (site_id, normalized, maximum),
                )
        return site_id

    def website_sources(self, enabled_only=False):
        with self.connect(vector=False) as conn:
            where = " where enabled" if enabled_only else ""
            rows = conn.execute("select * from python_rag.website_sources" + where + " order by created_at").fetchall()
            return [WebsiteSource(str(row["id"]), row["start_url"], row["max_pages"], row["enabled"]) for row in rows]

    def website_source_rows(self):
        with self.connect(vector=False) as conn:
            return conn.execute("select * from python_rag.website_sources order by created_at").fetchall()

    # Short UI-facing names keep app code readable while the explicit methods remain available.
    def add_site(self, start_url, max_pages=10):
        return self.add_website_source(start_url, max_pages)

    def sites(self):
        return self.website_source_rows()

    def delete_site(self, site_id):
        return self.remove_website_source(site_id)

    def update_website_source(self, site_id, status, error=None, page_count=None, success=False):
        if status not in ("pending", "syncing", "ready", "error"):
            raise ValueError("Invalid website source status")
        with self.connect(vector=False) as conn:
            result = conn.execute(
                """update python_rag.website_sources set status=%s,last_error=%s,
                page_count=coalesce(%s,page_count),last_success=case when %s then now() else last_success end,
                updated_at=now() where id=%s""",
                (status, error[:500] if error else None, page_count, success, site_id),
            )
            if not result.rowcount:
                raise RagError("The selected website source was not found.")

    def remove_website_source(self, site_id):
        with self.connect(vector=False) as conn, conn.transaction():
            generation = self._active_id(conn)
            removed = conn.execute(
                """delete from python_rag.generation_documents
                where generation_id=%s and source_kind='website' and source_group=%s""",
                (generation, site_id),
            ).rowcount
            source = conn.execute("delete from python_rag.website_sources where id=%s", (site_id,)).rowcount
            if not source:
                raise RagError("The selected website source was not found.")
            if removed:
                self._refresh_generation_counts(conn, generation)
                conn.execute("update python_rag.library set revision=revision+1 where id")

    def replace_site(self, site_id, prepared):
        """Atomically replace every page for one site after crawl and embedding complete."""
        if not prepared:
            raise RagError("The website produced no searchable pages. Its previous version was kept.")
        for file, chunks, vectors in prepared:
            if (
                getattr(file, "source_kind", None) != "website"
                or getattr(file, "source_group", None) != site_id
                or not chunks
                or len(chunks) != len(vectors)
            ):
                raise RagError("A website page did not finish processing. Its previous version was kept.")
        with self.connect() as conn, conn.transaction():
            generation = self._active_id(conn)
            source = conn.execute(
                "select id from python_rag.website_sources where id=%s for update", (site_id,)
            ).fetchone()
            if not source:
                raise RagError("The selected website source was not found.")
            dimensions = conn.execute(
                "select embedding_dimensions from python_rag.index_generations where id=%s", (generation,)
            ).fetchone()["embedding_dimensions"]
            if any(len(vector) != dimensions for _, _, vectors in prepared for vector in vectors):
                raise RagError(
                    f"The embedding model returned vectors that do not match this index ({dimensions} values required)."
                )
            conn.execute(
                """delete from python_rag.generation_documents
                where generation_id=%s and source_kind='website' and source_group=%s""",
                (generation, site_id),
            )
            for file, chunks, vectors in prepared:
                conn.execute(
                    """insert into python_rag.generation_documents
                    (generation_id,id,name,version,mime_type,url,source_kind,source_group)
                    values(%s,%s,%s,%s,%s,%s,'website',%s)""",
                    (generation, file.id, file.name, file.version, file.mime_type, file.url, site_id),
                )
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """insert into python_rag.generation_chunks
                        (generation_id,file_id,position,content,metadata,embedding)
                        values(%s,%s,%s,%s,%s,%s)""",
                        [
                            (
                                generation,
                                file.id,
                                i,
                                chunk.text,
                                Jsonb(chunk.metadata),
                                np.asarray(vector, dtype=np.float32),
                            )
                            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
                        ],
                    )
            self._refresh_generation_counts(conn, generation)
            conn.execute("update python_rag.library set revision=revision+1 where id")
            conn.execute(
                """update python_rag.website_sources set status='ready',page_count=%s,
                last_success=now(),last_error=null,updated_at=now() where id=%s""",
                (len(prepared), site_id),
            )

    def stage_site_generation(self, generation, site_id, prepared):
        """Atomically stage a complete site in a pending generation without changing chat."""
        if not prepared:
            raise RagError("The website produced no searchable pages. The working index was kept.")
        for file, chunks, vectors in prepared:
            if (
                getattr(file, "source_kind", None) != "website"
                or getattr(file, "source_group", None) != site_id
                or not chunks
                or len(chunks) != len(vectors)
            ):
                raise RagError("A website page did not finish processing. The working index was kept.")
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                """select embedding_dimensions,status from python_rag.index_generations
                where id=%s for update""",
                (generation,),
            ).fetchone()
            if not row or row["status"] != "building":
                raise RagError("This rebuild is no longer accepting website pages.")
            if any(len(vector) != row["embedding_dimensions"] for _, _, vectors in prepared for vector in vectors):
                raise RagError("The embedding dimensions do not match the pending index.")
            if not conn.execute("select id from python_rag.website_sources where id=%s", (site_id,)).fetchone():
                raise RagError("The selected website source was not found.")
            conn.execute(
                """delete from python_rag.generation_documents
                where generation_id=%s and source_kind='website' and source_group=%s""",
                (generation, site_id),
            )
            for file, chunks, vectors in prepared:
                conn.execute(
                    """insert into python_rag.generation_documents
                    (generation_id,id,name,version,mime_type,url,source_kind,source_group)
                    values(%s,%s,%s,%s,%s,%s,'website',%s)""",
                    (generation, file.id, file.name, file.version, file.mime_type, file.url, site_id),
                )
                with conn.cursor() as cursor:
                    cursor.executemany(
                        """insert into python_rag.generation_chunks
                        (generation_id,file_id,position,content,metadata,embedding)
                        values(%s,%s,%s,%s,%s,%s)""",
                        [
                            (
                                generation,
                                file.id,
                                i,
                                chunk.text,
                                Jsonb(chunk.metadata),
                                np.asarray(vector, dtype=np.float32),
                            )
                            for i, (chunk, vector) in enumerate(zip(chunks, vectors))
                        ],
                    )
            self._refresh_generation_counts(conn, generation)

    def reconcile_generation(self, generation, expected_ids):
        """Remove stale staged rows only after callers have a complete source snapshot."""
        with self.connect(vector=False) as conn, conn.transaction():
            row = conn.execute(
                "select status from python_rag.index_generations where id=%s for update", (generation,)
            ).fetchone()
            if not row or row["status"] != "building":
                raise RagError("This rebuild is no longer accepting reconciliation.")
            conn.execute(
                """delete from python_rag.generation_documents
                where generation_id=%s and not(id=any(%s::text[]))""",
                (generation, list(expected_ids)),
            )
            self._refresh_generation_counts(conn, generation)

    def set_status(self, status, message, skipped=None, success=False):
        with self.connect(vector=False) as conn:
            conn.execute(
                """update python_rag.sync_status set status=%s,message=%s,updated_at=now(),
                skipped=coalesce(%s,skipped),last_success=case when %s then now() else last_success end where id""",
                (status, message, Jsonb(skipped) if skipped is not None else None, success),
            )

    def status(self):
        with self.connect(vector=False) as conn:
            return conn.execute("select * from python_rag.sync_status where id").fetchone()

    def search_current(self, vector, settings):
        return self.search(vector, expected_pipeline=pipeline_id(settings))

    def search(self, vector, top_k=None, threshold=None, file_ids=None, expected_pipeline=None):
        with self.connect() as conn, conn.transaction():
            # A consistent snapshot of both evidence and its revision.
            conn.execute("set transaction isolation level repeatable read")
            revision = conn.execute("select revision from python_rag.library where id").fetchone()
            generation = self._active_id(conn)
            config = conn.execute(
                "select embedding_dimensions,pipeline_id from python_rag.index_generations where id=%s", (generation,)
            ).fetchone()
            if expected_pipeline is not None and config["pipeline_id"] != expected_pipeline:
                raise RagError("The active embedding index changed. Reload Settings before asking again.")
            if len(vector) != config["embedding_dimensions"]:
                raise RagError(
                    "The selected embedding model is incompatible with the active index. Rebuild the library before chatting."
                )
            limit = max(1, min(int(top_k or self.settings.top_k or TOP_K), 20))
            filters = list(file_ids or [])
            rows = conn.execute(
                """select d.id as file_id,d.name as file_name,d.version,d.url,c.content as text,c.metadata,
                1-(c.embedding <=> %s) as score from python_rag.generation_chunks c
                join python_rag.generation_documents d on d.generation_id=c.generation_id and d.id=c.file_id
                where c.generation_id=%s and (cardinality(%s::text[])=0 or d.id=any(%s::text[]))
                and (%s::real is null or 1-(c.embedding <=> %s) >= %s)
                order by c.embedding <=> %s limit %s""",
                (
                    np.asarray(vector, dtype=np.float32),
                    generation,
                    filters,
                    filters,
                    threshold,
                    np.asarray(vector, dtype=np.float32),
                    threshold,
                    np.asarray(vector, dtype=np.float32),
                    limit,
                ),
            ).fetchall()
            return [
                Source(number=i + 1, page=r.pop("metadata").get("page"), **r) for i, r in enumerate(rows)
            ], revision["revision"] if revision else 0

    def _active_id(self, conn):
        row = conn.execute("select id from python_rag.index_generations where status='active'").fetchone()
        if not row:
            raise RagError("No active search index exists. Open Settings and build the library index.")
        return row["id"]

    def active_generation(self):
        with self.connect(vector=False) as conn:
            return conn.execute("select * from python_rag.index_generations where status='active'").fetchone()

    def generations(self):
        with self.connect(vector=False) as conn:
            return conn.execute("select * from python_rag.index_generations order by created_at desc").fetchall()

    def resumable_generation(self, pipeline):
        with self.connect() as conn:
            return conn.execute(
                "select * from python_rag.index_generations where status='building' and pipeline_id=%s order by created_at desc limit 1",
                (pipeline,),
            ).fetchone()

    def generation_versions(self, generation):
        with self.connect() as conn:
            return {
                row["id"]: row["version"]
                for row in conn.execute(
                    "select id,version from python_rag.generation_documents where generation_id=%s", (generation,)
                )
            }

    def create_generation(
        self, pipeline_id, embedding_provider, embedding_model, dimensions, chunk_size, chunk_overlap
    ):
        generation = str(uuid4())
        with self.connect() as conn:
            conn.execute(
                """insert into python_rag.index_generations
                (id,pipeline_id,embedding_provider,embedding_model,embedding_dimensions,chunk_size,chunk_overlap,status)
                values(%s,%s,%s,%s,%s,%s,%s,'building')""",
                (generation, pipeline_id, embedding_provider, embedding_model, dimensions, chunk_size, chunk_overlap),
            )
        return generation

    def stage_document(self, generation, file, chunks, vectors):
        if not chunks or len(chunks) != len(vectors):
            raise RagError("The document did not finish processing.")
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                "select embedding_dimensions,status from python_rag.index_generations where id=%s for update",
                (generation,),
            ).fetchone()
            if not row or row["status"] != "building":
                raise RagError("This rebuild is no longer accepting documents.")
            if any(len(v) != row["embedding_dimensions"] for v in vectors):
                raise RagError("The embedding dimensions do not match the pending index.")
            conn.execute(
                """insert into python_rag.generation_documents
                (generation_id,id,name,version,mime_type,url,source_kind,source_group)
                values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(generation_id,id) do update set
                name=excluded.name,version=excluded.version,mime_type=excluded.mime_type,url=excluded.url,
                source_kind=excluded.source_kind,source_group=excluded.source_group,indexed_at=now(),error=null""",
                (
                    generation,
                    file.id,
                    file.name,
                    file.version,
                    file.mime_type,
                    file.url,
                    getattr(file, "source_kind", "drive"),
                    getattr(file, "source_group", None),
                ),
            )
            conn.execute(
                "delete from python_rag.generation_chunks where generation_id=%s and file_id=%s", (generation, file.id)
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """insert into python_rag.generation_chunks
                    (generation_id,file_id,position,content,metadata,embedding) values(%s,%s,%s,%s,%s,%s)""",
                    [
                        (generation, file.id, i, c.text, Jsonb(c.metadata), np.asarray(v, dtype=np.float32))
                        for i, (c, v) in enumerate(zip(chunks, vectors))
                    ],
                )
            self._refresh_generation_counts(conn, generation)

    def activate_generation(self, generation, expected_files):
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                "select * from python_rag.index_generations where id=%s for update", (generation,)
            ).fetchone()
            if not row or row["status"] != "building":
                raise RagError("The pending index cannot be activated.")
            stored = {
                r["id"]: r["version"]
                for r in conn.execute(
                    "select id,version from python_rag.generation_documents where generation_id=%s", (generation,)
                )
            }
            if stored != dict(expected_files):
                raise RagError(
                    "The rebuilt index does not match the complete current source snapshot. The working index was kept."
                )
            conn.execute("update python_rag.index_generations set status='previous' where status='active'")
            conn.execute(
                "update python_rag.index_generations set status='active',activated_at=now(),completed_at=now(),error=null where id=%s",
                (generation,),
            )
            conn.execute(
                "update python_rag.library set pipeline_id=%s,revision=revision+1 where id", (row["pipeline_id"],)
            )

    def finish_generation(self, generation, status, error=None):
        if status not in ("failed", "cancelled"):
            raise ValueError("Invalid final generation state")
        with self.connect() as conn:
            conn.execute(
                "update python_rag.index_generations set status=%s,error=%s,completed_at=now() where id=%s and status='building'",
                (status, error, generation),
            )

    def generation_error(self, generation, error):
        with self.connect() as conn:
            conn.execute(
                "update python_rag.index_generations set error=%s where id=%s and status='building'",
                (error[:500], generation),
            )

    def rollback_generation(self, generation, expected_files):
        """Reactivate the retained previous index only if it still matches Drive."""
        with self.connect() as conn, conn.transaction():
            row = conn.execute(
                "select * from python_rag.index_generations where id=%s and status='previous' for update", (generation,)
            ).fetchone()
            if not row:
                raise RagError("The recovery index is no longer available.")
            stored = {
                item["id"]: item["version"]
                for item in conn.execute(
                    "select id,version from python_rag.generation_documents where generation_id=%s", (generation,)
                )
            }
            if stored != dict(expected_files):
                raise RagError(
                    "The recovery index does not match the current source library. Rebuild it before activation."
                )
            conn.execute("update python_rag.index_generations set status='previous' where status='active'")
            conn.execute(
                "update python_rag.index_generations set status='active',activated_at=now(),error=null where id=%s",
                (generation,),
            )
            conn.execute(
                "update python_rag.library set pipeline_id=%s,revision=revision+1 where id", (row["pipeline_id"],)
            )

    def prune_generations(self):
        with self.connect() as conn:
            conn.execute("""delete from python_rag.index_generations where id in (
                select id from python_rag.index_generations where status in ('previous','failed','cancelled')
                order by created_at desc offset 1)""")

    def _refresh_generation_counts(self, conn, generation):
        conn.execute(
            """update python_rag.index_generations set
            document_count=(select count(*) from python_rag.generation_documents where generation_id=%s),
            chunk_count=(select count(*) from python_rag.generation_chunks where generation_id=%s)
            where id=%s""",
            (generation, generation, generation),
        )

    def exclusions(self):
        with self.connect(vector=False) as conn:
            return {
                r["file_id"]: r["name"] for r in conn.execute("select file_id,name from python_rag.document_exclusions")
            }

    def set_excluded(self, file_id, name, excluded=True):
        with self.connect(vector=False) as conn, conn.transaction():
            if excluded:
                conn.execute(
                    "insert into python_rag.document_exclusions(file_id,name) values(%s,%s) on conflict(file_id) do update set name=excluded.name,excluded_at=now()",
                    (file_id, name),
                )
                generation = self._active_id(conn)
                conn.execute(
                    "delete from python_rag.generation_documents where generation_id=%s and id=%s",
                    (generation, file_id),
                )
                self._refresh_generation_counts(conn, generation)
                conn.execute("update python_rag.library set revision=revision+1 where id")
            else:
                conn.execute("delete from python_rag.document_exclusions where file_id=%s", (file_id,))

    def log_activity(
        self, job_id, kind, stage, status, message="", document_id=None, document_name=None, duration_ms=None
    ):
        with self.connect(vector=False) as conn:
            conn.execute(
                """insert into python_rag.activity(id,job_id,kind,stage,status,message,document_id,document_name,duration_ms)
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (str(uuid4()), job_id, kind, stage, status, message[:500], document_id, document_name, duration_ms),
            )

    def activity(self, limit=100):
        with self.connect(vector=False) as conn:
            return conn.execute(
                "select * from python_rag.activity order by created_at desc limit %s", (max(1, min(limit, 500)),)
            ).fetchall()

    def purge_activity(self, days=30):
        with self.connect(vector=False) as conn:
            return conn.execute(
                "delete from python_rag.activity where created_at < now()-(%s * interval '1 day')",
                (max(1, min(days, 365)),),
            ).rowcount

    def revision(self):
        with self.connect(vector=False) as conn:
            row = conn.execute("select revision from python_rag.library where id").fetchone()
            return row["revision"] if row else 0

    def new_session(self):
        session = str(uuid4())
        with self.connect(vector=False) as conn:
            conn.execute("insert into python_rag.sessions(id) values(%s)", (session,))
        return session

    def ensure_session(self, session):
        """Create a caller-provided UUID session without mixing visitor histories."""
        with self.connect(vector=False) as conn:
            try:
                conn.execute("insert into python_rag.sessions(id) values(%s) on conflict do nothing", (session,))
            except psycopg.errors.InvalidTextRepresentation:
                raise RagError("The conversation ID is invalid. Start a new chat and try again.") from None

    def sessions(self):
        with self.connect(vector=False) as conn:
            return conn.execute("select id,title from python_rag.sessions order by created_at desc limit 50").fetchall()

    def history(self, session, limit=None):
        with self.connect(vector=False) as conn:
            if limit:
                rows = conn.execute(
                    """select question,answer,sources from python_rag.turns where session_id=%s
                    order by created_at desc limit %s""",
                    (session, max(1, min(limit, 50))),
                ).fetchall()
                return list(reversed(rows))
            return conn.execute(
                "select question,answer,sources from python_rag.turns where session_id=%s order by created_at",
                (session,),
            ).fetchall()

    def save_turn(self, session, turn_id, question, answer, revision):
        with self.connect(vector=False) as conn, conn.transaction():
            # Lock publication while recording the answer, so evidence isn't silently superseded.
            row = conn.execute("select revision from python_rag.library where id for share").fetchone()
            if (row["revision"] if row else 0) != revision:
                raise RagError(
                    "Your documents changed while the answer was being written. Please ask again for the latest information."
                )
            conn.execute(
                "insert into python_rag.turns(id,session_id,question,answer,sources) values(%s,%s,%s,%s,%s) on conflict(id) do nothing",
                (turn_id, session, question, answer.text, Jsonb([s.model_dump() for s in answer.sources])),
            )
            conn.execute(
                "update python_rag.sessions set title=%s where id=%s and title='New chat'", (question[:60], session)
            )
