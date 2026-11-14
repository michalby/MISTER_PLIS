"""Reagent labels for the lab's Brother P-touch (PT-E550W) tape printer.

A label has the lab's logo up the left edge (if the lab has one: Settings → Exports & printing, or ``[label_printer]
logo`` in its lab file), then the reagent name (large), its concentration, and the person and date on the bottom line. Labels for a whole
protocol go out as one strip of tape. How it is cut follows the printer's own cut options: half cut between
labels (the tape is cut, the backing isn't), auto cut (cut right through) and chain printing (the end of the
strip stays in the printer, to be cut with its button or by the next job). The default is the PT-E550W's
cut option 5: half cut, chain printing, no auto cut.

Each label is drawn at 8× the printer's resolution and reduced to its dot grid, which keeps letters even at
7 pt. In high-resolution mode the printer prints 360 dots per inch along the tape (180 across it, the print
head). The commands follow Brother's "Software Developer's Manual – Raster Command Reference
PT-E550W/P750W/P710BT" (v1.02) and are sent straight to the printer over the network (raw TCP, port 9100) —
no macOS printer or driver needed.

The reagent inventory prints labels for a portion put into a new container with the same layout: the storage
category letter in a rounded square in place of the logo, and a second, safety label with the GHS pictograms.

The printer's address, tape width, resolution and cut options are lab-wide settings (Settings → Exports & printing), kept in
``<data>/label_printer.json``; the "Labels" window can change all but the address for one print. The lab's logo is
``<data>/label_logo.png`` (none: no file).
"""

from __future__ import annotations

import base64
import io
import json
import re
import socket
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .errors import ToolError

PKG = Path(__file__).resolve().parent
LOGO_FILE = "label_logo.png"  # in the data folder: the lab's logo, if it has one
LOGO_MAX = 256_000  # bytes: a logo is a small picture (a lab file carries it inside)
LOGO_PIXELS = 4_000_000
DPI = 180  # across the tape (print head); along it 180, or 360 in high-resolution mode
PORT = 9100
HEAD_PINS = 128  # print head width in dots; each raster line is 16 bytes
# tape width (mm) → (printable dots, unused pins before them), manual §2.3.5
TAPES = {3.5: (24, 52), 6: (32, 48), 9: (50, 39), 12: (70, 29), 18: (112, 8), 24: (128, 0)}
TAPE_CHOICES = (9, 12, 18, 24)  # wide enough for the three lines of text
FEED_MM = 2  # blank tape before and after each label: the printer's minimum margin
MAX_LENGTH_MM = 300  # one label
MAX_LABELS = 99  # one strip ("cut each n labels" goes up to 99)
SUPER = 8  # drawing resolution, × 180 dpi

FIELDS = {"name": 80, "detail": 80, "person": 60, "date": 30}  # field → longest allowed text
GHS_DIR = PKG / "static" / "label" / "ghs"  # the official pictograms (rendered from modules/inventory/static/ghs/*.svg), black on tape
GHS_CODES = tuple(f"0{n}" for n in range(1, 10))


# --- fonts -------------------------------------------------------------------------------

