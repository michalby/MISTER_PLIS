# Plan: one Settings page with tabs

*November 2026. Status: **done** (8 November 2026; the log is at the end). Decisions in §8. Replaces the two pages **Settings**
(`/settings`) and **System & updates** (`/system`) with one page, **Settings**, split into tabs that switch
instantly, plus a page of its own for **Feedback**. Adds settings that a tool declares itself (first: the Blender
program).*

## 1. Why: what is mixed up today

| Problem | Where |
|---|---|
| Per-browser settings (your name, theme, numbers) and lab-wide ones (backup folder, label printer, inventory columns) sit side by side on one page, told apart only by a small "whole lab" tag. | Settings |
| Jobs are split over two pages: **Job storage** (where jobs live) is on System, **Results & backup** (how long they stay, where they are copied, clearing history) is on Settings. Time Machine's backup (on System) says "see Settings → Results & backup". | both |
| System holds things that aren't about the server: **People** (names, merging), **Feedback from the lab** (a to-do list), the inventory's sync, history and tidy-up, the notebook's sync and folders. | System |
| The inventory is on both pages: sync, history and tidy-up on System, its columns on Settings. | both |
| A tool's need shows up in the base: the **Blender** line in the Server panel, and Blender's own search paths in `config.py` (a copy of the tool's). A tool can't say "I need this set up" anywhere except `config.toml`. | System, `config.py` |
| Export and printing settings are spread out: Excel number format and PNG size under "Numbers" and "Plots" (this browser), the label printer under its own panel (whole lab). | Settings |
| The sidebar has two links (Settings, System & updates); the open-feedback counter sits on "System & updates". | sidebar |

## 2. The new page

Two sidebar links replace the two of today: **Settings** (a page with tabs) and **Feedback** (§2a).

**The tabs switch instantly, inside the page.** Every tab is in the page from the start; pressing a tab shows it
and hides the others without reloading. The page still behaves like separate addresses where it matters:

- The address follows the tab (`/settings#you`, `/settings#tools`, …), so a tab can be bookmarked or linked from a
  message, opening the page on that tab. The back button goes to the tab before.
- **A tab loads its data the first time it is opened**, not when the page opens. The Server tab's check with
  GitHub, the tool sources' status, the inventory's sync status only run when someone looks at them, so opening
  Settings stays fast. A tab that was opened once keeps what it loaded; its own buttons refresh it.
- Tabs that only show settings drawn by the server (You, Exports & printing) need no loading at all.
- Without JavaScript, all tabs are shown one under the other, each with its heading, so the page still works.
- `/settings` with no `#…` opens **You**.

Every setting says whom it affects, with the same two tags everywhere: **this browser** or **whole lab**. Tabs are
ordered from "me" to "the lab" to "the machine".

### The tabs

| # | Tab | Link | What is in it (from where today) | Scope |
|---|---|---|---|---|
| 1 | **You** | `#you` | Your name (Settings → You) · Language, Theme (Appearance) · Decimal separator on screen (Numbers) · Remember inputs, Forget data saved in this browser (Forms) | this browser |
| 2 | **Exports & printing** | `#exports` | *Files:* Numbers in Excel and .csv files (Numbers) · PNG resolution of plots (Plots). *Label printer:* address, tape, resolution, half/auto cut, chain, Check printer (Label printer). | files: this browser · printer: whole lab |
| 3 | **Tools** | `#tools` | *Tool sources* (System) · *Broken tools* and their errors (today only a count in the Server panel) · *Settings of each tool* that declares some (new, §4; first: Blender render → the Blender program, replacing the Blender line of the Server panel) | whole lab |
| 4 | **Jobs & backup** | `#jobs` | *Where jobs are kept:* the storage folder, "Use another folder" (System → Job storage) and how long results stay (Settings → Results & backup) · *Backup:* backup folder, back up after, status, Back up now / Check / Update old backups (Results & backup) · *Clear job history* (Results & backup) · module panels about backups: *Time Machine: its own backup* (System) | whole lab |
| 5… | **one tab per module that has settings** | `#<module id>` | **Reagents & consumables** (`inventory`): GitHub sync, recent changes, tidy-up by a local model (System) and the columns of both inventories (Settings). **Lab notebook** (`notebook`): sync, sync by itself, folders shown to the lab (System). Time Machine has no tab of its own: its one panel is a backup, so it joins tab 4. | whole lab |
| n−1 | **People** | `#people` | Names, counts, opening someone's jobs, merging two names (System → People) | whole lab |
| n | **Server & updates** | `#server` | Version: Check / Sync with git, Run another branch, Update by itself (System → Version) · Server: address to open, uptime, running jobs, disk, data folder, Python, system, Restart (System → Server, without the Blender line) | whole lab |

With `modules = "none"` the module tabs are simply not there; with every module on, the page has 8 tabs.
On a phone the tab row scrolls sideways (no wrapping into three lines).

### 2a. Feedback: a page of its own

**Feedback** gets its own sidebar link and page, `/feedback`, holding everything about feedback in one place: the
whole list from the lab (bugs, inconveniences, ideas), the kind filters, Show done, Copy as a list, marking done and
deleting — what is the "Feedback from the lab" panel on System today, given the full width of a page. The
open-feedback counter moves from the "System & updates" link to the **Feedback** link. Sending feedback doesn't
change: the glowing button at the top of every page, which also gets a "See all feedback" link to the page.
`/system#feedback` leads there.

### Within a tab

- Panels stay as they are (`panel`, `panel-head`, the `setting` rows with label, help and control), so no setting
  is redesigned in this work, only moved. Where two panels now say the same thing (the storage folder and "where
  results are kept"), they are merged into one.
- A tab whose content is long gets the same short lede under the tab row that the other pages have ("Your settings
  apply to this browser and are kept in cookies…" on You; "These apply to everyone in the lab…" on the lab tabs).

### Tab style for the whole site

The underline tabs exist only in the inventory today (`.rg-tabs` / `.rg-tab` in `modules/inventory/static/reagents.css`,
coloured with the inventory's green). They become a base component in `mister_plis/static/css/app.css`:
`.tabs` / `.tab` / `.tab.active` / `.tab-n` (the small count bubble), coloured with the base's accent. The inventory
keeps its colour by setting two CSS variables on its own page (`--tab-ink`, `--tab-line`) and switches its markup to
the base classes, so both look the same and are kept in one place. A Jinja macro `tabs(items, active)` in
`templates/partials/tabs.html` draws them. The same look serves two kinds of tabs: links to other pages (Reagents,
`aria-current="page"`) and tabs inside a page (Settings: `role="tablist"` / `role="tab"` / `role="tabpanel"`,
arrow keys move between tabs). A small `MP.tabs(element)` in `app.js` does the switching, the address, the back
button and the "opened for the first time" event, so any page can use it later.

### Old addresses keep working

| Old | New |
|---|---|
| `/system` | `/settings#server` (a 307 redirect) |
| `/system#tool-sources` | `/settings#tools` |
| `/system#storage` | `/settings#jobs` |
| `/system#people` | `/settings#people` |
| `/system#feedback` | `/feedback` |
| `/system#reagents` (also from `/reagents/setup`, `/consumables/setup`) | `/settings#inventory` |
| `/settings#lab-panel`, `#printer-panel` | `/settings#jobs`, `/settings#exports` |

A browser keeps the `#…` of the old address across a redirect, so `/system#storage` arrives as
`/settings#storage`; the tab script knows the old names and opens the right tab (and sends `#feedback` on to
`/feedback`). Every link in the code moves to the new address (§5, S5), so the old ones are only for bookmarks and
old messages.

## 3. How modules join in

Today a module adds panels to two places, `panels={"system": [...], "settings": [...]}`, and scripts for the page kinds
`"system"` and `"settings"`. The base must keep not naming its modules (`tests/test_modules.py`).

New, in `mister_plis/modules.py` (module `API` stays 1: everything is optional and old declarations keep working):

```python
@dataclass
class SettingsTab:
    """A tab of its own on the Settings page: /settings#<module id>."""
    label: str              # "Reagents & consumables"
    icon: str = "grid"
    order: int = 50         # between Jobs & backup (40) and People (80)
    visible: Callable[[], bool] | None = None

Module(
    ...,
    settings_tab=SettingsTab("Reagents & consumables", icon="flask", order=50),
    panels={"settings": ["panels/sync.html", "panels/columns.html"],   # → the module's own tab
            "settings:jobs": [...]},                                    # → a base tab, by its id
    scripts={"settings": ["reagents_admin.js"]},                        # on the module's tab only
)
```

- `panels["settings"]` goes to the module's own tab when it has a `settings_tab`, else to the end of
  **Server & updates**, so nothing gets lost. `panels["settings:<tab id>"]` puts a panel on a base tab
  (`you`, `exports`, `tools`, `jobs`, `people`, `server`). Time Machine uses `"settings:jobs"`.
- Scripts are loaded with the page; a module's script starts its work when its tab is opened for the first time
  (the `mp:tab-open` event with the tab's id), not when the page loads.
- The old key `"system"` is read as `"settings"` (so the test module in `tests/fixtures/modules/hello` and any
  module written for API 1 keep working).
- Scripts for `"settings"` (and the old `"system"` key) load on the Settings page when the module has a panel there.
- `Hooks.people` / `rename_person` are unchanged; only their wording ("System & updates → People") is updated.

## 4. Settings of a tool

### What a tool author writes

```python
from mister_plis.toolkit import Tool, find_program, tool_setting, inputs as I

BLENDER_CANDIDATES = ["/Applications/Blender.app/Contents/MacOS/Blender", ...]

def find_blender():
    return find_program("blender", BLENDER_CANDIDATES, configured=tool_setting("blender-render", "program"))

tool = Tool(
    id="blender-render",
    ...,
    settings=[I.Text("program", "Blender program", placeholder="/Applications/Blender.app/Contents/MacOS/Blender",
                     help="Leave empty to look in the usual places. Needed only if Blender is somewhere else.")],
    settings_status=lambda: (f"Found: {p}" if (p := find_blender()) else "Blender was not found on the server."),
    available=lambda: None if find_blender() else "Blender was not found. Set it in Settings → Tools.",
)
```

- `settings`: a list of the same inputs a form uses (`I.Text`, `I.Number`, `I.Choice`, `I.Checkbox`, …), so the
  Tools tab draws them with the code that draws tool forms, in both languages, and checks values the same way.
- They are **lab-wide** and belong to **this server** (a path to a program is about this machine), so they are kept
  in the data folder, not in the storage folder that moves between machines:
  `<data>/tool-settings/<tool id>.json` = `{"format": 1, "values": {...}, "changed_by": "...", "changed_at": ...}`.
  Described in `docs/FORMATS.md`. A tool that disappears leaves its file alone (it comes back with the tool).
- `tool_setting(tool_id, name)` reads a value (the input's default when nothing is saved). The run context gets
  the same as `ctx.setting(name)` for the tool being run.
- `settings_status` (optional): one line shown under the tool's settings, recomputed when the tab is opened and when
  **Check** is pressed — for Blender: where it was found, or that it wasn't.
- `find_program(name, candidates, configured="")`: the configured path (tool setting) wins, then `<name>_path` in
  config.toml (still read, so nothing breaks on the lab server), then the candidates, then the PATH.
- Per-person preferences of a tool stay what they are today: the form remembers its last inputs per browser.

### On the Tools tab

```
Tool sources                         (as today: lab, others; Check / Update / Branch / Pin / Remove; Add)
Broken tools                         (only when there are some: the tool, its source, the error)
Settings of the tools                (one block per tool that declares settings, grouped by tool source)
  ▸ Blender render · lab             Blender program  [ /Applications/…/Blender        ] [Save] [Check]
                                     Found: /Applications/Blender.app/Contents/MacOS/Blender
```

New API: `GET /api/tools/settings` (every tool with settings: spec, values, status), `POST /api/tools/{id}/settings`
(save; checked like a form; records who changed it), `POST /api/tools/{id}/settings/check` (the status line).

### Shared settings tools already use

Tools don't declare export and printing settings: the base applies them to every tool's results, and a tool can
read them with `pref(...)` as today (`decimal`, `xlsx_numbers`, `plot_scale`). They all move to the **Exports &
printing** tab, with the label printer that every labelling tool (Molar and Stock solution, …) prints to.

### Toolkit version

`settings`, `settings_status`, `tool_setting`, `ctx.setting` and `find_program(configured=)` are new parts of the
tools' API. An older MISTER PLIS would fail on a tool that uses them (an unknown `Tool(settings=…)`), so the
version must say so without breaking the lab's manifest (`requires_toolkit = ">=1,<2"`):

- `TOOLKIT_API` stays the number `1` (a tool may compare it), and a new `TOOLKIT_VERSION = "1.1"` says which
  additions are there (new names only, nothing removed or changed). `toolkit_ok` matches manifests against
  `TOOLKIT_VERSION` and learns versions with a minor number; `">=1,<2"` still matches 1.1, so every existing tool
  source keeps loading.
- A tool source that uses tool settings asks for `requires_toolkit = ">=1.1,<2"`. An older server can't read that
  version and doesn't load the source, with a clear message on the Tools tab — the right outcome.
- `docs/ADDING_TOOLS.md` gets a "Settings of a tool" section and the new names in the API table;
  `tests/test_tool_boundary.py` and the tools repository's `tests/test_boundary.py` learn the new names.

### Blender leaves the base

- `mister_plis/config.py`: `BLENDER_CANDIDATES` and `Settings.find_blender()` are removed; `blender_path` stays a
  known setting (read by `find_program`), documented as the old way.
- The Server panel loses its Blender line; `/api/system` loses `"blender"`.
- In `smith-lab/lab-tools`: `blender_render.py` declares its setting and status as above; its manifest asks for
  `>=1.1,<2`; its test covers "not found" and "set by hand". Pushed **after** the base is on `main` and on the lab
  server, so the server never sees a tool source it can't load.

## 5. Work, in order

Each step is one commit (or a few), tests green, pushed to the working branch and `main`.

**S1 — the tab component.** `.tabs` / `.tab` in `app.css` and `partials/tabs.html`; the inventory switches to them
(its look unchanged). *Done when:* the Reagents page looks the same in light and dark (screenshot before/after).

**S2 — one page, tabs, nothing moved yet.** `MP.tabs` in `app.js` (switching, address, back button, first-open
event, arrow keys). `settings.html` becomes the frame (header, tab row) including one template per tab
(`templates/settings/you.html`, `exports.html`, `tools.html`, `jobs.html`, `people.html`, `server.html`); the existing
panels are moved into them as they are (Settings' panels, then System's). `system.html` goes away; `system.js` and
the settings part of `app.js` become one `settings.js` whose parts start on `mp:tab-open` instead of on page load
(so the Server tab asks GitHub only when opened). `/system` redirects.
*Done when:* every control works on its new tab; switching is instant; reloading keeps the tab; back goes to the
previous tab; old fragments land on the right tab; the GitHub check runs only once Server is opened.

**S3 — modules on tabs.** `SettingsTab`, the `settings` / `settings:<tab>` panel keys, scripts per tab, the old
`"system"` key read as `"settings"` (§3). The inventory gets its tab (its System and Settings panels together), the
notebook gets its tab, Time Machine's backup panel goes to Jobs & backup.
*Done when:* `modules = "none"` shows the six base tabs only; `tests/test_modules.py` passes unchanged in what it
forbids; the `hello` test module still shows its panel.

**S4 — the Feedback page.** `/feedback` (`templates/feedback.html`, the list code moved out of `system.js` into
`feedback.js`, which already holds the send button). Sidebar: **Settings** and **Feedback** in place of Settings and
System & updates; the open-feedback counter on Feedback; "See all feedback" in the send pop-up.
*Done when:* everything the System panel did works on the page; the counter updates as before.

**S4b — merge and tidy.** One "Where jobs are kept" block (storage folder + how long results stay); the Files part
of Exports & printing; Broken tools listed on the Tools tab.

**S5 — every link and text.** All links move to the new addresses, and all texts that name a place
("Settings → Results & backup", "System & updates → Tool sources", "Sync notes on System & updates", …) are
rewritten as "Settings → Jobs & backup" etc., with their Polish. List of places, from a search:

- base: `templates/base.html` (sidebar, name chip), `templates/home.html` (`/system#tool-sources`),
  `static/js/tool.js`, `static/js/feedback.js` (`/settings` for the name → `/settings#you`), `static/js/jobs.js`,
  `static/js/label.js`, `labels.py`, `backup.py`, `storage.py`, `toolsources.py`, `config.py`, `people.py`,
  `prefs.py`, `modules.py`, `app.py` messages;
- modules: `inventory/static/reagents.js` (`/system#reagents`, `/settings`), `inventory/web.py` (redirects),
  `inventory/service.py`, `notebook/static/notes.js`, `notebook/templates/notes.html`, `notebook/service.py`,
  `timemachine/templates/panels/system.html`, `timemachine/static/tm-system.js`;
- docs: `README.md`, `docs/ARCHITECTURE.md`, `docs/MODULES.md`, `docs/ADDING_TOOLS.md`, `docs/DEPLOY_MAC_STUDIO.md`,
  `docs/FORMATS.md`, the modules' `MODULE.md` (the reorg history files stay as written).

*Done when:* a search for `"/system"`, `System & updates` and the old panel names finds only the redirects and
history docs; `tests/test_i18n.py` passes (every new text has Polish); the old Polish entries nothing uses are
removed (the stale-text check from the last clean-up, run again).

**S6 — settings of a tool.** Toolkit 1.1 (`TOOLKIT_VERSION`, §4): `Tool.settings`, `settings_status`, `tool_setting`, `ctx.setting`,
`find_program(configured=)`, the store in `<data>/tool-settings/`, the three API routes, the block on the Tools tab.
A test tool in `tests/fixtures/toolsource/` gets a setting, so the base's tests cover it; `toolkit_ok` tests for
minor versions. Blender's copy leaves `config.py` and the Server panel.
*Done when:* the tests pass; an old manifest (`>=1,<2`) still loads; one asking `>=1.1,<2` loads here and an old
base refuses it with a message.

**S7 — the tools repository.** `blender_render.py` with its setting and status; manifest `>=1.1,<2`; its tests run
by hand against the base's `main`. Pushed once S6 is on the lab server.

**S8 — check it as a person would.** Screenshots of every tab and of the Feedback page in light and dark, on a
wide screen and a phone (Playwright); the Polish interface on each tab; keyboard: tabs reachable with Tab, arrow
keys between them, the active tab announced. The
architecture doc's table of the base gets the new templates and `tool-settings`.

## 6. Tests to add or change

- `tests/test_settings_page.py` (new): the page holds every tab and its panels; `/system` → `/settings#server`; the
  module tabs appear only when their module is on; a browser test (Playwright) for switching, the address, back,
  reload and the old fragments, and that the Server tab's check isn't requested before the tab is opened.
- `tests/test_feedback.py`: the `/feedback` page; the counter on the sidebar link.
- `tests/test_modules.py`: a module with `settings_tab` gets its tab; `panels["settings:jobs"]` lands on Jobs
  & backup; the old `"system"` key still shows its panel.
- `tests/test_tool_settings.py` (new): save and read a value; bad values refused like a form; `settings_status`;
  `find_program` order (tool setting, then config.toml, then candidates, then PATH); a removed tool keeps its file.
- `tests/test_toolsources.py`: `toolkit_ok` with `"1.1"`, `">=1,<2"`, `">=1.1,<2"`, `">=1.2"`.
- Module tests that fetch `/system` or `/settings` (inventory, notebook, Time Machine) move to the new addresses.
- `tests/test_i18n.py` already covers the new texts.

## 7. What does not change

- No setting changes its meaning, its default or where it is stored (cookies, `data/lab.json`, the printer's file,
  the modules' own files, `data/storage.json`, `config.toml`). Only pages and links move, plus the new tool-settings
  file. No data is migrated, so nothing on the lab server needs copying.
- No logins: lab-wide settings stay editable by everyone, as now. (If that should change, it is a separate piece of
  work: a lab password for the lab-wide tabs.)
- Feedback is still sent with the button at the top of every page; only its list moves (to its own page).

## 8. Decisions (the owner, 8 November 2026)

1. **Tabs switch instantly inside the page** (not one address per tab). To keep it fast, each tab loads its data
   the first time it is opened; the address still follows the tab (§2).
2. **Feedback gets its own page and sidebar link**, with all of feedback on it (§2a). People stays in Settings.
3. **One tab per module** (Reagents & consumables, Lab notebook).
4. **Still open: the lab's name.** `lab_name` is the small line under "MISTER PLIS" at the top of the sidebar
   ("lab toolbox" when it isn't set). It is also printed on the PDF reports and written into the backups' README
   files. Today it can only be changed in `config.toml` on the server. Option: make it editable on Server & updates
   (whole lab; `config.toml` would still work as the default).

   **Decided:** yes — set on Settings → Server & updates → The lab, for everyone; `lab_name` in config.toml stays the
   default.

## 9. Log

- 2026-11-08: **done**, on `claude/busy-mayer-tivrwr` → `main`.
  - S1: `.tabs` / `.tab` / `.tab-n` in `app.css`; the inventory's tabs use them (pixel-identical before/after).
    `MP.tabs` and `MP.whenShown` in `app.js`.
  - S2–S4: `templates/settings.html` with `templates/settings/<tab>.html`; `static/js/settings.js` (was `system.js`,
    plus the Settings part of `app.js`); `/system` → `/settings?tab=server` (a 307 without a fragment, so the browser
    keeps an old `#storage`); a fragment naming an element inside a tab opens that tab, so every old anchor works
    without a list. `SettingsTab` and `panels["settings:<tab>"]` in `modules.py` (module API unchanged at 1).
    `/feedback` page; the sidebar has Feedback (with the open count) and Settings.
  - Lab name: `lab_name` in `lab_settings.json`, `POST /api/lab/name`.
  - S5: every link and text, with Polish; the i18n test now also reads templates in subfolders.
    `.panel-text` moved into the base's CSS (it came from the notebook's, so the base's panels lost their padding
    with the notebook off). The inventory gets its own "Molar mass" in Polish (it borrowed a tool's).
  - S6: `toolsettings.py`, `Tool.settings` / `settings_status`, `tool_setting`, `ctx.setting`,
    `find_program(configured=)`, `TOOLKIT_VERSION = "1.1"` (`TOOLKIT_API` stays 1); `toolkit_ok` reads minor
    versions. `GET /api/tools/settings`, `POST /api/tools/{id}/settings` (Check reloads the list, so no third route).
    A tool translates its own status line with `tr`. Blender left `config.py` and the Server panel.
  - S7: `smith-lab/lab-tools` `main`: Blender render's "Blender program" setting and status, and a test. It
    imports `tool_setting` in `try: … except ImportError`, so on an older base it loads as before (config.toml's
    `blender_path`) and the manifest keeps `>=1,<2`: the lab server never refuses the source, whatever order the two
    repositories are updated in. The tools' boundary test allows such a guarded import.
  - Other tools: none needs a setting today. Only Blender render runs an external program; the scale-bar reader uses
    macOS text recognition when it is there (nothing to set). Everything else is a per-run choice (forms remember
    their last inputs per browser) or a list the lab saves from the tool's own form (compounds, assay methods).
    A possible later one: lab-wide default coefficients for Chlorophyll concentration, if the lab settles on others
    than the built-in ones.
  - S8: `tests/test_settings_page.py`, `tests/test_settings_browser.py` (Playwright; skipped without it),
    `toolkit_ok` cases; screenshots of every tab in light, dark, on a phone and in Polish.

