"""Polish / English interface.

The code is written in English; Polish comes from the catalogue in ``mister_plis/locale/`` — a dict of
English → Polish. Who sees which language is a per-browser setting (cookie ``lang``, the switch in the top bar),
read like the other settings: ``pref("lang")`` for the current request or running job. English is the default.

Only the interface is translated. What is written to disk — job records, result files, backups, Time Machine —
is always English: jobs kept in the history run in English, and their results are translated when they are
shown (``outputs.translate_output``).

Keys can hold placeholders, so sentences built with values are translated without touching the tools::

    "Dissolve **{mass}** of {name}": "Rozpuść **{mass}** {name}"

A string that isn't in the catalogue as it is is matched against those patterns; the values caught by the
placeholders are translated too when they are catalogue entries themselves ("Mass [{unit}]" → "Masa [{unit}]").
Anything still unknown stays in English.

Plurals: ``tn(n, "{n} file", "{n} files")`` looks up ``"{n} file|{n} files"``, whose Polish value has the three
Polish forms: ``"{n} plik|{n} pliki|{n} plików"``.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache

from .prefs import pref

LANGS = {"pl": "Polski", "en": "English"}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*|\d+)\}")
_SENTENCE_END = re.compile(r"[.!?]\s+[A-Z“(]")  # a value that runs over into a further sentence
_NUMERIC = re.compile(r"[\d\s.,:×/%+−-]+")  # a value that is only numbers (for table cells)


def lang() -> str:
    """The language of whoever is asking (the request, or the job that is running)."""
    v = pref("lang")
    return v if v in LANGS else "en"


class Catalog:
    def __init__(self, entries: dict[str, str], language: str = "pl"):
        self.language = language
        self.exact = dict(entries)
        for key, value in entries.items():  # " Empty = …" (a key with its spaces) also found on its own
            if key.strip() != key and key.strip() not in self.exact:
                self.exact[key.strip()] = value.strip()
        patterns = []
        for key, value in self._pattern_entries(entries):
            parts = _PLACEHOLDER.split(key)  # literal, name, literal, name, …, literal
            literal = "".join(parts[0::2])
            if not literal.strip():
                continue  # "{0}" alone would match everything
            rx, seen = "", set()
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    rx += re.escape(part)
                elif part in seen:
                    rx += f"(?P=g{part})"
                else:
                    rx += f"(?P<g{part}>.+?)"
                    seen.add(part)
            patterns.append((len(literal), re.compile(rx, re.S), value))
        # most fixed text first: the likeliest best match is found early
        self.patterns = [(rx, value, n) for n, rx, value in sorted(patterns, key=lambda p: -p[0])]

    @staticmethod
    def _pattern_entries(entries: dict[str, str]):
        """(English pattern, translation) for every key with placeholders. A plural entry
        ``"{n} file|{n} files": "{n} plik|{n} pliki|{n} plików"`` gives both English forms, each translated to the
        tuple of forms: the form is chosen by the number found in ``{n}``. So "6 spectra" inside a sentence is
        translated too (results are stored in English and translated when shown)."""
        for key, value in entries.items():
            if not _PLACEHOLDER.search(key):
                continue
            if "|" not in key:
                yield key, value
                continue
            english, forms = key.split("|"), tuple(value.split("|"))
            if len(english) == 2 and "n" in _PLACEHOLDER.findall(english[0]) + _PLACEHOLDER.findall(english[1]):
                for form in dict.fromkeys(english):
                    yield form, forms

    def lookup(self, text: str, depth: int = 0, strict: bool = False, numeric: bool = False) -> str | None:
        """The translation, or None. ``strict``: no placeholder may swallow a further sentence (longer text is
        then translated sentence by sentence); ``numeric``: placeholders may only hold numbers (table cells)."""
        return self._lookup(text, depth, strict, numeric)[0]

    def _lookup(self, text: str, depth: int, strict: bool, numeric: bool) -> tuple[str | None, int]:
        """(translation or None, how many characters of ``text`` it covers). Of the patterns that fit, the one
        covering most of the text wins: "Dissolve **{0}** of {1}…" beats the bare "{0} of {1}"."""
        hit = self.exact.get(text)
        if hit is not None:
            return hit, len(text)
        if depth > 2 or len(text) > 4000:
            return None, 0
        best, best_cover = None, 0
        for rx, value, literal in self.patterns:
            m = rx.fullmatch(text)
            if not m:
                continue
            groups = m.groupdict()
            if strict and any(_SENTENCE_END.search(v) for v in groups.values()):
                continue
            if numeric and not all(_NUMERIC.fullmatch(v) for v in groups.values()):
                continue
            vals, cover = {}, literal
            for k, v in groups.items():
                sub, sub_cover = self._lookup(v, depth + 1, False, False) if v.strip() else (None, 0)
                vals[k[1:]] = v if sub is None else sub
                cover += sub_cover if sub is not None else (len(v) if not re.search(r"[A-Za-z]{2}", v) else 0)
            if isinstance(value, tuple):  # a plural: the form for the number in {n}
                try:
                    n = float(groups["gn"].replace("\u00a0", "").replace(" ", "").replace(",", "."))
                except (KeyError, ValueError):
                    continue
                value = value[min(plural_form(n, self.language), len(value) - 1)]
            out = _PLACEHOLDER.sub(lambda x: vals.get(x.group(1), x.group(0)), value)
            if out == text or cover < 0.3 * len(text):  # a stray " of " in a sentence isn't a translation of it
                continue
            if cover > best_cover:
                best, best_cover = out, cover
            if cover >= len(text):
                break
        return best, best_cover


@lru_cache(maxsize=1)
def _catalogs() -> dict[str, Catalog]:
    from .locale import PL

    return {"pl": Catalog(PL)}


def catalog(language: str) -> dict[str, str]:
    """The plain English → language dict (for the browser)."""
    cat = _catalogs().get(language)
    return cat.exact if cat else {}


@lru_cache(maxsize=20000)
def _translate(text: str, language: str, strict: bool = False, numeric: bool = False) -> str:
    cat = _catalogs().get(language)
    if cat is None:
        return text
    core = text.strip()
    if not core:
        return text
    if core != text:  # " — relative units." is a key with its spaces
        hit = cat.lookup(text, strict=strict, numeric=numeric)
        if hit is not None:
            return hit
    hit = cat.lookup(core, strict=strict, numeric=numeric)
    if hit is None:
        return text
    lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
    return lead + hit + trail


def _fill(template: str, values: dict) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template)


# ---- the phrase book of a stored job ------------------------------------------------------------------------
# Jobs kept in the history run in English (their files and records are English). While one runs, every piece a
# tool translates with tr / tn / trc is noted with its translation into each catalogue language — the job's phrase
# book. When the job is shown in Polish, the phrase book puts those pieces back, longest first, so results that
# tools glue together from translated pieces ("Pchlide signal = **…**" + ", × dilution" + …) read as they would
# have if the tool had run in Polish. What it doesn't cover is translated with the catalogue as usual.
MAX_PHRASES = 3000
_recording: ContextVar[dict | None] = ContextVar("i18n_recording", default=None)
_phrases: ContextVar[list | None] = ContextVar("i18n_phrases", default=None)


@contextmanager
def recording():
    """Note the translations of what is translated meanwhile (a stored job running in English): yields
    ``{language: {english: translation}}``, filled as the job runs."""
    book: dict = {}
    token = _recording.set(book)
    try:
        yield book
    finally:
        _recording.reset(token)


def _note(english: str, translate) -> None:
    book = _recording.get()
    if book is None or not isinstance(english, str) or not english.strip() or len(english) > 4000:
        return
    for language in _catalogs():
        notes = book.setdefault(language, {})
        if english in notes or len(notes) >= MAX_PHRASES:
            continue
        other = translate(language)
        if isinstance(other, str) and other != english:
            notes[english] = other


@contextmanager
def phrases(book: dict | None):
    """Use a stored job's phrase book (see ``recording``) while showing it in the current language."""
    notes = (book or {}).get(lang()) if isinstance(book, dict) else None
    if not notes or not isinstance(notes, dict):
        yield
        return
    token = _phrases.set([notes, None])  # the swaps are worked out on first use (a job list needs none)
    try:
        yield
    finally:
        _phrases.reset(token)