# Lato is what the P-touch template uses; Arial (what the PDF reports use) if it isn't installed.
_REGULAR = [
    Path.home() / "Library/Fonts/Lato-Regular.ttf", Path("/Library/Fonts/Lato-Regular.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("C:/Windows/Fonts/arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
# for characters the main font lacks (Arial has no ₂ ₃ …)
_FALLBACK = [
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"), Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
]
_BOLD = [
    Path.home() / "Library/Fonts/Lato-Bold.ttf", Path("/Library/Fonts/Lato-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"), Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
]
_font_cache: dict = {}


def _bold(size: int):
    p = next((p for p in _BOLD if p.exists()), None)
    return ImageFont.truetype(str(p), size) if p else _fonts(size)[0]


def _fonts(size: int) -> list:
    if size not in _font_cache:
        found = [p for p in (next((p for p in _REGULAR if p.exists()), None), next((p for p in _FALLBACK if p.exists()), None)) if p]
        fonts = [ImageFont.truetype(str(p), size) for p in dict.fromkeys(found)]
        _font_cache[size] = fonts or [ImageFont.load_default(size)]
    return _font_cache[size]


def _has_glyph(font, ch: str) -> bool:
    if ch.isspace():
        return True
    try:
        return bytes(font.getmask(ch)) != bytes(font.getmask("\uffff"))  # a missing character draws the "no glyph" box
    except Exception:
        return False


def _runs(text: str, fonts: list) -> list[tuple[str, object]]:
    """Split text into pieces that one font can draw, preferring the first font."""
    runs: list[list] = []
    for ch in text:
        font = next((f for f in fonts if _has_glyph(f, ch)), fonts[0])
        if runs and runs[-1][1] is font:
            runs[-1][0] += ch
        else:
            runs.append([ch, font])
    return [(t, f) for t, f in runs]


def _text_width(text: str, size: int) -> int:
    return round(sum(f.getlength(t) for t, f in _runs(text, _fonts(size))))


def _draw_text(draw: ImageDraw.ImageDraw, x: float, top: float, text: str, size: int) -> None:
    fonts = _fonts(size)
    ascent = fonts[0].getmetrics()[0]
    for t, f in _runs(text, fonts):
        draw.text((x, top + ascent), t, font=f, fill=0, anchor="ls")  # common baseline for every font
        x += f.getlength(t)


# --- drawing ---------------------------------------------------------------------------------


@dataclass
class Label:
    name: str = ""
    detail: str = ""  # concentration, e.g. "150 mM"
    person: str = ""
    date: str = ""
    logo: bool = True
    # reagent labels: the storage category letter in a rounded square instead of the logo (a portion's label),
    # or GHS pictograms on the left (its second, safety label)
    square: str = ""
    pictos: tuple = ()
    right: str = ""  # large, at the right end (the reagent's label number), like the letter in the square
    match: str = ""  # labels with the same key come out the same length (a portion's two labels)

    @classmethod
    def from_dict(cls, d: dict) -> "Label":
        d = d if isinstance(d, dict) else {}
        clean = {k: " ".join(str(d.get(k) or "").split())[:n] for k, n in FIELDS.items()}
        square = " ".join(str(d.get("square") or "").split())[:2]
        raw = d.get("pictos") if isinstance(d.get("pictos"), list) else []
        pictos = tuple(dict.fromkeys(c for c in (str(x).removeprefix("GHS").zfill(2) for x in raw) if c in GHS_CODES))
        one = lambda key, n: " ".join(str(d.get(key) or "").split())[:n]  # noqa: E731
        return cls(**clean, logo=d.get("logo", True) not in (False, "false", "0", 0), square=square, pictos=pictos,
                   right=one("right", 8), match=one("match", 40))

    @property
    def empty(self) -> bool:
        return not (self.name or self.detail or self.pictos)


def _xdpi(hires: bool) -> int:
    return 2 * DPI if hires else DPI


def render(label: Label, tape_mm: float = 12, hires: bool = True, min_dots: int = 0,
           lab_logo: Image.Image | None = None) -> Image.Image:
    """The label as it will print: mode "1", one pixel per dot (360 or 180 dpi along the tape, 180 across).
    min_dots: at least this long (in printed dots), to match another label; the extra tape goes before the
    right-hand number, or at the end. lab_logo: the lab's logo (:func:`logo_image`), drawn when the label asks for it."""
    if tape_mm not in TAPES:
        raise ToolError(f"Unsupported tape width: {tape_mm} mm.")
    h = TAPES[tape_mm][0]
    k = SUPER
    u = h / 70 * k  # layout units: dots of 12 mm tape (70 dots high), at the drawing resolution
    big, small = round(25 * u), round(18 * u)  # 10 pt and 7 pt, as in the template
    line2, line3 = round(25 * u), round(49 * u)

    x0 = 0
    logo = None
    if label.pictos:  # side by side, each as high as the tape
        side = h * k
        gap = round(3 * u)
        logo = Image.new("L", (len(label.pictos) * (side + gap) - gap, side), 255)
        for i, code in enumerate(label.pictos):
            pic = Image.open(GHS_DIR / f"GHS{code}.png").convert("L").resize((side, side), Image.LANCZOS)
            logo.paste(pic, (i * (side + gap), 0))
        x0 = logo.width + round(9 * u)
    elif label.square:  # white letter in a black rounded square
        side = h * k - round(4 * u)
        logo = Image.new("L", (side, h * k), 255)
        sq = ImageDraw.Draw(logo)
        top = (h * k - side) // 2
        sq.rounded_rectangle((0, top, side - 1, top + side - 1), radius=round(side * 0.22), fill=0)
        font = _bold(_big_size(h, k, len(label.square)))
        sq.text((side / 2, top + side / 2), label.square, font=font, fill=255, anchor="mm")
        x0 = logo.width + round(9 * u)
    elif label.logo and lab_logo is not None:
        logo = lab_logo.rotate(270, expand=True)  # reads top to bottom
        logo = logo.resize((max(1, round(logo.width * h * k / logo.height)), h * k), Image.LANCZOS)
        x0 = logo.width + round(11 * u)

    name = label.name or " "
    widths = [x0 + _text_width(name, big), x0 + _text_width(label.detail, small)]
    person_w = _text_width(label.person, small)
    date_x = x0 + max(round(55 * u), person_w + round(10 * u)) if label.person else x0
    widths.append(date_x + _text_width(label.date, small) if label.date else x0 + person_w)
    right_font = _bold(_big_size(h, k, 1)) if label.right else None
    right_w = round(right_font.getlength(label.right)) if right_font else 0
    length = max(max(widths) + round(4 * u) + (right_w + round(9 * u) if right_w else 0), h * k)
    if length / (DPI * k) * 25.4 > MAX_LENGTH_MM:
        raise ToolError(f"The label would be longer than {MAX_LENGTH_MM / 10:g} cm — shorten the text.")

    step = DPI * k // _xdpi(hires)  # drawing pixels per printed dot along the tape
    length = max(-(-length // step) * step, min_dots * step)
    img = Image.new("L", (length, h * k), 255)
    if logo:
        img.paste(logo, (0, 0))
    d = ImageDraw.Draw(img)
    _draw_text(d, x0, 0, name, big)
    if label.detail:
        _draw_text(d, x0, line2, label.detail, small)
    if label.person:
        _draw_text(d, x0, line3, label.person, small)
    if label.date:
        _draw_text(d, date_x, line3, label.date, small)
    if right_font:
        d.text((length - round(2 * u), h * k / 2), label.right, font=right_font, fill=0, anchor="rm")
    # each printed dot is black when enough of its area is: even strokes, no lost hairlines
    small_img = img.resize((length // step, h), Image.BOX)
    return small_img.point(lambda v: 0 if v < 150 else 255).convert("1", dither=Image.NONE)


def _big_size(h: int, k: int, chars: int) -> int:
    """The letter in the square (and the number on the right): as large as the square allows."""
    side = h * k - round(4 * h / 70 * k)
    return round(side * (0.68 if chars == 1 else 0.5))


def render_all(labels: list[Label], tape_mm: float, hires: bool = True, lab_logo: Image.Image | None = None) -> list[Image.Image]:
    """Every label, those that share a `match` key made as long as the longest of them."""
    imgs = [render(lb, tape_mm, hires, 0, lab_logo) for lb in labels]
    longest: dict[str, int] = {}
    for lb, img in zip(labels, imgs):
        if lb.match:
            longest[lb.match] = max(longest.get(lb.match, 0), img.width)
    return [render(lb, tape_mm, hires, longest[lb.match], lab_logo) if lb.match and img.width < longest[lb.match] else img
            for lb, img in zip(labels, imgs)]


def _feed(hires: bool) -> int:
    return round(FEED_MM / 25.4 * _xdpi(hires))


def _check_count(labels: list[Label]) -> list[Label]:
    labels = [lb for lb in labels if not lb.empty]
    if not labels:
        raise ToolError("There is nothing to print — every label is empty.")
    if len(labels) > MAX_LABELS:
        raise ToolError(f"At most {MAX_LABELS} labels on one strip.")
    return labels


def preview_png(labels: list[Label], tape_mm: float = 12, hires: bool = True, half_cut: bool = True, auto_cut: bool = False,
                scale: int = 4, lab_logo: Image.Image | None = None) -> bytes:
    """The strip as it will come out: labels with the blank tape fed around each, cut lines dashed,
    enlarged so each dot is visible (in high-resolution mode a dot is half as long as it is high).
    Between labels: a half cut is dashed, a full cut solid, no cut (neither option) not drawn."""
    imgs = [img.convert("L") for img in render_all(_check_count(labels), tape_mm, hires, lab_logo)]
    feed = _feed(hires)
    sx = scale // 2 if hires else scale  # screen pixels per dot along the tape
    tape_h = round(tape_mm / 25.4 * DPI) * scale
    dots, _ = TAPES[tape_mm]
    total = sum(i.width + 2 * feed for i in imgs)
    strip = Image.new("L", (total * sx, max(tape_h, dots * scale)), 255)
    top = (strip.height - dots * scale) // 2
    x = 0
    cuts = []
    for i, img in enumerate(imgs):
        big = img.resize((img.width * sx, img.height * scale), Image.NEAREST)
        strip.paste(big, ((x + feed) * sx, top))
        x += img.width + 2 * feed
        if i < len(imgs) - 1 and (half_cut or auto_cut):
            cuts.append(x * sx)
    d = ImageDraw.Draw(strip)
    dash = 3 * scale
    for cx in cuts:
        for y in range(0, strip.height, 2 * dash if half_cut else dash):
            d.line([(cx, y), (cx, y + dash - 1)], fill=150, width=max(1, scale // 2))
    buf = io.BytesIO()
    strip.convert("L").save(buf, "PNG", optimize=True)
    return buf.getvalue()


# --- printer commands -------------------------------------------------------------------------


def _raster_lines(img: Image.Image, tape_mm: float) -> list[bytes]:
    """One 16-byte line per column of the picture. Pin 0 is the last bit of the last byte (manual §4, "G"), and
    the picture's bottom row goes to the lowest pin — the other way round the label comes out mirrored
    (same order as the ptouch-print driver)."""
    dots, offset = TAPES[tape_mm]
    if img.height != dots:
        raise ValueError("picture height must match the tape")
    px = img.convert("1").load()
    lines = []
    for x in range(img.width):
        line = bytearray(HEAD_PINS // 8)
        for y in range(dots):
            if not px[x, y]:  # black
                pin = offset + dots - 1 - y
                line[HEAD_PINS // 8 - 1 - pin // 8] |= 1 << (pin % 8)
        lines.append(bytes(line))
    return lines


def raster_job(imgs: list[Image.Image], tape_mm: float, hires: bool = True, half_cut: bool = True,
               auto_cut: bool = False, chain: bool = True) -> bytes:
    """Brother raster commands for a strip of labels: one page per label, control codes repeated for each page,
    FF between pages and Control-Z (print, then feed and cut as the options say) after the last.

    half_cut: between labels; auto_cut: cut right through (after the strip with half cuts, else after each label);
    chain: don't feed and cut after the last label — it stays in the printer for its cut button."""
    if isinstance(imgs, Image.Image):
        imgs = [imgs]
    advanced = (0x04 if half_cut else 0) | (0 if chain else 0x08) | (0x40 if hires else 0)  # ESC i K, manual §4
    per_cut = len(imgs) if half_cut else 1  # with auto cut: through after the whole strip, or after each label
    out = bytearray(b"\x00" * 100)  # invalidate: clears a half-received job
    out += b"\x1b@"  # initialise
    for page, img in enumerate(imgs):
        lines = _raster_lines(img, tape_mm)
        out += b"\x1bia\x01"  # raster mode
        # print information: valid flags (recover + width), laminated tape, width mm, length 0, raster lines, page
        out += b"\x1biz" + bytes([0x84, 0x01, int(tape_mm), 0x00]) + len(lines).to_bytes(4, "little") + bytes([0 if page == 0 else 1, 0])
        out += b"\x1biM" + bytes([0x40 if auto_cut else 0])  # auto cut; mirror printing (0x80) off
        out += b"\x1biA" + bytes([max(1, min(MAX_LABELS, per_cut))])  # cut each n labels
        out += b"\x1biK" + bytes([advanced])
        out += b"\x1bid" + _feed(hires).to_bytes(2, "little")  # margin before and after the label
        out += b"M\x02"  # TIFF (PackBits) compression
        for line in lines:
            if any(line):
                out += b"G" + (len(line) + 1).to_bytes(2, "little") + bytes([len(line) - 1]) + line  # one literal run
            else:
                out += b"Z"  # blank line
        out += b"\x1a" if page == len(imgs) - 1 else b"\x0c"
    return bytes(out)


ERRORS_1 = {0x01: "no tape cassette", 0x02: "the tape ran out", 0x04: "the cutter is jammed", 0x08: "the battery is low",
            0x40: "wrong power adapter"}
ERRORS_2 = {0x01: "the tape cassette needs replacing", 0x10: "the cover is open", 0x20: "the printer is overheating"}
WIDTH_FROM_STATUS = {4: 3.5, 6: 6, 9: 9, 12: 12, 18: 18, 24: 24}


@dataclass
class Status:
    tape_mm: float | None
    errors: list[str]


def parse_status(b: bytes) -> Status:
    if len(b) < 32 or b[0] != 0x80:
        raise ToolError("The printer sent an answer this app doesn't understand.")
    errors = [m for bit, m in ERRORS_1.items() if b[8] & bit] + [m for bit, m in ERRORS_2.items() if b[9] & bit]
    return Status(WIDTH_FROM_STATUS.get(b[10]), errors)


# --- the lab's logo ------------------------------------------------------------------------------


def check_logo(data: bytes) -> bytes:
    """A picture for the labels' logo (PNG, JPEG, GIF, WebP…) → the PNG kept. Raises :class:`ToolError`."""
    if not data:
        raise ToolError("Choose a picture for the logo.")
    if len(data) > LOGO_MAX:
        raise ToolError(f"The logo should be a small picture (at most {LOGO_MAX // 1000} kB).")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > LOGO_PIXELS or not im.width or not im.height:
                raise ToolError("The logo's picture is too large.")
            im.load()
            out = io.BytesIO()
            im.save(out, "PNG")
    except ToolError:
        raise
    except Exception:
        raise ToolError("That isn't a picture this app can read (use PNG or JPEG).") from None
    png = out.getvalue()
    if len(png) > LOGO_MAX * 2:
        raise ToolError(f"The logo should be a small picture (at most {LOGO_MAX // 1000} kB).")
    return png


def logo_data_url(png: bytes) -> str:
    """How a lab file (and the setup page) carries the logo: the picture itself, as a data: address."""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def logo_from_data_url(text: str) -> bytes:
    """A data: address of a picture → the PNG to keep. Raises :class:`ToolError`."""
    m = re.fullmatch(r"data:image/[a-z+.-]+;base64,([A-Za-z0-9+/=\s]+)", str(text or "").strip())
    if not m:
        raise ToolError("The logo should be a picture (a data:image/…;base64 address).")
    try:
        raw = base64.b64decode("".join(m.group(1).split()), validate=True)
    except ValueError:
        raise ToolError("The logo's picture is damaged.") from None
    return check_logo(raw)


def logo_image(png: bytes | None) -> Image.Image | None:
    """The logo as the labels draw it: grey levels, transparent parts white."""
    if not png:
        return None
    with Image.open(io.BytesIO(png)) as im:
        im = im.convert("RGBA")
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        return Image.alpha_composite(white, im).convert("L")


# --- settings and sending ------------------------------------------------------------------------


@dataclass
class PrinterSettings:
    address: str = ""  # IP or host name, optionally :port
    tape_mm: float = 12
    hires: bool = True  # 180 × 360 dpi
    half_cut: bool = True  # between labels on a strip
    auto_cut: bool = False  # cut right through
    chain: bool = True  # leave the end of the strip in the printer (no feed and cut after it)

    def with_options(self, options: dict | None) -> "PrinterSettings":
        """A copy with one print's choices (tape, resolution, cutting) from the Labels window applied."""
        s = PrinterSettings(**asdict(self))
        _apply(s, {k: v for k, v in (options or {}).items() if k != "address"})
        return s


BOOL_OPTIONS = ("hires", "half_cut", "auto_cut", "chain")


def _apply(s: PrinterSettings, changes: dict) -> None:
    if "address" in changes:
        address = str(changes["address"] or "").strip()
        if any(c.isspace() or c in "/\\@" for c in address):
            raise ToolError("Type just the printer's IP address or host name, e.g. 192.168.1.50.")
        s.address = address
    if "tape_mm" in changes:
        try:
            tape = float(changes["tape_mm"])
        except (TypeError, ValueError):
            raise ToolError("Pick a tape width.") from None
        tape = int(tape) if tape.is_integer() else tape
        if tape not in TAPE_CHOICES:
            raise ToolError("Pick a tape width.")
        s.tape_mm = tape
    for key in BOOL_OPTIONS:
        if key in changes:
            setattr(s, key, changes[key] not in (False, "false", "0", 0, None))


class Printer:
    def __init__(self, data_path: Path):
        self.file = data_path / "label_printer.json"
        self.logo_file = data_path / LOGO_FILE
        self._lock = threading.Lock()

    # ---- the lab's logo ----
    def logo_png(self) -> bytes | None:
        try:
            return self.logo_file.read_bytes() or None
        except OSError:
            return None

    def logo_data(self) -> str:
        """The logo as a data: address ("" for none): what the lab file and the setup page carry."""
        png = self.logo_png()
        return logo_data_url(png) if png else ""

    def _set_logo(self, value) -> None:
        if value in (None, "", False):
            if self.logo_file.exists():
                self.logo_file.unlink()
            return
        png = value if isinstance(value, bytes) else logo_from_data_url(str(value))
        png = check_logo(png)
        self.logo_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.logo_file.with_suffix(".tmp")
        tmp.write_bytes(png)
        tmp.replace(self.logo_file)

    def keep_old_logo(self, old: Callable[[], bytes | None]) -> bool:
        """Once, for a server that printed labels before labs chose their own logo (its label_printer.json has no
        "logo" yet): it keeps the picture ``old()`` gives (its lab's), so a server's labels don't change by
        themselves. Returns True when it kept one."""
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(d, dict) or "logo" in d:
            return False
        kept = False
        if not self.logo_file.exists():
            try:
                png = old()
                if png:
                    self._set_logo(png)
                    kept = True
            except (OSError, ToolError) as e:
                print(f"label logo: the old one wasn't kept ({e})", flush=True)
        self._write(self.settings())
        return kept

    def settings(self) -> PrinterSettings:
        try:
            d = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return PrinterSettings()
        tape = d.get("tape_mm")
        s = PrinterSettings(str(d.get("address") or ""), tape if tape in TAPE_CHOICES else PrinterSettings.tape_mm)
        for key in BOOL_OPTIONS:
            if isinstance(d.get(key), bool):
                setattr(s, key, d[key])
        return s

    def update(self, changes: dict) -> PrinterSettings:
        """Change the printer's settings; ``changes["logo"]``: a picture (bytes, or a data: address), or "" for none."""
        s = self.settings()
        _apply(s, changes)
        if "logo" in changes:
            self._set_logo(changes["logo"])
        self._write(s)
        return s

    def _write(self, s: PrinterSettings) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        # "logo": whether the lab has one (the picture is label_logo.png); its presence also says the old logo's
        # question (keep_old_logo) has been answered
        tmp.write_text(json.dumps(asdict(s) | {"logo": self.logo_file.exists()}, indent=1), encoding="utf-8")
        tmp.replace(self.file)

    def info(self) -> dict:
        logo = self.logo_file.stat().st_mtime_ns if self.logo_file.exists() else 0
        return asdict(self.settings()) | {"tape_choices": list(TAPE_CHOICES), "logo": bool(logo), "logo_version": logo}

    def preview(self, labels: list[Label], options: dict | None = None) -> bytes:
        s = self.settings().with_options(options)
        return preview_png(labels, s.tape_mm, s.hires, s.half_cut, s.auto_cut, lab_logo=logo_image(self.logo_png()))

    def _target(self) -> tuple[str, int]:
        addr = self.settings().address
        if not addr:
            raise ToolError("No label printer is set up — add its address in Settings → Exports & printing.")
        host, _, port = addr.rpartition(":") if addr.count(":") == 1 else (addr, "", "")
        return (host or addr), int(port) if port.isdigit() else PORT

    def _connect(self) -> socket.socket:
        host, port = self._target()
        try:
            return socket.create_connection((host, port), timeout=5)
        except OSError as e:
            raise ToolError(f"Can't reach the label printer at {host} ({e.strerror or e}). Is it on and on the same network?") from None

    @staticmethod
    def _ask_status(sock: socket.socket) -> Status | None:
        """Ask for the 32-byte status; None if the printer doesn't answer (the manual only documents it for USB)."""
        sock.sendall(b"\x00" * 100 + b"\x1b@" + b"\x1biS")
        data = b""
        sock.settimeout(3)
        try:
            while len(data) < 32:
                chunk = sock.recv(32 - len(data))
                if not chunk:
                    break
                data += chunk
        except OSError:
            return None
        return parse_status(data) if len(data) == 32 else None

    def check(self) -> str:
        with self._lock, self._connect() as sock:
            st = self._ask_status(sock)
        if st is None:
            return "The printer is reachable but didn't report its status."
        tape = f"{st.tape_mm:g} mm tape" if st.tape_mm else "no tape detected"
        return f"Ready · {tape}" if not st.errors else f"Problem: {', '.join(st.errors)} ({tape})"

    def print(self, labels: list[Label], options: dict | None = None) -> str:
        labels = _check_count(labels)
        s = self.settings().with_options(options)
        with self._lock, self._connect() as sock:
            st = self._ask_status(sock)
            tape = s.tape_mm
            if st:
                if st.errors:
                    raise ToolError(f"The printer reports: {', '.join(st.errors)}.")
                if st.tape_mm and st.tape_mm != tape:
                    if st.tape_mm not in TAPE_CHOICES:
                        raise ToolError(f"The printer has {st.tape_mm:g} mm tape — too narrow for these labels.")
                    tape = st.tape_mm  # print on whatever is loaded
            job = raster_job(render_all(labels, tape, s.hires, logo_image(self.logo_png())), tape, s.hires, s.half_cut, s.auto_cut, s.chain)
            sock.settimeout(30)
            try:
                sock.sendall(job)
            except OSError as e:
                raise ToolError(f"Sending to the printer failed: {e.strerror or e}.") from None
        n = len(labels)
        return f"Sent {n} label{'s' if n != 1 else ''} to the printer ({tape:g} mm tape)."
