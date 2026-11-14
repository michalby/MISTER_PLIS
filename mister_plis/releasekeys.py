"""Who may sign MISTER PLIS's releases (docs/RELEASES.md; docs/SECURITY_AUDIT.md M5).

A release feed says which versions exist and the checksum of each one's files. It is signed with an SSH key
(``ssh-keygen -Y sign``, the kind of key people use for GitHub): ``feed-<channel>.json`` comes with
``feed-<channel>.json.sig``. A server checks the signature against the public keys below — part of the code it runs,
so whoever controls the place the feed is published can't change them. With at least one key here, a feed that isn't
signed by one of them is refused; with none (until the owner makes the release key, F2), a feed is read unsigned and
says so.

Each entry is a public key, as in ``~/.ssh/<key>.pub``: ``"ssh-ed25519 AAAA… MISTER PLIS releases"``.
"""

from __future__ import annotations

NAMESPACE = "mister-plis-release"  # what a signature is for (ssh-keygen -n): a key's other signatures don't count here

SIGNERS: list[str] = []
