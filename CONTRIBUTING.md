# Contributing

Thank you for helping. The short version:

1. **Make a branch** for your change: in your **fork** of this repository (or, for its maintainers, in the repository
   itself).
2. Set it up for development: `./scripts/setup.sh --dev`, then run the tests: `.venv/bin/python -m pytest`.
3. Open a **pull request into `beta`** (never into `stable`). Say what a lab will notice, and add a line to
   `CHANGELOG.md` under a new version (see "Versions" in CLAUDE.md).
4. Once `beta` has run for a while without trouble, it goes to `stable` by a pull request.

## Branches

| Branch | Who runs it | How code gets there |
|---|---|---|
| `stable` | labs (the default branch) | a pull request from `beta`, after testing |
| `beta` | labs that test new versions | pull requests from branches and forks |

A server follows the branch it was cloned with. Settings → Server & updates → *Run another branch* switches it, e.g.
to `beta` for a test computer.

## Rules that keep labs safe

- **Never break a lab's data.** Every file format is in docs/FORMATS.md; add a reader for a new one, never change an
  old one. The frozen fixtures in `tests/fixtures/*_v0/` must stay readable.
- **No lab in the code.** A lab's repositories, folders and printer come from its lab file or the Settings page.
- **Tools live in tool sources**, not here (docs/ADDING_TOOLS.md). Tools use only `mister_plis.toolkit`.
- Never put a token, password or a lab's data in a commit.

Contributions are under the project's licence, the GNU General Public License v3.0 or later (LICENSE).

Security problems: please don't open a public issue — write to the maintainers first (see the repository's
*Security* tab).
