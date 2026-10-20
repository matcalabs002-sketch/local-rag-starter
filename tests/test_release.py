from scripts import package_release


def test_release_allowlist_excludes_private_state_and_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, "ROOT", tmp_path)
    for name in [
        "README.md",
        ".env.example",
        ".env",
        "docs/.env",
        ".private/password.txt",
        "rag/config.py",
        "rag/debug.log",
        "rag/__pycache__/secret.py",
        "docs/model.bin",
        "documents/personal.txt",
        "random.txt",
    ]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture")
    (tmp_path / "docs" / "linked.txt").symlink_to(tmp_path / ".env")
    names = {relative.as_posix() for _, relative in package_release.paths()}
    assert names == {"README.md", ".env.example", "rag/config.py"}
