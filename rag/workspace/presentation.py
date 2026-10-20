"""Static interface chrome. Never render document text or configuration secrets as HTML."""

from html import escape

import streamlit as st

BRAND = """<div class="sidebar-brand"><span class="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 3h7l4 4v14H7zM14 3v5h4M10 12h5M10 16h5"/><path d="M4 7v14" opacity=".6"/></svg></span><div><div class="brand-name">Local RAG Starter</div><div class="brand-description">Free starter kit</div></div></div>"""


def render_brand():
    st.markdown(BRAND, unsafe_allow_html=True)


def render_service_footer(status, local_models):
    rows = []
    for name, (ready, _) in status.items():
        label = f"{name} {'ready' if ready else 'needs setup'}"
        state = "" if ready else " needs-setup"
        rows.append(
            f'<div class="service-line"><span class="service-dot{state}" aria-hidden="true"></span>{escape(label)}</div>'
        )
    model_note = "Ollama · PostgreSQL" if local_models else "Cloud AI explicitly selected"
    st.markdown(
        '<div class="sidebar-footer">'
        + "".join(rows)
        + "<strong>"
        + model_note
        + "</strong>Single-user workspace</div>",
        unsafe_allow_html=True,
    )


def render_status_summary(status):
    pills = []
    for name, (ready, _) in status.items():
        label = f"{name}: {'ready' if ready else 'needs setup'}"
        pills.append(
            f'<span class="status-pill{"" if ready else " offline"}"><span aria-hidden="true">{"✓" if ready else "!"}</span>{escape(label)}</span>'
        )
    st.markdown('<div class="status-row">' + "".join(pills) + "</div>", unsafe_allow_html=True)
    for _, (ready, message) in status.items():
        if not ready:
            st.warning(message)
        elif message != "Ready":
            st.caption(message)
