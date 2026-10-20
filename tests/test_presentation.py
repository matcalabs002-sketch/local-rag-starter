from rag.workspace.presentation import render_service_footer, render_status_summary


def test_service_chrome_escapes_labels_and_never_exposes_diagnostics(monkeypatch):
    rendered = []
    monkeypatch.setattr("rag.workspace.presentation.st.markdown", lambda body, **kwargs: rendered.append(body))
    render_service_footer({"<script>": (False, "private diagnostic value")}, True)
    assert "&lt;script&gt;" in rendered[0]
    assert "<script>" not in rendered[0] and "private diagnostic value" not in rendered[0]
    assert "needs setup" in rendered[0]


def test_status_summary_preserves_actionable_failures(monkeypatch):
    rendered = []
    warnings = []
    captions = []
    monkeypatch.setattr("rag.workspace.presentation.st.markdown", lambda body, **kwargs: rendered.append(body))
    monkeypatch.setattr("rag.workspace.presentation.st.warning", warnings.append)
    monkeypatch.setattr("rag.workspace.presentation.st.caption", captions.append)
    render_status_summary(
        {"Database": (False, "Initialize your database."), "AI": (True, "Cloud availability unverified.")}
    )
    assert warnings == ["Initialize your database."]
    assert captions == ["Cloud availability unverified."]
    assert "needs setup" in rendered[0] and "AI: ready" in rendered[0]
