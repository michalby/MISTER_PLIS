"""Obsidian-flavoured Markdown → safe HTML for the lab notebook.

Handles what the lab's notes use: ``[[links]]`` (with ``|alias`` and ``#heading``), ``![[embeds]]``
(images, other notes), callouts (``> [!note]``), ``==highlight==``, ``~~strike~~``, ``%%comments%%``,
task lists, tables and front matter. Raw HTML in a note is shown as text, never run, and only
http(s)/mailto links are kept.

The caller decides what a link points to through ``resolve_note`` and ``resolve_file``, so this module
knows nothing about folders or which notes are shown.
"""

from __future__ import annotations

import html
import re
import unicodedata
import xml.etree.ElementTree as etree
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import quote, unquote

import markdown
from markdown.extensions import Extension

from mister_plis.text import fold, norm  # noqa: F401  (moved to text.py; still importable from here)
from markdown.extensions.toc import slugify_unicode
from markdown.treeprocessors import Treeprocessor

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".avif", ".heic"}
CALLOUTS = {
    "note": "note", "info": "info", "todo": "info", "tip": "tip", "hint": "tip", "important": "tip",
    "success": "success", "check": "success", "done": "success", "question": "question", "help": "question",
    "faq": "question", "warning": "warning", "caution": "warning", "attention": "warning", "failure": "danger",
    "fail": "danger", "missing": "danger", "danger": "danger", "error": "danger", "bug": "danger",
    "example": "note", "quote": "quote", "cite": "quote", "abstract": "note", "summary": "note", "tldr": "note",
}

# Private-use characters mark spots filled in after Markdown has run; Markdown leaves them alone.
_T0, _T1 = "\ue000", "\ue001"
_TOKEN = re.compile(f"{_T0}(\\d+){_T1}")
_FENCE = re.compile(r"^( {0,3})(`{3,}|~{3,})[^\n]*\n.*?(?:^\1\2[`~]*[ \t]*$|\Z)", re.S | re.M)
_INLINE_CODE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)", re.S)
_EMBED = re.compile(r"!\[\[([^\]\n]+)\]\]")
_WIKILINK = re.compile(r"\[\[([^\]\n]+)\]\]")
_MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_HIGHLIGHT = re.compile(r"==(?=\S)(.+?)(?<=\S)==")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_COMMENT = re.compile(r"%%.*?%%", re.S)
_FRONTMATTER = re.compile(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", re.S)
_SIZE = re.compile(r"^(\d{1,4})(?:x(\d{1,4}))?$")
_LIST_ITEM = r"[ \t]*(?:[-*+]|\d{1,3}[.)])[ \t]"
_LIST_AFTER_TEXT = re.compile(rf"^((?!{_LIST_ITEM})(?![ \t]*[>|])[^\n]*\S[^\n]*)\n(?={_LIST_ITEM})", re.M)
_SAFE_HREF = re.compile(r"^(https?:|mailto:|#|/notes/)", re.I)


def heading_slug(text: str) -> str:
    """Heading ids get an "h-" prefix so they can't clash with ids of the page around the note."""
    return "h-" + slugify_unicode(text, "-")


@dataclass
class NoteRef:
    """Where a [[link]] goes: a shown note (``id`` set) or nothing."""
    id: str
    title: str


@dataclass
class Rendered:
    html: str
    links: set[str] = field(default_factory=set)  # ids of shown notes this one links to
    files: set[str] = field(default_factory=set)  # vault paths of attachments it uses


def split_target(raw: str) -> tuple[str, str, str]:
    """``Note#Heading|Alias`` → (note, heading, alias); ``\\|`` (used inside tables) counts as ``|``."""
    raw = raw.replace("\\|", "|")
    target, _, alias = raw.partition("|")
    name, _, heading = target.partition("#")
    return name.strip(), heading.strip().lstrip("^"), alias.strip()


def note_url(note_id: str, heading: str = "") -> str:
    return "/notes/" + quote(note_id) + (f"#{quote(heading_slug(heading))}" if heading else "")


def file_url(path: str) -> str:
    return "/notes/files/" + quote(path)


class _Postprocess(Treeprocessor):
    """Callouts, task-list checkboxes and safe links, done on the element tree."""

    def run(self, root):
        for parent in root.iter():
            for i, el in enumerate(list(parent)):
                if el.tag == "blockquote":
                    self._callout(el)
                elif el.tag == "li":
                    self._task(el)
                elif el.tag == "a":
                    href = el.get("href", "")
                    if not _SAFE_HREF.match(href):
                        el.attrib.pop("href", None)
                    elif href.lower().startswith(("http:", "https:")):
                        el.set("target", "_blank")
                        el.set("rel", "noopener noreferrer")
                elif el.tag == "img":
                    src = el.get("src", "")
                    if not src.lower().startswith("https:"):
                        span = etree.Element("span", {"class": "note-missing"})
                        span.text = f"[image: {el.get('alt') or 'not available'}]"
                        span.tail = el.tail
                        parent.remove(el)
                        parent.insert(i, span)
                    else:
                        el.set("loading", "lazy")
                        el.set("referrerpolicy", "no-referrer")
                elif el.tag == "table" and parent.get("class") != "note-table":
                    wrap = etree.Element("div", {"class": "note-table"})
                    wrap.tail = el.tail
                    el.tail = None
                    parent.remove(el)
                    wrap.append(el)
                    parent.insert(i, wrap)

    @staticmethod
    def _callout(bq):
        first = bq[0] if len(bq) else None
        if first is None or first.tag != "p" or not first.text:
            return
        m = re.match(r"\s*\[!([\w-]+)\]([+-]?)[ \t]*([^\n]*)\n?", first.text)
        if not m:
            return
        kind = m.group(1).lower()
        title = m.group(3).strip() or kind.capitalize()
        first.text = first.text[m.end():]
        if not first.text.strip() and len(first) and first[0].tag == "br":  # nl2br's break after the title
            br = first[0]
            first.text = (br.tail or "").lstrip("\n")
            first.remove(br)
        if not first.text.strip() and len(first) == 0:
            bq.remove(first)
        bq.tag = "div"
        bq.set("class", f"callout callout-{CALLOUTS.get(kind, 'note')}")
        head = etree.Element("div", {"class": "callout-title"})
        head.text = title
        bq.insert(0, head)

    @staticmethod
    def _task(li):
        holder = li[0] if len(li) and li[0].tag == "p" and not (li.text or "").strip() else li
        m = re.match(r"\s*\[([ xX])\]\s", holder.text or "")
        if not m:
            return
        holder.text = holder.text[m.end():]
        box = etree.Element("input", {"type": "checkbox", "disabled": "disabled"})
        if m.group(1) != " ":
            box.set("checked", "checked")
        box.tail = " " + (holder.text or "")
        holder.text = None
        holder.insert(0, box)
        li.set("class", "task")


class _Obsidian(Extension):
    def extendMarkdown(self, md):
        # No raw HTML: a "<script>" in a note is printed as text.
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        md.treeprocessors.register(_Postprocess(md), "obsidian", 1)


def _md() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=["tables", "fenced_code", "sane_lists", "nl2br", "toc", _Obsidian()],
        extension_configs={"toc": {"slugify": slugify_unicode, "permalink": False}},
        output_format="html",
    )


