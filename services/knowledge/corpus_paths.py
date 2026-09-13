"""Single source of truth for where the arena corpus lives.

The host/container trap this exists to prevent: on the Proxmox host the Synology
share is mounted at ``/mnt/sovereign-ai``, but inside the gateway container the
same share is mounted at ``/mnt/sovereign-memory`` — and ``/mnt/sovereign-ai``
there is a *local* directory.  Every component (arena, gateway, promotion tools)
runs inside the container, so a default written for the host silently produced a
decoy tree on container-local disk: increments were built and even promoted, but
never reached the NAS and the /corpus page reported nothing.

Defaults below are therefore the CONTAINER paths, and both can be overridden by
environment so a host-side run stays possible.
"""

from __future__ import annotations

import os
from pathlib import Path

CONTAINER_SHARE = "/mnt/sovereign-memory"
RAW_ARENA_ENV = "SOVEREIGN_CORPUS_RAW_ROOT"
VALIDATED_ARENA_ENV = "SOVEREIGN_CORPUS_VALIDATED_ROOT"


def raw_arena_root() -> Path:
    return Path(os.environ.get(RAW_ARENA_ENV, f"{CONTAINER_SHARE}/raw/corpus/arena"))


def validated_arena_root() -> Path:
    return Path(os.environ.get(VALIDATED_ARENA_ENV, f"{CONTAINER_SHARE}/validated/corpus/arena-increments"))


class ShareNotMounted(RuntimeError):
    """The corpus root's share is not mounted, so writing would create a decoy tree."""


def require_share(root: Path) -> Path:
    """Refuse to write a corpus tree onto an unmounted or wrong path.

    We check the grandparent (``…/raw`` for ``…/raw/corpus/arena``): it belongs to
    the share and must already exist.  Creating it ourselves is what previously
    produced a local look-alike tree that nothing else could see.
    """
    root = Path(root)
    if len(root.parents) < 2:
        raise ShareNotMounted(f"chemin de corpus inattendu : {root}")
    anchor = root.parents[1]
    if not anchor.is_dir():
        raise ShareNotMounted(
            f"refus d'écrire dans {root} : {anchor} n'existe pas — le partage est-il monté ? "
            f"(dans le conteneur le partage est {CONTAINER_SHARE}, sur l'hôte /mnt/sovereign-ai)"
        )
    return root
