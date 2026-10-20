"""Build the standalone guide deterministically: pip install -e '.[docs]'."""

from pathlib import Path
import base64
import re
import markdown

ROOT = Path(__file__).resolve().parent
body = markdown.markdown((ROOT / "TUTORIAL.md").read_text(), extensions=["tables", "fenced_code"])
for path in (ROOT / "docs" / "images").glob("*.png"):
    body = body.replace(
        'src="docs/images/' + path.name + '"',
        'src="data:image/png;base64,' + base64.b64encode(path.read_bytes()).decode() + '"',
    )
body = re.sub(r"<h2>(\d+)\.", r'<h2 id="step-\1">\1.', body)
# Keep document links usable when the single HTML file is downloaded on its own.
body = re.sub(
    r'href="(?!https?://|mailto:|#)([^"]+)"',
    r'href="https://github.com/matcalabs002-sketch/local-rag-starter/blob/main/\1"',
    body,
)
style = """body{margin:0;background:#f5f5f7;color:#1d1d1f;font:17px/1.7 system-ui,sans-serif}main,header,footer{max-width:900px;margin:auto;padding:32px}header,footer{border-block:1px solid #dedee3;font-size:14px}h1{font:650 40px/1.15 system-ui,sans-serif;letter-spacing:-.035em}h2{font-size:28px;margin-top:56px}a{color:#0066cc}code{overflow-wrap:anywhere;background:#f0f0f3;padding:2px 4px}pre{background:#f0f0f3;padding:20px;overflow:auto}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:12px;border-bottom:1px solid #dedee3}img{max-width:100%;border:1px solid #dedee3}blockquote{border-left:3px solid #0066cc;padding-left:20px}@media(max-width:600px){main,header,footer{padding:20px}h1{font-size:36px}table{display:block;overflow:auto}}"""
page = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    "<title>Local RAG Starter · Beginner guide</title><style>" + style + "</style></head><body>"
    "<header>Local RAG Starter / Free chatbot framework</header><main>" + body + "</main>"
    "<footer>Local inference · Private source storage · MIT licensed</footer></body></html>\n"
)
(ROOT / "START-HERE.html").write_text(page)
