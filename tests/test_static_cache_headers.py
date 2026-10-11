"""Cache-Control policy for static assets (UI quick-wins, item 3).

Pins the contract of ``src/api/static_cache.py``:

1. Stamped JS/CSS (``?v=`` — what ``bust_asset_urls`` generates) is
   served ``immutable`` with a year max-age.
2. Un-stamped JS/CSS and media get ``must-revalidate`` so the StaticFiles
   ETag keeps them correct across upgrades.
3. HTML gets ``no-cache`` (safety net for /index.html direct).
4. A handler that already set Cache-Control is never overridden
   (e.g. the ``/`` route's explicit no-cache header).
5. Non-200 responses and API paths are untouched.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from src.api.static_cache import StaticCacheHeaders


def _build_app() -> FastAPI:
    tmp = Path(tempfile.mkdtemp(prefix="meshpoint-cache-"))
    (tmp / "app.js").write_text("console.log(1);")
    (tmp / "style.css").write_text("body{}")
    (tmp / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    (tmp / "page.html").write_text("<html>hi</html>")

    app = FastAPI()

    @app.get("/api/thing")
    async def thing():
        return Response("ok", headers={"Cache-Control": "private, max-age=5"})

    app.mount("/static", StaticFiles(directory=str(tmp)))
    app.add_middleware(StaticCacheHeaders)
    return app


class TestStaticCacheHeaders(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(_build_app())

    def test_versioned_js_is_immutable(self) -> None:
        r = self.client.get("/static/app.js?v=deadbeef")
        self.assertEqual(
            r.headers["cache-control"],
            "public, max-age=31536000, immutable",
        )

    def test_unversioned_js_revalidates(self) -> None:
        r = self.client.get("/static/style.css")
        self.assertEqual(r.headers["cache-control"], "public, max-age=0, must-revalidate")

    def test_media_revalidates(self) -> None:
        r = self.client.get("/static/pic.png")
        self.assertEqual(r.headers["cache-control"], "public, max-age=0, must-revalidate")

    def test_html_is_no_cache(self) -> None:
        r = self.client.get("/static/page.html")
        self.assertEqual(r.headers["cache-control"], "no-cache")

    def test_handler_set_header_is_not_overridden(self) -> None:
        r = self.client.get("/api/thing")
        self.assertEqual(r.headers["cache-control"], "private, max-age=5")

    def test_404_untouched(self) -> None:
        r = self.client.get("/static/nope.js?v=1")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("cache-control", r.headers)

    def test_etag_survives_middleware(self) -> None:
        # must-revalidate is only honest if StaticFiles' validators stay.
        r = self.client.get("/static/app.js")
        self.assertIn("etag", r.headers)
        r2 = self.client.get("/static/app.js", headers={"if-none-match": r.headers["etag"]})
        self.assertEqual(r2.status_code, 304)


if __name__ == "__main__":
    unittest.main()
