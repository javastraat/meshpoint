"""CSV export formatting helpers (Mac-runnable, no fastapi/DB)."""

import asyncio
import unittest

from src.api.csv_export import (
    csv_cell,
    csv_document,
    csv_line,
    export_filename,
    stream_query,
)


class CsvCellTest(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(csv_cell(None), "")

    def test_bool_lowercased(self):
        self.assertEqual(csv_cell(True), "true")
        self.assertEqual(csv_cell(False), "false")

    def test_dict_becomes_compact_json(self):
        self.assertEqual(
            csv_cell({"battery_level": 100, "voltage": 4.21}),
            '{"battery_level":100,"voltage":4.21}',
        )

    def test_emoji_preserved(self):
        self.assertEqual(csv_cell("NL-AMS ☀🔋"), "NL-AMS ☀🔋")


class CsvLineTest(unittest.TestCase):
    def test_quotes_fields_with_commas_and_crlf(self):
        line = csv_line(["a,b", "plain", 'has"quote'])
        self.assertTrue(line.endswith("\r\n"))
        self.assertIn('"a,b"', line)
        self.assertIn('"has""quote"', line)

    def test_json_payload_stays_one_cell(self):
        line = csv_line([1, {"lat": 52.3, "lon": 4.9}])
        # The comma inside the JSON must be quoted, not split the row.
        self.assertEqual(line.count("\r\n"), 1)
        self.assertIn('"{""lat"":52.3,""lon"":4.9}"', line)


class CsvDocumentTest(unittest.TestCase):
    def test_starts_with_bom_then_header(self):
        doc = csv_document(["a", "b"], [[1, 2], [3, 4]])
        self.assertTrue(doc.startswith("﻿"))
        self.assertIn("a,b\r\n", doc)
        self.assertIn("1,2\r\n", doc)
        self.assertIn("3,4\r\n", doc)


class ExportFilenameTest(unittest.TestCase):
    def test_shape_and_sanitization(self):
        name = export_filename("PD2EMC ☀", "meshtastic-packets")
        self.assertTrue(name.startswith("meshpoint-PD2EMC---meshtastic-packets-"))
        self.assertTrue(name.endswith(".csv"))
        # No unsafe chars leaked into the filename.
        self.assertNotIn("☀", name)
        self.assertNotIn(" ", name)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    async def fetchmany(self, n):
        chunk, self._rows = self._rows[:n], self._rows[n:]
        return chunk

    async def close(self):
        self.closed = True


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.cursor = None

    async def execute(self, sql, params):
        self.cursor = _FakeCursor(list(self._rows))
        return self.cursor


class StreamQueryTest(unittest.TestCase):
    def test_pages_rows_in_column_order_with_transform(self):
        db = _FakeDb([
            {"a": 1, "payload": '{"x":9}'},
            {"a": 2, "payload": None},
        ])

        def _t(row):
            import json
            row["x"] = (json.loads(row["payload"]) if row["payload"] else {}).get("x")
            return row

        async def _collect():
            return [
                r async for r in stream_query(
                    db, "SELECT ...", (), ["a", "x"], transform=_t, batch=1,
                )
            ]

        rows = asyncio.run(_collect())
        self.assertEqual(rows, [[1, 9], [2, None]])
        self.assertTrue(db.cursor.closed)  # cursor always closed


if __name__ == "__main__":
    unittest.main()
