"""Backup archive manifest (format version 1)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

FORMAT_VERSION = 1


@dataclass(frozen=True)
class BackupFileEntry:
    """One file inside the backup archive."""

    path: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BackupFileEntry:
        return cls(
            path=str(raw["path"]),
            sha256=str(raw["sha256"]),
            size_bytes=int(raw["size_bytes"]),
        )


@dataclass
class BackupManifest:
    """Metadata describing a Meshpoint backup archive."""

    format_version: int
    meshpoint_version: str
    created_at: str
    device_id: str
    device_name: str
    entries: list[BackupFileEntry] = field(default_factory=list)
    total_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "meshpoint_version": self.meshpoint_version,
            "created_at": self.created_at,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "entries": [entry.to_dict() for entry in self.entries],
            "total_bytes": self.total_bytes,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> BackupManifest:
        entries = [
            BackupFileEntry.from_dict(item)
            for item in raw.get("entries", [])
        ]
        return cls(
            format_version=int(raw["format_version"]),
            meshpoint_version=str(raw["meshpoint_version"]),
            created_at=str(raw["created_at"]),
            device_id=str(raw["device_id"]),
            device_name=str(raw.get("device_name", "")),
            entries=entries,
            total_bytes=int(raw.get("total_bytes", 0)),
        )

    @classmethod
    def from_json(cls, text: str) -> BackupManifest:
        return cls.from_dict(json.loads(text))
