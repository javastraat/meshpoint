"""Rolling history of dashboard update applies and rollbacks.

The Updates page shows the last few apply/rollback events on this box
(when, from which SHA to which, success or failed step). Git log can
show what commits exist but not *when this gateway* took them, nor
failed attempts -- so each apply/rollback appends one entry here.

Same defensive posture as ``rollback_state``: a corrupt or missing
file is never fatal, history is best-effort.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = Path("/opt/meshpoint/data/update_history.json")
MAX_ENTRIES = 20


def resolve_history_path(rollback_state_path: Path) -> Path:
    """History lives next to the rollback-state file in ``data/``."""
    return rollback_state_path.parent / "update_history.json"


def read_history(
    path: Path = DEFAULT_HISTORY_PATH,
    *,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Return persisted history entries, newest first. Never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("update_history: could not read %s: %s", path, exc)
        return []
    if not isinstance(data, list):
        return []
    entries = [e for e in data if isinstance(e, dict)]
    if limit is not None:
        entries = entries[: max(0, limit)]
    return entries


def append_history_entry(
    entry: dict[str, Any],
    *,
    path: Path = DEFAULT_HISTORY_PATH,
) -> bool:
    """Prepend one apply/rollback event, capped at ``MAX_ENTRIES``."""
    record = {"at": datetime.now(timezone.utc).isoformat(), **entry}
    entries = [record, *read_history(path)][:MAX_ENTRIES]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(entries, separators=(",", ":")),
            encoding="utf-8",
        )
        return True
    except OSError as exc:
        logger.warning("update_history: could not write %s: %s", path, exc)
        return False
