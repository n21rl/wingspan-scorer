"""Where player pictures live, and how a stored avatar becomes a real file.

Two directories are in play. The bundled one ships with the code and holds the
placeholder plus any pictures committed to the repository. The upload directory
is writable and is where new uploads go; in a container it points at a mounted
volume, because the image's own filesystem is thrown away on every deploy.

Everything resolves through `resolve()`, which returns None rather than a path
that is not there -- a missing file handed to `st.image` is a crashed page, not
a missing picture.
"""

from __future__ import annotations

import os
from pathlib import Path

from wingspan.db import ROOT

#: Pictures that ship with the code, including the placeholder.
BUNDLED_DIR = ROOT / "images"

DEFAULT_AVATAR_NAME = "_default.png"


def upload_dir() -> Path:
    """The writable directory new uploads are written to.

    $WINGSPAN_IMAGES wins -- on Fly that points into the mounted volume, so
    uploaded pictures survive a redeploy the way the database does. Without it,
    uploads sit beside the bundled ones, which is what a local checkout wants.

    Read at call time, not import time, so tests and deployments can move it.
    """
    env = os.environ.get("WINGSPAN_IMAGES")
    return Path(env) if env else BUNDLED_DIR


def search_dirs() -> list[Path]:
    """Where to look for a picture, most specific first."""
    directories = [upload_dir()]
    if BUNDLED_DIR not in directories:
        directories.append(BUNDLED_DIR)
    return directories


def _find(name: str) -> Path | None:
    for directory in search_dirs():
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def default_avatar() -> Path | None:
    """The placeholder, or None if it did not make it into the deployment."""
    return _find(DEFAULT_AVATAR_NAME)


def resolve(avatar: str | None) -> Path | None:
    """Turn a stored avatar value into a file that exists, or None.

    Avatars are stored as a bare filename. The old app stored Windows-style
    paths, which never resolved on any other platform and left every player
    showing the placeholder, so only the final component is trusted.
    """
    if avatar:
        found = _find(Path(str(avatar).replace("\\", "/")).name)
        if found is not None:
            return found
    return default_avatar()


def save(player_id: str, filename: str, data: bytes) -> str:
    """Store an uploaded picture and return the name to keep on the player."""
    directory = upload_dir()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{player_id}_{Path(filename).name}"
    (directory / name).write_bytes(data)
    return name
