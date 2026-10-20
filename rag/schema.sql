-- Local/private starter library. Existing n8n tables are never modified.
begin;
select pg_advisory_xact_lock(731426019);
create schema if not exists extensions;
create extension if not exists vector with schema extensions;
create schema if not exists python_rag;
revoke all on schema python_rag from public;
set local search_path=python_rag,public,extensions;
create table if not exists python_rag.library (
  id boolean primary key default true check(id), folder_id text not null,
  pipeline_id text not null, revision bigint not null default 0
);
create table if not exists python_rag.documents (
  id text primary key, name text not null, version text not null, mime_type text not null,
  url text not null, indexed_at timestamptz not null default now()
);
create table if not exists python_rag.chunks (
  id bigint generated always as identity primary key,
  file_id text not null references python_rag.documents(id) on delete cascade,
  position integer not null, content text not null check(length(btrim(content))>0),
  metadata jsonb not null, embedding vector(768) not null,
  unique(file_id,position)
);
create table if not exists python_rag.sessions (
  id uuid primary key, title text not null default 'New chat', created_at timestamptz not null default now()
);
create table if not exists python_rag.turns (
  id uuid primary key, session_id uuid not null references python_rag.sessions(id) on delete cascade,
  question text not null, answer text not null, sources jsonb not null default '[]',
  created_at timestamptz not null default now()
);
create index if not exists python_rag_turn_session on python_rag.turns(session_id,created_at);
create table if not exists python_rag.sync_status (
  id boolean primary key default true check(id), status text not null default 'idle',
  message text not null default 'Waiting for first sync', updated_at timestamptz not null default now(),
  last_success timestamptz, skipped jsonb not null default '[]'
);
insert into python_rag.sync_status(id) values(true) on conflict do nothing;

-- Versioned indexes let a replacement build finish before it becomes searchable.
create table if not exists python_rag.index_generations (
  id uuid primary key,
  pipeline_id text not null,
  embedding_provider text not null,
  embedding_model text not null,
  embedding_dimensions integer not null check(embedding_dimensions between 1 and 8192),
  chunk_size integer not null check(chunk_size between 200 and 4000),
  chunk_overlap integer not null check(chunk_overlap >= 0 and chunk_overlap < chunk_size),
  status text not null check(status in ('building','active','previous','failed','cancelled')),
  document_count integer not null default 0,
  chunk_count integer not null default 0,
  error text,
  created_at timestamptz not null default now(),
  activated_at timestamptz,
  completed_at timestamptz
);
create unique index if not exists python_rag_one_active_generation
  on python_rag.index_generations ((status)) where status='active';

create table if not exists python_rag.generation_documents (
  generation_id uuid not null references python_rag.index_generations(id) on delete cascade,
  id text not null,
  name text not null,
  version text not null,
  mime_type text not null,
  url text not null,
  source_kind text not null default 'drive' check(source_kind in ('drive','website','local')),
  source_group text,
  indexed_at timestamptz not null default now(),
  error text,
  primary key(generation_id,id),
  check((source_kind in ('drive','local') and source_group is null) or
        (source_kind='website' and source_group is not null))
);
alter table python_rag.generation_documents add column if not exists source_kind text not null default 'drive';
alter table python_rag.generation_documents add column if not exists source_group text;
-- Replace the two legacy anonymous source checks without dropping user data.
do $$ declare constraint_name text; begin
  for constraint_name in select conname from pg_constraint
    where conrelid='python_rag.generation_documents'::regclass and contype='c'
      and pg_get_constraintdef(oid) like '%source_kind%'
  loop execute format('alter table python_rag.generation_documents drop constraint %I', constraint_name); end loop;
end $$;
alter table python_rag.generation_documents add constraint source_identity_check check (
  (source_kind in ('drive','local') and source_group is null) or
  (source_kind='website' and source_group is not null));
create table if not exists python_rag.uploaded_documents (
  id text primary key,
  library_id boolean not null default true references python_rag.library(id) on delete cascade,
  name text not null unique,
  version text not null check(version ~ '^[a-f0-9]{64}$'),
  mime_type text not null,
  size bigint not null check(size > 0),
  created_at timestamptz not null default now()
);
alter table python_rag.uploaded_documents enable row level security;
create index if not exists python_rag_generation_document_source
  on python_rag.generation_documents(generation_id,source_kind,source_group);
create table if not exists python_rag.generation_chunks (
  id bigint generated always as identity primary key,
  generation_id uuid not null references python_rag.index_generations(id) on delete cascade,
  file_id text not null,
  position integer not null,
  content text not null check(length(btrim(content))>0),
  metadata jsonb not null,
  embedding vector not null,
  unique(generation_id,file_id,position),
  foreign key(generation_id,file_id) references python_rag.generation_documents(generation_id,id) on delete cascade
);

create table if not exists python_rag.document_exclusions (
  file_id text primary key,
  name text not null,
  excluded_at timestamptz not null default now()
);

create table if not exists python_rag.website_sources (
  id uuid primary key,
  start_url text not null unique,
  max_pages integer not null default 10 check(max_pages between 1 and 50),
  enabled boolean not null default true,
  status text not null default 'pending' check(status in ('pending','syncing','ready','error')),
  page_count integer not null default 0,
  last_success timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists python_rag.activity (
  id uuid primary key,
  job_id uuid not null,
  kind text not null,
  stage text not null,
  status text not null check(status in ('pending','running','success','error','cancelled')),
  document_id text,
  document_name text,
  message text not null default '',
  duration_ms integer,
  created_at timestamptz not null default now()
);
create index if not exists python_rag_activity_recent on python_rag.activity(created_at desc);

-- Preserve an existing working index as the first active generation.
do $$
declare migrated_id uuid;
begin
  if not exists(select 1 from python_rag.index_generations) then
    migrated_id := gen_random_uuid();
    insert into python_rag.index_generations(
      id,pipeline_id,embedding_provider,embedding_model,embedding_dimensions,
      chunk_size,chunk_overlap,status,document_count,chunk_count,activated_at,completed_at
    ) select migrated_id,coalesce((select pipeline_id from python_rag.library where id),'nomic-embed-text:v1.5|768|1000|150|v1'),
      'ollama','nomic-embed-text:v1.5',768,1000,150,'active',
      (select count(*) from python_rag.documents),(select count(*) from python_rag.chunks),now(),now();
    insert into python_rag.generation_documents(generation_id,id,name,version,mime_type,url,indexed_at)
      select migrated_id,id,name,version,mime_type,url,indexed_at from python_rag.documents;
    insert into python_rag.generation_chunks(generation_id,file_id,position,content,metadata,embedding)
      select migrated_id,file_id,position,content,metadata,embedding from python_rag.chunks;
  end if;
end $$;

alter table python_rag.library enable row level security;
alter table python_rag.documents enable row level security;
alter table python_rag.chunks enable row level security;
alter table python_rag.sessions enable row level security;
alter table python_rag.turns enable row level security;
alter table python_rag.sync_status enable row level security;
alter table python_rag.index_generations enable row level security;
alter table python_rag.generation_documents enable row level security;
alter table python_rag.generation_chunks enable row level security;
alter table python_rag.document_exclusions enable row level security;
alter table python_rag.website_sources enable row level security;
alter table python_rag.activity enable row level security;
commit;
