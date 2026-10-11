"""Tests for backup archive password encryption."""

from __future__ import annotations

import unittest

from src.backup.encryption import (
    MAGIC,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    BackupDecryptionError,
    decrypt_archive,
    encrypt_archive,
    is_encrypted,
    validate_password,
)


class TestBackupEncryption(unittest.TestCase):
    def test_round_trip(self) -> None:
        plaintext = b"\x1f\x8b" + b"fake tar.gz payload" * 50
        ciphertext = encrypt_archive(plaintext, "correct horse battery staple")
        self.assertEqual(decrypt_archive(ciphertext, "correct horse battery staple"), plaintext)

    def test_ciphertext_starts_with_magic_marker(self) -> None:
        ciphertext = encrypt_archive(b"payload", "correct horse battery staple")
        self.assertTrue(ciphertext.startswith(MAGIC))

    def test_is_encrypted_detects_marker_without_decrypting(self) -> None:
        ciphertext = encrypt_archive(b"payload", "correct horse battery staple")
        self.assertTrue(is_encrypted(ciphertext))
        self.assertFalse(is_encrypted(b"\x1f\x8bnot encrypted"))
        self.assertFalse(is_encrypted(b""))

    def test_wrong_password_raises_generic_error(self) -> None:
        ciphertext = encrypt_archive(b"payload", "correct horse battery staple")
        with self.assertRaises(BackupDecryptionError):
            decrypt_archive(ciphertext, "wrong password")

    def test_truncated_archive_raises_same_generic_error(self) -> None:
        ciphertext = encrypt_archive(b"payload", "correct horse battery staple")
        with self.assertRaises(BackupDecryptionError):
            decrypt_archive(ciphertext[:-1], "correct horse battery staple")

    def test_tampered_header_raises_same_generic_error(self) -> None:
        # The header is unencrypted but authenticated as AEAD associated
        # data -- flipping a bit in it (e.g. the salt) must be caught at
        # decrypt time, not silently accepted with a garbage key.
        ciphertext = bytearray(encrypt_archive(b"payload", "correct horse battery staple"))
        ciphertext[len(MAGIC) + 4] ^= 0xFF
        with self.assertRaises(BackupDecryptionError):
            decrypt_archive(bytes(ciphertext), "correct horse battery staple")

    def test_too_small_payload_raises_without_crashing(self) -> None:
        with self.assertRaises(BackupDecryptionError):
            decrypt_archive(b"short", "correct horse battery staple")

    def test_not_encrypted_payload_raises(self) -> None:
        with self.assertRaises(BackupDecryptionError):
            decrypt_archive(b"\x1f\x8b" + b"x" * 64, "correct horse battery staple")

    def test_validate_password_rejects_too_short(self) -> None:
        with self.assertRaises(ValueError):
            validate_password("short")

    def test_validate_password_rejects_too_long(self) -> None:
        with self.assertRaises(ValueError):
            validate_password("x" * (MAX_PASSWORD_LENGTH + 1))

    def test_validate_password_accepts_boundary_lengths(self) -> None:
        validate_password("x" * MIN_PASSWORD_LENGTH)
        validate_password("x" * MAX_PASSWORD_LENGTH)

    def test_each_encryption_uses_fresh_salt_and_nonce(self) -> None:
        # Same plaintext, same password, two independent calls -- the
        # ciphertext (and header) must differ, or an attacker comparing
        # two backups could learn something from a repeated nonce/salt.
        a = encrypt_archive(b"payload", "correct horse battery staple")
        b = encrypt_archive(b"payload", "correct horse battery staple")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