def _swaps(notes: dict) -> list:
    pairs = dict(notes)
    for english, other in notes.items():  # tools sometimes lower-case a translated piece ("… = **peak maximum**")
        if isinstance(english, str) and isinstance(other, str) and english.lower() != english:
            pairs.setdefault(english.lower(), other.lower())
    swaps = []
    for english, other in sorted(pairs.items(), key=lambda kv: -len(kv[0])):
        if not (isinstance(english, str) and isinstance(other, str)) or len(english) < 3 or not re.search(r"[A-Za-z]", english):
            continue
        start = r"(?<!\w)" if re.match(r"\w", english) else ""
        end = r"(?!\w)" if re.search(r"\w$", english) else ""
        swaps.append((english, re.compile(start + re.escape(english) + end), other))
    return swaps


def _swap(text: str, whole_only: bool = False) -> str:
    active = _phrases.get()
    if not active or not isinstance(text, str) or not text.strip():
        return text
    notes = active[0]
    if text in notes:
        return notes[text]
    if whole_only:
        return text
    if active[1] is None:
        active[1] = _swaps(notes)
    for english, rx, other in active[1]:
        if english in text:
            text = rx.sub(lambda _m: other, text)
    return text


def tr(text, language: str | None = None, /, **values) -> str:
    """``text`` in the current language; ``{name}`` placeholders are then filled from ``values``."""
    if text is None:
        return ""
    if not isinstance(text, str):
        return text
    language = language or lang()
    if language == "en":
        out = _fill(text, values) if values else text
        if _recording.get() is not None:
            _note(out, lambda other: tr(text, other, **values))
        return out
    if not values:
        text = _swap(text)
    out = _translate(text, language)
    return _fill(out, values) if values else out


