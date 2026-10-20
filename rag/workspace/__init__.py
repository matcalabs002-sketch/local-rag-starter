"""A focused three-page local workspace."""

from pathlib import Path

import streamlit as st

from ..config import Settings, RagError
from ..models import Models
from ..store import Store

PAGES = ("Chat", "Sources", "Settings")


@st.cache_data(ttl=10, show_spinner=False)
def service_status(settings):
    result = {}
    for name, operation in [("Database", lambda: Store(settings).ready()), ("AI", lambda: Models(settings).health())]:
        try:
            operation()
            result[name] = (
                True,
                "Ready"
                if name != "AI" or settings.chat_provider == settings.embedding_provider == "ollama"
                else "Local components checked; selected cloud adapters are configured but not live-verified.",
            )
        except RagError as error:
            result[name] = (False, str(error))
        except Exception:
            result[name] = (False, f"{name} could not be checked. Review Settings.")
    return result


@st.cache_resource
def runtime_holder():
    return {"runtime": None}


def main():
    st.set_page_config(page_title="Local RAG Starter · Free Starter Kit", page_icon="◌", layout="centered")
    st.markdown("<style>" + Path(__file__).with_name("style.css").read_text() + "</style>", unsafe_allow_html=True)
    try:
        settings = Settings.load()
    except RagError as error:
        st.title("Check your configuration.")
        st.error(str(error))
        st.info("Correct .env and reload this page. See README.md for every setting.")
        return
    status = service_status(settings)
    store = Store(settings)
    ready = status["Database"][0]
    holder = runtime_holder()
    old = holder["runtime"]
    if old and old.settings != settings:
        old.stop()
        holder["runtime"] = None
    # Remote connectors are optional. Local uploads never wait for Google sign-in.
    if ready and status["AI"][0] and holder["runtime"] is None:
        try:
            if settings.folder_id or store.website_sources(enabled_only=True):
                from ..runtime import Runtime

                holder["runtime"] = Runtime(settings)
                holder["runtime"].start()
        except RagError as error:
            st.warning(str(error))
    from .presentation import render_brand, render_service_footer

    with st.sidebar:
        render_brand()
        st.markdown('<div class="sidebar-label">Workspace</div>', unsafe_allow_html=True)
        page = st.radio("Workspace", PAGES, key="workspace_page", label_visibility="collapsed")
        render_service_footer(status, settings.chat_provider == settings.embedding_provider == "ollama")
    from .chat_page import render_chat
    from .sources_page import render_sources
    from .settings_page import render_settings

    try:
        if page == "Chat":
            render_chat(store, settings, ready)
        elif page == "Sources":
            render_sources(store, settings, ready, holder["runtime"])
        else:
            render_settings(store, settings, status)
    except RagError as error:
        st.error(str(error))
    except Exception as error:
        import logging

        logging.getLogger(__name__).error("Workspace request failed (%s).", type(error).__name__)
        st.error("This action could not finish. Check Settings and service availability, then retry.")
