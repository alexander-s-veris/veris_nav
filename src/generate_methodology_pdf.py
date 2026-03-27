"""Generate NAV Data Sourcing Methodology PDF from markdown source.

Uses Playwright (headless Chromium) for rendering, which properly supports
CSS break-after: avoid on headings and break-inside: avoid on tables.
"""

import os
import re
import markdown
from playwright.sync_api import sync_playwright

DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "methodology")
MD_PATH = os.path.join(DOCS_DIR, "NAV_Data_Sourcing_Methodology.md")
PDF_PATH = os.path.join(DOCS_DIR, "NAV_Data_Sourcing_Methodology.pdf")

# CSS from claude_code_formatting_prompt.md with proper page-break rules
CSS = """
body {
    font-family: sans-serif;
    font-size: 10pt;
    line-height: 1.5;
    color: #000;
    background: white;
}

h1 {
    font-size: 16pt;
    margin-top: 24pt;
    margin-bottom: 8pt;
    break-after: avoid;
    page-break-after: avoid;
}

h2 {
    font-size: 13pt;
    margin-top: 20pt;
    margin-bottom: 6pt;
    break-after: avoid;
    page-break-after: avoid;
}

h3 {
    font-size: 11pt;
    margin-top: 14pt;
    margin-bottom: 4pt;
    break-after: avoid;
    page-break-after: avoid;
}

table {
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0;
    font-size: 9pt;
    break-inside: avoid;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #000;
    padding: 4px 8px;
    background: white;
    white-space: nowrap;
}

th {
    font-weight: bold;
    background: #2c3e6b;
    color: white;
}

code {
    font-family: monospace;
    font-size: 9pt;
    background: #f0f0f0;
    border-radius: 3px;
    padding: 2px 5px;
    white-space: normal;
    word-break: break-all;
}

pre {
    font-family: monospace;
    font-size: 8pt;
    background: white;
    margin: 4pt 0;
    padding: 4pt 8pt;
}

p {
    margin: 4pt 0;
}

ul, ol {
    margin: 4pt 0;
    padding-left: 20pt;
}

li {
    margin: 2pt 0;
    break-inside: avoid;
}

hr {
    display: none;
}
"""


def build_toc(md_text: str) -> str:
    lines = []
    for match in re.finditer(r"^(#{1,3})\s+(.+)$", md_text, re.MULTILINE):
        level = len(match.group(1))
        title = match.group(2)
        indent = "&nbsp;&nbsp;&nbsp;&nbsp;" * (level - 1)
        lines.append(f"{indent}{title}<br/>")
    return "<h2>Table of Contents</h2>\n" + "\n".join(lines) + "\n<br/>"


def main():
    with open(MD_PATH, encoding="utf-8") as f:
        md_text = f.read()

    html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    toc_html = build_toc(md_text)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
{toc_html}
{html_body}
</body>
</html>"""

    # Render with headless Chromium
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=PDF_PATH,
            format="A4",
            print_background=True,
            margin={
                "top": "80px",
                "bottom": "60px",
                "left": "50px",
                "right": "50px",
            },
            display_header_footer=True,
            header_template="""
                <div style="width: 100%; font-family: sans-serif; font-size: 7pt;
                            color: #666; text-align: center; padding: 0 50pt;
                            border-bottom: 0.5pt solid #bbb; padding-bottom: 4pt;">
                    Veris Capital AMC - NAV Data Sourcing Methodology &nbsp;|&nbsp; ISIN: LI1536896288
                </div>
            """,
            footer_template="""
                <div style="width: 100%; font-family: sans-serif; font-size: 8pt;
                            color: #666; text-align: center;">
                    Page <span class="pageNumber"></span> of <span class="totalPages"></span>
                </div>
            """,
        )
        browser.close()

    print(f"PDF generated: {PDF_PATH}")


if __name__ == "__main__":
    main()
