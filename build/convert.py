"""Build the Alice reader: Project Gutenberg HTML in, clean semantic book out.

Usage (from anywhere):
    python3 build/convert.py
    python3 build/convert.py --source other.html --output elsewhere.html

The template holds the page's design and code; it must contain the placeholders
<!-- @contents --> and <!-- @chapters -->. Generated markup takes on the
indentation of the placeholder it replaces. Edit the template, not the output.
"""
import argparse
import re
import textwrap
from pathlib import Path

BUILD_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BUILD_DIR.parent
DEFAULT_SOURCE = PROJECT_DIR / "pg11-h" / "pg11-images.html"
DEFAULT_TEMPLATE = BUILD_DIR / "template.html"
DEFAULT_OUTPUT = PROJECT_DIR / "alice-in-wonderland.html"

CHAPTER_RE = re.compile(r'<div class="chapter">(.*?)</div><!--end chapter-->', re.S)
HEADING_RE = re.compile(r'<h2><a id="chap(\d+)"></a>CHAPTER ([IVXLC]+)\.<br>\s*(.*?)</h2>', re.S)
BLOCK_RE = re.compile(
    r'<p(?: class="(?P<cls>\w+)")?>(?P<p>.*?)</p>'
    r'|<pre>(?P<pre>.*?)</pre>'
    r'|<h5>(?P<h5>.*?)</h5>'
    r'|(?P<hr><hr>)',
    re.S,
)
INDENT = "  "
WRAP_WIDTH = 96


def inline(text):
    """Collapse source line wrapping and use semantic emphasis."""
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace("<i>", "<em>").replace("</i>", "</em>")


def leading_spaces(line):
    """Count indentation; the source indents verse with non-breaking spaces."""
    return len(line) - len(line.lstrip("  "))


def balance_emphasis(lines):
    """Close and reopen <em> at line ends so each line is well-formed on its own."""
    balanced, open_em = [], False
    for line in lines:
        if open_em:
            line = "<em>" + line
        open_em = line.rfind("<em>") > line.rfind("</em>")
        balanced.append(line + "</em>" if open_em else line)
    return balanced


def paragraph(text, cls=None):
    """A prose paragraph, wrapped so the page source stays readable."""
    open_tag = f'<p class="{cls}">' if cls else "<p>"
    text = inline(text)
    if len(INDENT + open_tag + text) + 4 <= WRAP_WIDTH:
        return f"{INDENT}{open_tag}{text}</p>"
    body = textwrap.fill(
        text, WRAP_WIDTH, initial_indent=INDENT * 2, subsequent_indent=INDENT * 2,
        break_long_words=False, break_on_hyphens=False,
    )
    return f"{INDENT}{open_tag}\n{body}\n{INDENT}</p>"


def verse(raw, modifier=None, indent_unit=4):
    """Render <br>-separated lines as stanzas; blank lines start a new stanza."""
    lines = re.split(r"<br>\n?|\n", raw.strip("\n"))
    base = min(leading_spaces(l) for l in lines if l.strip())
    text = balance_emphasis([inline(l) for l in lines])

    stanzas, current = [], []
    for line, content in zip(lines, text):
        if not content:
            if current:
                stanzas.append(current)
                current = []
            continue
        level = round((leading_spaces(line) - base) / indent_unit)
        cls = "line" + (f" line--indent-{level}" if level else "")
        current.append(f'<span class="{cls}">{content}</span>')
    if current:
        stanzas.append(current)

    classes = "verse" + (f" verse--{modifier}" if modifier else "")
    body = "\n".join(
        f'{INDENT * 2}<p class="stanza">\n'
        + "\n".join(f"{INDENT * 3}{l}" for l in stanza)
        + f"\n{INDENT * 2}</p>"
        for stanza in stanzas
    )
    return f'{INDENT}<div class="{classes}">\n{body}\n{INDENT}</div>'


def tail(raw):
    """The Mouse's tale, set in the shape of a tail that narrows as it goes."""
    lines = [l for l in raw.strip("\n").split("\n") if l.strip()]
    last = len(lines) - 1
    spans = "\n".join(
        f'{INDENT * 2}<span class="tail__line" style="--indent: {leading_spaces(l)}; '
        f'--taper: {i / last:.2f}">{inline(l)}</span>'
        for i, l in enumerate(lines)
    )
    return (
        f'{INDENT}<figure class="tail" aria-label="The Mouse’s tale, printed in the shape of a tail">\n'
        f"{spans}\n{INDENT}</figure>"
    )


def block(match):
    if match["hr"]:
        return f'{INDENT}<hr class="break">'
    if match["h5"] is not None:
        return f'{INDENT}<p class="the-end">The End</p>'
    if match["pre"] is not None:
        is_tail = "Fury said to a" in match["pre"]
        return tail(match["pre"]) if is_tail else verse(match["pre"], "inscription", indent_unit=2)

    cls, text = match["cls"], match["p"]
    if cls == "poem":
        return verse(text)
    if cls == "asterism":
        return f'{INDENT}<hr class="break break--asterism">'
    if cls == "center":
        return paragraph(text, "aside").replace("<br> ", "<br>")
    if cls == "noindent":
        return paragraph(text, "continued")
    return paragraph(text)


def chapter(html):
    heading = HEADING_RE.search(html)
    if heading is None:
        raise ValueError(f"Chapter heading not found near: {html[:200]!r}")
    number, numeral, title = int(heading[1]), heading[2], inline(heading[3])
    body = html[heading.end():]

    leftover = BLOCK_RE.sub("", body).strip()
    if leftover:
        raise ValueError(f"Unconverted content in chapter {numeral}: {leftover[:200]!r}")

    blocks = "\n".join(block(m) for m in BLOCK_RE.finditer(body))
    article = (
        f'<article class="chapter" id="chapter-{number}" aria-labelledby="chapter-{number}-title">\n'
        f'{INDENT}<header class="chapter__header">\n'
        f'{INDENT * 2}<p class="chapter__number">Chapter {numeral}</p>\n'
        f'{INDENT * 2}<h2 class="chapter__title" id="chapter-{number}-title">{title}</h2>\n'
        f"{INDENT}</header>\n"
        f"{blocks}\n"
        f"</article>"
    )
    contents_item = (
        f'<li><a href="#chapter-{number}">'
        f'<span class="contents__numeral">{numeral}</span> {title}</a></li>'
    )
    return article, contents_item


def fill(template, placeholder, content):
    """Replace a placeholder comment, indenting content to match it."""
    pattern = re.compile(rf"^([ \t]*)<!-- @{placeholder} -->$", re.M)
    if not pattern.search(template):
        raise ValueError(f"Placeholder @{placeholder} not found in template")
    return pattern.sub(lambda m: textwrap.indent(content, m[1]), template, count=1)


def build(source, template, output):
    chapters = [chapter(c) for c in CHAPTER_RE.findall(source.read_text(encoding="utf-8"))]
    if len(chapters) != 12:
        raise ValueError(f"Expected 12 chapters, found {len(chapters)}")

    page = template.read_text(encoding="utf-8")
    page = fill(page, "contents", "\n".join(item for _, item in chapters))
    page = fill(page, "chapters", "\n\n".join(article for article, _ in chapters))
    output.write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Build the Alice reader from Project Gutenberg HTML.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Project Gutenberg HTML")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE, help="page template")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="where to write the book")
    args = parser.parse_args()
    build(args.source, args.template, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
