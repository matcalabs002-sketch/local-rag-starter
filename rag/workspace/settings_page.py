from dataclasses import replace
import streamlit as st

from ..config import RagError, save_settings
from ..models import Models
from ..reindex import ReindexEngine
from ..sources import rebuild_sources
from ..ui import provider_catalog, provider_models


def generation_settings(row):
    return {
        "EMBEDDING_PROVIDER": row["embedding_provider"],
        "EMBEDDING_MODEL": row["embedding_model"],
        "EMBEDDING_DIMENSIONS": str(row["embedding_dimensions"]),
        "CHUNK_SIZE": str(row["chunk_size"]),
        "CHUNK_OVERLAP": str(row["chunk_overlap"]),
    }


def render_settings(store, settings, status):
    st.title("Settings")
    st.caption("Connections, models, and the way your library works.")
    notice = st.session_state.pop("settings_notice", None)
    if notice:
        st.success(notice)
    from .presentation import render_status_summary

    render_status_summary(status)
    if st.button("Check connections again"):
        from . import service_status

        service_status.clear()
        st.rerun()
    with st.expander("First-run setup", expanded=not status["Database"][0]):
        st.write("From the repository root, after installing the Python dependencies:")
        st.code(
            "python -m rag setup\ndocker compose up -d --wait\npython -m rag init\npython -m rag check", language="bash"
        )
        st.caption(
            "setup creates .env only when absent. init creates the library schema in the configured database. It does not download models or contact Google."
        )
        st.write(
            "Start Ollama separately, then pull the two default models. See README.md for Windows commands and custom ports."
        )
        st.code("OLLAMA_HOST=127.0.0.1:11435 ollama serve", language="bash")
        st.code(
            "OLLAMA_HOST=127.0.0.1:11435 ollama pull qwen3:4b\nOLLAMA_HOST=127.0.0.1:11435 ollama pull nomic-embed-text:v1.5",
            language="bash",
        )
    with st.expander("Connection settings"):
        st.write(
            "Edit .env to configure DATABASE_URL, OLLAMA_URL, private storage, or optional API keys. Environment variables override .env. Credentials are never displayed here."
        )
        st.caption(
            "Local PostgreSQL runs on loopback. Supabase uses its Session pooler on port 5432 with verify-full TLS; set SUPABASE_PROJECT_URL and DATABASE_CA_FILE when needed."
        )
        st.caption("The interface is a local, single-user tool. Keep the Streamlit server bound to loopback.")
        if st.button("Initialize configured database schema"):
            settings.validate()
            Models(settings)
            with st.spinner("Initializing schema…"):
                store.initialize()
            from . import service_status

            service_status.clear()
            st.success("Schema initialized. Existing data was preserved. Check connections again.")
    catalog = provider_catalog()
    with st.form("chat_settings"):
        st.subheader("Answer model")
        provider = st.selectbox(
            "Chat provider",
            catalog["chat"],
            index=catalog["chat"].index(settings.chat_provider) if settings.chat_provider in catalog["chat"] else 0,
        )
        # A free-text model name avoids form-dependent dropdowns resetting unsaved selections.
        model = st.text_input("Chat model", value=settings.chat_model)
        st.caption(
            "Supported models: " + "; ".join(p + ": " + ", ".join(provider_models("chat", p)) for p in catalog["chat"])
        )
        st.caption(
            "Cloud providers require an explicitly configured API key and can incur charges. Adapter tests do not establish live provider availability."
        )
        if st.form_submit_button("Save answer model"):
            Models(replace(settings, chat_provider=provider, chat_model=model))
            save_settings({"CHAT_PROVIDER": provider, "CHAT_MODEL": model})
            from . import service_status

            service_status.clear()
            st.rerun()
    if not status["Database"][0]:
        return
    with st.expander("Advanced · rebuild or recover an index"):
        current = store.active_generation()
        st.caption(
            f"Active embeddings: {current['embedding_provider']} / {current['embedding_model']} · {current['embedding_dimensions']} dimensions"
        )
        st.write(
            "A rebuild prepares every current source before switching indexes. The working index remains available if preparation fails."
        )
        confirmed = st.checkbox("Rebuild all sources using these settings; selected paid embeddings may incur charges")
        with st.form("rebuild"):
            provider = st.selectbox("Embedding provider", catalog["embedding"])
            model = st.text_input("Embedding model", value=current["embedding_model"])
            dimensions = st.number_input(
                "Dimensions", min_value=1, max_value=3072, value=current["embedding_dimensions"]
            )
            size = st.number_input("Chunk size", min_value=200, max_value=4000, value=current["chunk_size"])
            overlap = st.number_input("Chunk overlap", min_value=0, max_value=3999, value=current["chunk_overlap"])
            st.caption(
                "Supported embeddings: "
                + "; ".join(p + ": " + ", ".join(provider_models("embedding", p)) for p in catalog["embedding"])
            )
            submitted = st.form_submit_button("Rebuild index", disabled=not confirmed)
        if submitted:
            proposed = replace(
                settings,
                embedding_provider=provider,
                embedding_model=model,
                embedding_dimensions=int(dimensions),
                chunk_size=int(size),
                chunk_overlap=int(overlap),
            )
            proposed.validate()
            models = Models(proposed)
            with st.status("Preparing a replacement index…") as progress:
                ReindexEngine(
                    store,
                    rebuild_sources(store, settings),
                    models,
                    settings.folder_id,
                    chunk_size=proposed.chunk_size,
                    chunk_overlap=proposed.chunk_overlap,
                ).run()
                progress.update(label="Replacement index activated", state="complete")
            active = store.active_generation()
            try:
                save_settings(generation_settings(active))
            except Exception:
                raise RagError(
                    "The replacement index is active, but .env could not be saved. Update embedding and chunk settings in .env to match the active index shown above."
                ) from None
            st.session_state["settings_notice"] = (
                "Index activated and settings saved. Environment overrides must match these settings."
            )
            st.rerun()
        previous = [row for row in store.generations() if row["status"] == "previous"]
        if previous:
            recovery = st.selectbox(
                "Retained index",
                previous,
                format_func=lambda row: str(row["created_at"]) + " · " + row["embedding_model"],
            )
            if st.button("Recover retained index"):
                ReindexEngine(store, rebuild_sources(store, settings), Models(settings), settings.folder_id).rollback(
                    str(recovery["id"])
                )
                try:
                    save_settings(generation_settings(recovery))
                except Exception:
                    raise RagError(
                        "Recovery activated, but .env could not be saved. Set the embedding and chunk settings to the recovered index values."
                    ) from None
                st.session_state["settings_notice"] = (
                    "Recovery activated. Source versions were checked before switching."
                )
                st.rerun()
    with st.expander("Optional · connect Google Drive"):
        st.caption(
            "Install the drive extra and set DRIVE_FOLDER_ID in .env first. This connector reads directly inside one folder; it does not modify Drive files."
        )
        raw = st.file_uploader("Google Desktop OAuth client JSON", type=["json"])
        if st.button("Save Google OAuth client", disabled=raw is None):
            from ..drive import save_client

            save_client(raw.getvalue())
            st.success("OAuth client saved privately.")
        if st.button("Connect Google Drive", disabled=not bool(settings.folder_id)):
            from ..drive import authorize

            authorize()
            st.success("Google connected. Refresh Sources to start sync.")
