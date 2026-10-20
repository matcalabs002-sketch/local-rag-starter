"""Build a reviewable source archive using a positive allowlist."""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    ".env.example",
    ".gitignore",
    ".gitleaks.toml",
    "app.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-lock.txt",
    "compose.yaml",
    "README.md",
    "TUTORIAL.md",
    "START-HERE.html",
    "build_guide.py",
    "LICENSE",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "VALIDATION.md",
    "PORTFOLIO-CASE-STUDY.md",
    "AGENTS.md",
}
DIRECTORIES = {"rag", "tests", "docs", "samples", "scripts", ".github", ".streamlit"}
EXCLUDED_PARTS = {".venv", ".private", ".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
ALLOWED_SUFFIXES = {".py", ".sql", ".css", ".md", ".json", ".txt", ".toml", ".yml", ".yaml", ".png", ".jpg"}


def paths():
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED_PARTS for part in relative.parts) or path.is_symlink():
            continue
        if not path.is_file():
            continue
        if relative.as_posix() in FILES or (
            relative.parts[0] in DIRECTORIES
            and path.suffix.lower() in ALLOWED_SUFFIXES
            and not path.name.startswith(".env")
            and not path.name.endswith(".log")
        ):
            yield path, relative


def main():
    target = ROOT / "dist" / "local-rag-starter.zip"
    target.parent.mkdir(exist_ok=True)
    names = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, relative in paths():
            name = "local-rag-starter/" + relative.as_posix()
            archive.write(path, name)
            names.append(name)
    print(f"Created {target.name}: {len(names)} source files, {target.stat().st_size:,} bytes. Review before sharing.")


if __name__ == "__main__":
    main()
