"""Contacts -- a local address book for Reticulum peers.

A Reticulum peer only ever tells you the name it announces (or nothing at
all). This module lets the operator pin their own name to a destination
hash -- "Philster", "TechInc BBS", "my other node" -- stored on disk and
shown everywhere that hash appears in the UI. It's local only: nothing is
announced to the network, there's no protocol traffic, and a peer can't
see what you've called them.

The assigned name is stored under the key ``petname`` (the term Sideband /
NomadNet use for exactly this), but nothing user-facing says "petname" --
it's just the contact's name.

One JSON file, ``data/reticulum/contacts.json`` (alongside the identity
and the LXMF store -- the path is derived from ``identity_path``'s
directory in ``state.py`` so it follows a relocated reticulum data dir).
Shape::

    {
      "<destination_hash>": {
        "petname":  "Philster",
        "note":     "voice test peer",
        "trusted":  false,
        "updated":  "2026-09-09T12:00:00+00:00"
      }
    }

FastAPI-free; stdlib only. The route layer (``routes.py``) owns auth and
turns an empty petname into a delete -- this just does validated
load/save. Same load-once-cache-in-memory shape as the SpaceAPI / iCal
feed helpers; the file is small (one line per contact) so a full
rewrite-on-change is fine.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MAX_HASH = 64        # a Reticulum destination hash is 32 hex chars; be lenient but bounded
_MAX_PETNAME = 64
_MAX_NOTE = 280


class ContactStore:
    """Operator petname address book, backed by one JSON file."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._cache: dict[str, dict] | None = None

    # --- reads ------------------------------------------------------------

    def _load(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        data: dict[str, dict] = {}
        try:
            raw = json.loads(self._path.read_text("utf-8"))
            if isinstance(raw, dict):
                for key, val in raw.items():
                    if not isinstance(key, str) or not isinstance(val, dict):
                        continue
                    petname = str(val.get("petname") or "").strip()
                    if not petname:
                        continue
                    data[key] = {
                        "petname": petname[:_MAX_PETNAME],
                        "note": str(val.get("note") or "").strip()[:_MAX_NOTE],
                        "trusted": bool(val.get("trusted")),
                        "updated": str(val.get("updated") or ""),
                    }
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001 -- a hand-corrupted file must not crash the plugin
            logger.warning("contacts: could not parse %s, starting empty", self._path, exc_info=True)
        self._cache = data
        return data

    def all(self) -> dict[str, dict]:
        """Every contact, keyed by destination hash. Fresh dicts -- safe to
        mutate the result."""
        return {k: dict(v) for k, v in self._load().items()}

    def get(self, destination_hash: str) -> dict | None:
        entry = self._load().get(destination_hash)
        return dict(entry) if entry else None

    # --- writes ---------------------------------------------------------

    def set(
        self, destination_hash: str, petname: str,
        note: str = "", trusted: bool = False,
    ) -> dict:
        """Create or replace a contact. Raises ``ValueError`` on an empty
        petname or an over-long field -- the route layer maps a cleared
        petname to :meth:`delete` before it gets here."""
        destination_hash = (destination_hash or "").strip()
        petname = (petname or "").strip()
        note = (note or "").strip()
        if not destination_hash or len(destination_hash) > _MAX_HASH:
            raise ValueError("destination hash missing or too long")
        if not petname:
            raise ValueError("petname is required")
        if len(petname) > _MAX_PETNAME:
            raise ValueError(f"petname too long (max {_MAX_PETNAME})")
        if len(note) > _MAX_NOTE:
            raise ValueError(f"note too long (max {_MAX_NOTE})")

        entry = {
            "petname": petname,
            "note": note,
            "trusted": bool(trusted),
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        data = self._load()
        data[destination_hash] = entry
        self._save(data)
        return dict(entry)

    def delete(self, destination_hash: str) -> bool:
        """Remove a contact. Returns whether it existed."""
        data = self._load()
        if destination_hash not in data:
            return False
        del data[destination_hash]
        self._save(data)
        return True

    def _save(self, data: dict[str, dict]) -> None:
        self._cache = data
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8",
            )
            os.replace(tmp, self._path)
        except Exception:  # noqa: BLE001 -- keep the in-memory copy even if disk write fails
            logger.warning("contacts: could not write %s", self._path, exc_info=True)
