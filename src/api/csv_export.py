"""Shared CSV export helpers for the protocol dashboard pages.

Streams rows out of the packets/nodes tables as a downloadable CSV so
captured traffic isn't trapped in the Pi's SQLite. Kept free of FastAPI
imports in the pure helpers (``csv_cell``/``csv_line``/``csv_document``)
so the formatting is unit-testable on the Mac; the ``StreamingResponse``
wrapper is imported lazily inside ``streaming_csv``.

Excel-proofing: UTF-8 with a BOM (the MeshCore roster is full of emoji
and ``☀🔋`` that Excel mangles without it), proper csv quoting, and the
decoded payload carried as one JSON string cell so per-type content
survives without exploding the column set.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Iterable, Sequence

_BOM = "﻿"


def csv_cell(value: Any) -> str:
    """Normalize one value for a CSV cell.

    dict/list -> compact JSON string (decoded_payload); None -> empty;
    everything else -> str. Quoting is handled by ``csv.writer``.
    """
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def csv_line(values: Sequence[Any]) -> str:
    """One CRLF-terminated CSV record (RFC 4180 / Excel-friendly)."""
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerow([csv_cell(v) for v in values])
    return buf.getvalue()


def csv_document(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    """Full CSV text incl. BOM -- convenience for tests/small exports."""
    out = [_BOM, csv_line(header)]
    out.extend(csv_line(r) for r in rows)
    return "".join(out)


def export_filename(device_name: str, dataset: str) -> str:
    """e.g. ``meshpoint-PD2EMC-meshtastic-packets-20260710-1745.csv``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in device_name)
    return f"meshpoint-{safe}-{dataset}-{stamp}.csv"


def streaming_csv(
    header: Sequence[str],
    rows: AsyncIterator[Sequence[Any]],
    filename: str,
):
    """Return a ``StreamingResponse`` that streams the CSV row by row.

    ``rows`` is an async generator so packet exports never buffer the
    whole table -- the caller pages the DB and yields batches.
    """
    from fastapi.responses import StreamingResponse

    async def _gen():
        yield (_BOM + csv_line(header)).encode("utf-8")
        async for row in rows:
            yield csv_line(row).encode("utf-8")

    return StreamingResponse(
        _gen(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


async def stream_query(db, sql: str, params: tuple, columns: Sequence[str],
                       transform=None, batch: int = 500) -> AsyncIterator[list]:
    """Yield one row (list, column order) at a time from a DB query.

    Pages the cursor ``batch`` rows at a time so even a full-table
    packets export holds only a batch in memory. ``transform`` (optional)
    maps a row dict to a row dict before column extraction -- used to
    flatten LoRaWAN's decoded_payload into fcnt/fport/etc.
    """
    cursor = await db.execute(sql, params)
    try:
        while True:
            chunk = await cursor.fetchmany(batch)
            if not chunk:
                break
            for raw in chunk:
                row = dict(raw)
                if transform is not None:
                    row = transform(row)
                yield [row.get(c) for c in columns]
    finally:
        await cursor.close()