class Renderer:
    """Turns one note's text into HTML. ``resolve_note(name, from_id)`` → NoteRef | None;
    ``resolve_file(name, from_id)`` → vault path of an attachment | None;
    ``load_note(id)`` → the text of a shown note (for ``![[embeds]]``)."""

    def __init__(self, resolve_note: Callable[[str, str], NoteRef | None],
                 resolve_file: Callable[[str, str], str | None],
                 load_note: Callable[[str], str | None]):
        self.resolve_note = resolve_note
        self.resolve_file = resolve_file
        self.load_note = load_note

    def render(self, text: str, note_id: str, depth: int = 0) -> Rendered:
        out = Rendered("")
        snippets: list[str] = []

        def token(snippet: str) -> str:
            snippets.append(snippet)
            return f"{_T0}{len(snippets) - 1}{_T1}"

        def link(name: str, heading: str, alias: str) -> str:
            if not name:  # [[#Heading]] inside the same note
                label = alias or heading
                return token(f'<a class="wikilink" href="#{html.escape(quote(heading_slug(heading)))}">{html.escape(label)}</a>')
            ref = self.resolve_note(name, note_id)
            label = alias or (f"{name} › {heading}" if heading else name)
            if ref:
                out.links.add(ref.id)
                return token(f'<a class="wikilink" href="{html.escape(note_url(ref.id, heading))}" data-note="{html.escape(ref.id)}">{html.escape(label)}</a>')
            path = self.resolve_file(name, note_id)
            if path:  # [[protocol.pdf]]: a link to an attachment
                out.files.add(path)
                return token(f'<a class="wikilink" href="{html.escape(file_url(path))}" target="_blank">{html.escape(label)}</a>')
            return token(f'<span class="wikilink-missing" title="Not shown in MISTER PLIS">{html.escape(label)}</span>')

        def embed(m: re.Match) -> str:
            name, heading, alias = split_target(m.group(1))
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in IMAGE_EXT:
                path = self.resolve_file(name, note_id)
                if not path:
                    return token(f'<span class="note-missing">[image: {html.escape(name)}]</span>')
                out.files.add(path)
                size = _SIZE.match(alias)
                attrs = f' width="{size.group(1)}"' if size else ""
                alt = "" if size else alias
                return token(f'<img src="{html.escape(file_url(path))}" alt="{html.escape(alt or name)}"{attrs} loading="lazy">')
            if ext and ext != ".md":
                return link(name, heading, alias)
            ref = self.resolve_note(name, note_id)
            if not ref or depth >= 1 or heading:
                return link(name, heading, alias)
            body = self.load_note(ref.id)
            if body is None:
                return link(name, heading, alias)
            out.links.add(ref.id)
            inner = self.render(body, ref.id, depth + 1)
            out.files |= inner.files
            out.links |= inner.links
            return "\n\n" + token(
                f'<div class="note-embed"><a class="note-embed-title wikilink" href="{html.escape(note_url(ref.id))}" '
                f'data-note="{html.escape(ref.id)}">{html.escape(ref.title)}</a>{inner.html}</div>') + "\n\n"

        def md_image(m: re.Match) -> str:
            alt, src = m.group(1), unquote(m.group(2))
            if src.lower().startswith(("http:", "https:")):
                return m.group(0)  # external picture: kept (https only, see _Postprocess)
            if re.match(r"^[a-z]+:", src, re.I):  # file:///C:/… pasted from Word
                return token(f'<span class="note-missing">[image: {html.escape(alt or "not available")}]</span>')
            path = self.resolve_file(src, note_id)
            if not path:
                return token(f'<span class="note-missing">[image: {html.escape(alt or src)}]</span>')
            out.files.add(path)
            return token(f'<img src="{html.escape(file_url(path))}" alt="{html.escape(alt)}" loading="lazy">')

        def inline(chunk: str) -> str:
            # keep `code` as it is, convert Obsidian syntax around it
            parts, last = [], 0
            for cm in _INLINE_CODE.finditer(chunk):
                parts.append(convert(chunk[last:cm.start()]))
                parts.append(cm.group(0))
                last = cm.end()
            parts.append(convert(chunk[last:]))
            return "".join(parts)

        def convert(s: str) -> str:
            # Obsidian starts a list right after a line of text; Markdown wants a blank line first
            s = _LIST_AFTER_TEXT.sub(r"\1\n\n", s)
            s = _EMBED.sub(embed, s)
            s = _WIKILINK.sub(lambda m: link(*split_target(m.group(1))), s)
            s = _MD_IMAGE.sub(md_image, s)
            s = _HIGHLIGHT.sub(lambda m: token("<mark>") + m.group(1) + token("</mark>"), s)
            s = _STRIKE.sub(lambda m: token("<del>") + m.group(1) + token("</del>"), s)
            return s

        text = unicodedata.normalize("NFC", text.replace("\r\n", "\n"))
        text = _FRONTMATTER.sub("", text, count=1)
        text = _COMMENT.sub("", text)
        pieces, last = [], 0
        for fm in _FENCE.finditer(text):
            pieces.append(inline(text[last:fm.start()]))
            pieces.append(fm.group(0))
            last = fm.end()
        pieces.append(inline(text[last:]))

        body = _md().convert("".join(pieces))
        body = re.sub(r'<(h[1-6]) id="', r'<\1 id="h-', body)
        # a block (embedded note) alone on its line must not sit inside <p>
        body = re.sub(f"<p>\\s*({_T0}(\\d+){_T1})\\s*</p>",
                      lambda m: m.group(1) if snippets[int(m.group(2))].startswith("<div") else m.group(0), body)
        # tokens inside code blocks are impossible (code is never converted), so filling them in is safe
        for _ in range(3):  # embeds hold tokens of their own (already filled in), one pass is normally enough
            new = _TOKEN.sub(lambda m: snippets[int(m.group(1))], body)
            if new == body:
                break
            body = new
        out.html = body
        return out


def title_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name[:-3] if name.lower().endswith(".md") else name


def plain_text(text: str) -> str:
    """Rough text of a note for search snippets."""
    text = _FRONTMATTER.sub("", text, count=1)
    text = _COMMENT.sub("", text)
    text = _EMBED.sub("", text)
    text = _WIKILINK.sub(lambda m: (split_target(m.group(1))[2] or split_target(m.group(1))[0]), text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_`=~|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
