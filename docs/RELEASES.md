# Releases: pinned, signed, and where the code comes from

*November 2026, 0.16.0 (docs/SECURITY_AUDIT.md M5). How a release is made so that what reaches a lab is exactly what
was tested: the packages pinned with their checksums, the release feed signed, and `main` protected on GitHub. The
release steps themselves are in `scripts/release.sh`; the direction is in [FINAL_VERSION.md](FINAL_VERSION.md) §3.*

## 1. The packages: `requirements.lock`

`requirements.txt` says which packages MISTER PLIS needs and from which version (`fastapi>=0.115`). On its own, every
new install would take whatever is newest on PyPI that day — tested or not, and, if a package were ever hijacked, the
hijacked one. **`requirements.lock`** pins every package (and what each needs in turn) to one version, with the
checksums of its files. What installs from it gets exactly those files, or fails:

| Where | How |
|---|---|
| the Docker image | `pip install --require-hashes -r requirements.lock` (Dockerfile) |
| a service or worker set up with `./scripts/setup.sh` | the same |
| a server that updates with git (Sync with git, nightly) | the same, whenever an update changes `requirements.lock` |
| a release | `requirements.lock` is one of its files, with its checksum in the signed feed |
| development (`./scripts/setup.sh --dev`) | `requirements-dev.txt`: the newest versions, to notice early what changes |

**Changing the packages:** edit `requirements.txt`, run `./scripts/lock.sh` (it needs `uv`, which `requirements-dev.txt`
installs), run the tests, read `git diff requirements.lock`, and commit both files. To take newer versions of
everything on purpose, run `./scripts/lock.sh` alone. `tests/test_lock.py` fails when `requirements.txt` asks for a
package or a version the lock file doesn't have. The lock file covers Linux, macOS and Windows and Python 3.11 and
newer.

## 2. The release feed, signed

A server learns about new versions from the **release feed** (`feed-<channel>.json`): the versions, what changed, the
formats each writes, and the checksum of each version's files. Whoever can change the feed could point labs at other
files, so it is **signed** with an SSH key — the kind used for GitHub — and checked by every server against the public
key that is part of its code (`mister_plis/releasekeys.py`), which the place the feed is published can't change.

**Making the release key (once, by the owner):**

```bash
ssh-keygen -t ed25519 -C "MISTER PLIS releases" -f ~/.ssh/mister-plis-release
```

Give it a passphrase, and keep it off servers (on the computer releases are made from, and a copy in a password
manager). Then put the public key into the code, as one line in `SIGNERS` in `mister_plis/releasekeys.py`:

```python
SIGNERS: list[str] = ["ssh-ed25519 AAAA… MISTER PLIS releases"]   # the contents of ~/.ssh/mister-plis-release.pub
```

and release that version. **From then on, servers running it refuse a feed that isn't signed by that key.** Until a
key is there, a feed is read unsigned, and the server's update status says so (`"signed": false` in
`/api/system/updates`).

**Signing a release:** `MISTER_PLIS_SIGNING_KEY=~/.ssh/mister-plis-release ./scripts/release.sh beta` writes
`feed-beta.json.sig` beside the feed (`ssh-keygen -Y sign -n mister-plis-release`). Publish both. To check one by hand:

```bash
echo "release namespaces=\"mister-plis-release\" $(cat ~/.ssh/mister-plis-release.pub)" > /tmp/signers
ssh-keygen -Y verify -f /tmp/signers -I release -n mister-plis-release -s feed-beta.json.sig < feed-beta.json
```

**Changing or losing the key:** add the new public key to `SIGNERS` beside the old one, release, sign with the new key
from then on, and remove the old key a release later. If the private key leaks, remove it from `SIGNERS` in the next
release at once. Servers need `ssh-keygen` to check signatures: it comes with macOS, with Linux's `openssh-client`
(the Docker image has it), and with Windows 10 and newer.

**The Docker image:** give `make_feed.py` the image by its digest (`ghcr.io/<owner>/mister-plis@sha256:…`, from
`docker push`), not by a tag, which can be moved to another image later.

## 3. `main` on GitHub (the owner, in GitHub's settings)

Until labs update from releases, servers that update with git take whatever is on `main` (or the branch they follow),
every night if asked. So whoever can push to `main` can change every such server. In the repository's settings on
github.com:

1. **Settings → Rules → Rulesets → New branch ruleset** for `main` (and any branch a lab's server follows):
   - **Block force pushes** and **Restrict deletions** — history that servers already run can't be rewritten or
     removed;
   - leave *Require a pull request* off while the owner and the coding agents push to `main` directly (CLAUDE.md);
     turn it on if more people get write access.
2. **Settings → Collaborators:** as few people with write access as possible; remove those who no longer need it.
3. **Every account with write access uses two-factor authentication** (each person's GitHub *Settings → Password and
   authentication*). On an organization, require it: *Organization settings → Authentication security*.
4. **Tokens that servers use** (Settings → Server & updates → GitHub access) are fine-grained and **read-only** for the
   code, the tools and the notebook; only the inventory's repository needs write access (docs/DEPLOY_MAC_STUDIO.md).
5. Optional: **sign commits** with the same kind of SSH key (GitHub *Settings → SSH and GPG keys → New SSH key → Signing
   key*; `git config --global gpg.format ssh`, `user.signingkey`, `commit.gpgsign true`), and in the ruleset,
   **Require signed commits**.

A server that updates with git does not check commit signatures itself: these rules are what keeps `main` trustworthy
until labs install signed releases instead.
