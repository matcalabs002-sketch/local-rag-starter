import streamlit as st

from ..config import RagError
from ..models import Models
from ..ui import literal_label
from ..uploads import UploadService
from ..websites import WebsiteSyncEngine


def render_sources(store, settings, ready, runtime=None):
    st.title("Sources")
    st.caption("The knowledge behind your answers. Add documents and keep your library up to date.")
    if not ready:
        st.info("Initialize the database in Settings before adding sources.")
        return
    counts = store.counts()
    a, b = st.columns(2)
    a.metric("Documents", counts["documents"])
    b.metric("Passages", counts["chunks"])
    with st.form("uploads", clear_on_submit=False):
        st.subheader("Upload documents")
        files = st.file_uploader(
            "Text PDF, DOCX, TXT, Markdown, or CSV",
            type=["pdf", "docx", "txt", "md", "csv"],
            accept_multiple_files=True,
            max_upload_size=settings.max_file_bytes // (1024 * 1024) or 1,
        )
        replace_existing = st.checkbox("Replace existing uploads with the same name")
        submitted = st.form_submit_button("Index documents", type="primary")
    if submitted:
        if not files:
            st.warning("Choose at least one document to index.")
        else:
            service = UploadService(store, Models(settings), settings)
            for file in files:
                try:
                    with st.spinner("Indexing " + file.name + "…"):
                        result = service.add(file.name, file.getvalue(), replace_existing)
                    st.success(file.name + " · " + result)
                except RagError as error:
                    st.error(file.name + ": " + str(error))
            st.caption("Refresh the source list below to see the latest counts.")
    if st.button("Refresh source list"):
        st.rerun()
    documents = store.documents()
    st.subheader("Searchable library")
    if not documents:
        st.caption("No documents yet. Start with samples/welcome-handbook.txt.")
    for row in documents:
        with st.expander(literal_label(row["name"])):
            st.caption(f"{row.get('source_kind', 'drive').title()} · {row.get('chunk_count', 0)} passages")
            if row.get("source_kind") == "local":
                confirmed = st.checkbox("Remove this upload and its indexed passages", key="remove_" + row["id"])
                if st.button("Remove document", key="delete_" + row["id"], disabled=not confirmed):
                    UploadService(store, Models(settings), settings).remove(row["id"])
                    st.rerun()
    with st.expander("Optional sources · websites and Google Drive"):
        st.caption("These connectors make external requests only after you configure them. Uploads work independently.")
        with st.form("website"):
            url = st.text_input("Public HTTPS website", placeholder="https://example.com/docs")
            limit = st.number_input("Maximum pages", min_value=1, max_value=50, value=5)
            if st.form_submit_button("Add website"):
                with store.sync_lock() as locked:
                    locked.assert_pipeline(settings)
                    site = locked.add_website_source(url, int(limit))
                    with st.spinner("Importing website…"):
                        WebsiteSyncEngine(locked, Models(settings)).run(str(site))
                st.rerun()
        for site in store.website_source_rows():
            st.text(site["start_url"])
            st.caption(f"{site['status']} · {site['page_count']} pages")
            if site.get("last_error"):
                st.error(site["last_error"])
            left, right = st.columns(2)
            if left.button("Refresh website", key="refresh_" + str(site["id"])):
                with store.sync_lock() as locked:
                    WebsiteSyncEngine(locked, Models(settings)).run(str(site["id"]))
                st.rerun()
            if right.button("Remove website", key="remove_site_" + str(site["id"])):
                with store.sync_lock() as locked:
                    locked.remove_website_source(str(site["id"]))
                st.rerun()
        if settings.folder_id:
            st.caption(
                "Drive folder configured. Remote sources refresh on the configured schedule while the app is open."
            )
            if st.button("Refresh Drive now"):
                if runtime:
                    runtime.request_sync()
                    st.info("Refresh requested. Check recent activity below.")
                else:
                    st.warning("The background worker needs ready database and model connections. Check Settings.")
        else:
            st.caption("To enable Drive, install the drive extra, set DRIVE_FOLDER_ID, and connect Google in Settings.")
    with st.expander("Recent activity", expanded=bool(runtime and runtime.error)):
        if runtime and runtime.error:
            st.error(runtime.error)
        activity = store.activity(limit=30)
        if activity:
            st.dataframe(
                [{k: row[k] for k in ("created_at", "kind", "stage", "status", "message")} for row in activity],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("Indexing and refresh events will appear here.")
