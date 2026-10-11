"""Static assets are served gzip-compressed (UI quick-wins, item 2).

``server.py`` registers ``GZipMiddleware`` right after the FastAPI app
is constructed. These tests pin the behavior that decision depends on:

1. Textual static assets (JS/CSS) come back ``Content-Encoding: gzip``
   and round-trip to the original bytes.
2. Already-compressed formats (png) are NOT re-compressed -- the
   middleware's DEFAULT_EXCLUDED_CONTENT_TYPES must stay in effect.
3. ``text/event-stream`` responses are never buffered through gzip, so
   the update/firmware progress streams keep their per-chunk latency.
4. Small bodies below ``minimum_size`` go out uncompressed.

Built the same way as ``test_auth_page_serving.py``: a minimal app
wiring the pieces the real server wires, without booting the pipeline.
"""

from __future__ import annotations

import asyncio
import gzip
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient


def _build_app() -> tuple[FastAPI, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="meshpoint-gzip-"))
    payload = b"console.log('x');\n" * 500  # ~11 KB, over minimum_size
    (tmp / "big.js").write_bytes(payload)
    (tmp / "tiny.js").write_bytes(b"a=1;\n")
    (tmp / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 6000)

    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    @app.get("/events")
    async def events():
        async def gen():
            yield b"data: tick\n\n"
            await asyncio.sleep(0)
            yield b"data: tock\n\n"
        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    app.mount("/static", StaticFiles(directory=str(tmp)))
    return app, tmp


class TestGzipStaticServing(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self.tmp = _build_app()
        self.client = TestClient(self.app)
        self.gz = {"accept-encoding": "gzip"}

    def test_js_asset_is_gzipped_and_round_trips(self) -> None:
        response = self.client.get("/static/big.js", headers=self.gz)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        # httpx transparently decodes Content-Encoding on .content.
        self.assertEqual(
            response.content, (self.tmp / "big.js").read_bytes(),
        )

    def test_small_asset_not_compressed(self) -> None:
        response = self.client.get("/static/tiny.js", headers=self.gz)
        self.assertIsNone(response.headers.get("content-encoding"))

    def test_png_not_recompressed(self) -> None:
        response = self.client.get("/static/pic.png", headers=self.gz)
        self.assertIsNone(response.headers.get("content-encoding"))

    def test_event_stream_not_gzipped(self) -> None:
        response = self.client.get("/events", headers=self.gz)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("content-encoding"))

    def test_wire_bytes_are_actually_smaller(self) -> None:
        # The whole point of the change: fewer bytes on the wire, and
        # the wire bytes are the true gzip stream of the asset.
        on_disk = (self.tmp / "big.js").read_bytes()
        with self.client.stream("GET", "/static/big.js", headers=self.gz) as r:
            wire = b"".join(r.iter_raw())
        self.assertLess(len(wire), len(on_disk) * 0.5, "expected >2x on JS")
        self.assertEqual(gzip.decompress(wire), on_disk)


if __name__ == "__main__":
    unittest.main()