_LIST_ITEM = re.compile(r"^(\s*(?:\d+\.|[-*•])\s+)?(.*)$", re.S)
_SENTENCE = re.compile(r"(?<=[.!?:])\s+(?=[A-Z*“(])")


def tr_text(text: str, language: str | None = None) -> str:
    """Longer text (Markdown): as a whole if the catalogue has it, else line by line (list markers kept),
    else sentence by sentence — so a recipe made of several catalogue sentences is translated too."""
    if not isinstance(text, str):
        return text
    language = language or lang()
    if language != "en":
        text = _swap(text)
    whole = tr(text, language)
    if whole != text or language == "en":
        return whole

    def line(s: str) -> str:
        m = _LIST_ITEM.match(s)
        marker, body = m.group(1) or "", m.group(2)
        out = _translate(body, language, strict=True)
        if out == body and _SENTENCE.search(body):
            out = _by_sentences(_SENTENCE.split(body), language)
        if out == body:
            out = tr(body, language)
        return marker + out

    return "\n".join(line(s) for s in text.split("\n"))


def _by_sentences(sents: list[str], language: str) -> str:
    """Translate a run of sentences, taking the longest stretch the catalogue knows each time
    (some entries are two or three sentences long)."""
    out, i = [], 0
    while i < len(sents):
        for j in range(len(sents), i, -1):
            chunk = " ".join(sents[i:j])
            done = _translate(chunk, language, strict=True) if j > i + 1 else tr(chunk, language)
            if done != chunk or j == i + 1:
                out.append(done)
                i = j
                break
    return " ".join(out)


def trc(context: str, text: str, language: str | None = None) -> str:
    """``text`` where the same English word means something else elsewhere: the key is "<context>::<text>"
    ("printer::Standard" is a resolution, "Standard" alone a standard solution)."""
    language = language or lang()
    if language == "en":
        if _recording.get() is not None:
            _note(text, lambda other: trc(context, text, other))
        return text
    cat = _catalogs().get(language)
    hit = cat.exact.get(f"{context}::{text}") if cat else None
    return hit if hit is not None else tr(text, language)


def exact(text, language: str | None = None) -> str:
    """For table cells: a whole catalogue entry, or a pattern whose values are only numbers ("1 of 3"),
    so that a sample called "WT 2" stays "WT 2"."""
    if not isinstance(text, str) or not text.strip():
        return text
    language = language or lang()
    if language == "en":
        return text
    swapped = _swap(text, whole_only=True)
    return swapped if swapped != text else _translate(text, language, numeric=True)


def plural_form(n: float, language: str) -> int:
    """Index of the plural form: English one / other; Polish one / few (2–4, 22–24…) / many."""
    if language != "pl":
        return 0 if n == 1 else 1
    if n != int(n):
        return 1  # 1,5 litra
    n = abs(int(n))
    if n == 1:
        return 0
    return 1 if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 2


def tn(n: float, one: str, other: str, language: str | None = None, /, **values) -> str:
    """"{n} file" / "{n} files" for ``n``, in the current language."""
    language = language or lang()
    forms = [one, other]
    if language != "en":
        hit = _catalogs()[language].exact.get(f"{one}|{other}") if language in _catalogs() else None
        if hit:
            forms = hit.split("|")
    form = forms[min(plural_form(n, language), len(forms) - 1)]
    out = _fill(form, {"n": n, **values})
    if language == "en" and _recording.get() is not None:
        _note(out, lambda language_: tn(n, one, other, language_, **values))
    return out
