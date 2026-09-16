"""On-disk storage for LXMF image attachments (Send tab, ``FIELD_IMAGE``).

Deliberately off the shared ``messages`` SQLite table -- only a small
JSON descriptor (``{kind, id, mime, size}``) goes in the ``attachments``
column there; the actual bytes live under ``state.attachments_dir()``
(``<reticulum data dir>/attachments/``), same storage-hygiene reasoning
as keeping hosted ``.mu`` pages as real files (``node_pages.py``) rather
than blobs in config.

Each attachment gets a random hex id used both as the on-disk filename
stem and the ``/api/reticulum/attachments/{id}`` URL segment. This is
deliberately *not* the message row id: an outbound image is written to
disk before ``save_sent()`` returns a row id (LXMF fields are attached
before the DB insert happens at all), so a message-id-keyed path would
need a second UPDATE after the fact. A random id works uniformly for
both the send and receive paths with no ordering dependency.

Image-only for now (LXMF's ``FIELD_FILE_ATTACHMENTS`` is a follow-up,
see memory/reticulum_todo.md item 1) -- ``kind`` is always ``"image"``,
but stored as an array in the DB column so a future attachment kind
doesn't need its own migration.
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

# Matches the ~5 MB cap agreed for the Send tab's image attachments --
# generous enough for a phone photo at moderate quality, small enough
# that a handful of them won't meaningfully dent a Pi's SD card.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# LXMF's FIELD_IMAGE carries the image type as a bare extension-like
# string ("jpg", "png", "webp", ...) -- matches what reticulum-meshchat's
# own web UI sends (file.type.replace("image/", "")), not a full MIME
# type. Map the common ones back to a real MIME type for the Content-Type
# header when serving; anything unrecognized still round-trips (stored
# and served with the extension as-is) via the octet-stream fallback.
_MIME_BY_TYPE = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


def mime_for_image_type(image_type: str) -> str:
    return _MIME_BY_TYPE.get((image_type or "").strip().lower(), "application/octet-stream")


def dir_from_identity_path(identity_path: str) -> str:
    """Where attachments live for a given identity -- next to it, same as
    ``state.contacts_path()`` places ``contacts.json``. The one place this
    join happens: both ``state.attachments_dir()`` (routes.py's GET
    endpoint) and ``LxmfService._attachments_dir()`` (send/receive) call
    through here rather than each re-deriving it, so the two can't
    silently drift onto different paths."""
    return str(Path(identity_path).parent / "attachments")


def save_image(attachments_dir: str, image_type: str, image_bytes: bytes) -> dict:
    """Writes *image_bytes* to ``<attachments_dir>/<id>.<ext>`` and
    returns the descriptor to store in the messages.attachments column:
    ``{"kind": "image", "id": ..., "mime": ..., "size": ...}``."""
    ext = (image_type or "").strip().lower().lstrip(".")
    ext = ext if re.fullmatch(r"[a-z0-9]{1,8}", ext) else "bin"
    token = secrets.token_hex(16)
    directory = Path(attachments_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{token}.{ext}").write_bytes(image_bytes)
    return {
        "kind": "image",
        "id": token,
        "mime": mime_for_image_type(image_type),
        "size": len(image_bytes),
    }


def read_image(attachments_dir: str, attachment_id: str) -> tuple[bytes, str] | None:
    """Returns ``(bytes, mime)`` for a previously-saved attachment, or
    ``None`` if it doesn't exist. *attachment_id* is validated as a bare
    hex token before it ever touches the filesystem -- never built into
    a path from unsanitized input, even though callers only ever pass a
    value already stored server-side."""
    if not _ID_RE.match(attachment_id or ""):
        return None
    directory = Path(attachments_dir)
    for candidate in sorted(directory.glob(f"{attachment_id}.*")):
        if not candidate.is_file():
            continue
        return candidate.read_bytes(), mime_for_image_type(candidate.suffix.lstrip("."))
    return None
