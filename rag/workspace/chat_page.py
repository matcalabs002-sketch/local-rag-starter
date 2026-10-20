from uuid import uuid4
from urllib.parse import urlparse
import streamlit as st

from ..chat import Chat
from ..config import RagError
from ..models import Models
from ..ui import literal_label


def show_sources(sources):
    if not sources:
        return
    with st.expander(f"{len(sources)} supporting passage(s)"):
        for source in sources:
            data = source.model_dump() if hasattr(source, "model_dump") else source
            st.markdown(f"**[{data['number']}] {literal_label(data['file_name'])}**")
            if data.get("page"):
                st.caption(f"Page {data['page']}")
            st.text(data["text"])
            url = data.get("url", "")
            if urlparse(url).scheme == "https" and urlparse(url).hostname:
                st.link_button("Open source", url)


def retry_question(question):
    st.session_state["retry_question"] = question


def request_new_chat():
    st.session_state["new_chat_requested"] = True


def render_chat(store, settings, ready):
    st.title("Chat")
    st.caption("Your documents, in conversation. Every factual answer links back to its evidence.")
    if not ready:
        st.info("Start with Settings to initialize your local library. Then upload a document in Sources.")
        return
    store.assert_pipeline(settings)
    if st.session_state.pop("new_chat_requested", False):
        st.session_state["conversation"] = store.new_session()
    sessions = store.sessions()
    if not sessions:
        store.new_session()
        sessions = store.sessions()
    ids = [str(row["id"]) for row in sessions]
    titles = {str(row["id"]): row["title"] for row in sessions}
    if st.session_state.get("conversation") not in ids:
        st.session_state["conversation"] = ids[0]
    with st.container(key="chat_toolbar"):
        left, right = st.columns([4, 1], vertical_alignment="bottom")
        session = left.selectbox(
            "Conversation",
            ids,
            format_func=titles.get,
            key="conversation",
            persist_state="session",
            label_visibility="collapsed",
        )
        right.button("New chat", width="stretch", icon=":material/add:", on_click=request_new_chat)
    history = store.history(session, limit=30)
    if not store.counts()["chunks"]:
        st.info("Your library is empty. Upload the fictional sample handbook in Sources to try your first answer.")
        return
    if not history:
        st.caption(
            "Try a specific question about a document. Answers use current evidence; missing facts stay missing."
        )
    for row in history:
        with st.chat_message("user", avatar=":material/person:"):
            st.text(row["question"])
        with st.chat_message("assistant", avatar=":material/description:"):
            st.text(row["answer"])
            show_sources(row["sources"])
    retry = st.session_state.pop("retry_question", None)
    question = st.chat_input("Ask a question about your library", max_chars=3000) or retry
    if question:
        st.session_state["last_question"] = question
        with st.chat_message("user", avatar=":material/person:"):
            st.text(question)
        with st.chat_message("assistant", avatar=":material/description:"):
            try:
                models = Models(settings)
                with st.status("Preparing your answer…", expanded=True) as progress:
                    chat = Chat(store, models, on_stage=lambda stage: progress.update(label=stage))
                    answer = chat.answer(session, question, str(uuid4()))
                    progress.update(label="Answer saved · sources checked", state="complete", expanded=False)
                st.text(answer.text)
                show_sources(answer.sources)
            except RagError as error:
                progress.update(label="Answer could not finish", state="error") if "progress" in locals() else None
                st.error(str(error))
                st.button("Try again", key="retry_failed", on_click=retry_question, args=(question,))
    elif history and st.button("Ask again", key="retry_last"):
        st.session_state["retry_question"] = history[-1]["question"]
        st.rerun()
