"""attachments.save_image / read_image / mime_for_image_type -- pure
filesystem helpers, no RNS/LXMF, Mac-runnable."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from plugins.apps.reticulum.backend import attachments


class TestSaveImage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_returns_expected_descriptor_shape(self) -> None:
        desc = attachments.save_image(self.dir, "jpg", b"hello")
        self.assertEqual(desc["kind"], "image")
        self.assertEqual(desc["mime"], "image/jpeg")
        self.assertEqual(desc["size"], 5)
        self.assertRegex(desc["id"], r"^[0-9a-f]{32}$")

    def test_writes_bytes_under_the_given_directory(self) -> None:
        desc = attachments.save_image(self.dir, "png", b"pngdata")
        written = list(Path(self.dir).glob(f"{desc['id']}.*"))
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].read_bytes(), b"pngdata")

    def test_creates_the_directory_if_missing(self) -> None:
        nested = str(Path(self.dir) / "does" / "not" / "exist")
        desc = attachments.save_image(nested, "png", b"x")
        self.assertTrue((Path(nested) / f"{desc['id']}.png").is_file())

    def test_unusual_image_type_falls_back_to_bin_extension(self) -> None:
        desc = attachments.save_image(self.dir, "../../etc", b"x")
        written = list(Path(self.dir).glob(f"{desc['id']}.*"))
        self.assertEqual(written[0].suffix, ".bin")

    def test_two_saves_never_collide(self) -> None:
        d1 = attachments.save_image(self.dir, "jpg", b"a")
        d2 = attachments.save_image(self.dir, "jpg", b"b")
        self.assertNotEqual(d1["id"], d2["id"])


class TestReadImage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_round_trips_bytes_and_mime(self) -> None:
        desc = attachments.save_image(self.dir, "webp", b"webpbytes")
        result = attachments.read_image(self.dir, desc["id"])
        self.assertIsNotNone(result)
        data, mime = result
        self.assertEqual(data, b"webpbytes")
        self.assertEqual(mime, "image/webp")

    def test_unknown_id_returns_none(self) -> None:
        self.assertIsNone(attachments.read_image(self.dir, "a" * 32))

    def test_rejects_non_hex_id_without_touching_filesystem(self) -> None:
        # Path-traversal / non-token input never reaches Path.glob() at
        # all -- the regex check runs first.
        self.assertIsNone(attachments.read_image(self.dir, "../../../etc/passwd"))
        self.assertIsNone(attachments.read_image(self.dir, ""))
        self.assertIsNone(attachments.read_image(self.dir, "not-hex-at-all"))

    def test_wrong_length_hex_string_rejected(self) -> None:
        self.assertIsNone(attachments.read_image(self.dir, "abc123"))


class TestMimeForImageType(unittest.TestCase):
    def test_known_types(self) -> None:
        self.assertEqual(attachments.mime_for_image_type("jpg"), "image/jpeg")
        self.assertEqual(attachments.mime_for_image_type("jpeg"), "image/jpeg")
        self.assertEqual(attachments.mime_for_image_type("PNG"), "image/png")
        self.assertEqual(attachments.mime_for_image_type("webp"), "image/webp")

    def test_unknown_type_falls_back_to_octet_stream(self) -> None:
        self.assertEqual(attachments.mime_for_image_type("tiff"), "application/octet-stream")
        self.assertEqual(attachments.mime_for_image_type(""), "application/octet-stream")


if __name__ == "__main__":
    unittest.main()
