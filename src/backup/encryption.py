"""Optional password encryption for backup archives.

A backup's plain ``.tar.gz`` already contains ``config/local.yaml`` --
secrets and all -- so an operator who wants to store a download
somewhere less trusted (cloud storage, email, a USB stick that
leaves the building) can opt into wrapping the whole archive in
AES-256-GCM behind a Scrypt-derived key.

The entire already-built ``.tar.gz`` is treated as one opaque
plaintext blob. A fixed-size, unencrypted header precedes the
ciphertext so both server and client can detect "is this an
encrypted backup?" by sniffing the first 8 bytes alone, without ever
calling ``tarfile.open()``. The header is authenticated as AEAD
associated data, so tampering with the header (e.g. swapping in a
weaker set of KDF params) is caught at decrypt time rather than
silently accepted.

Wrong password and corrupted/truncated ciphertext both surface as the
same :class:`BackupDecryptionError` -- ``cryptography``'s
``InvalidTag`` is caught and re-raised generically so a failed decrypt
never distinguishes "bad password" from "corrupt file" for a caller
that might relay the message back over the API.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"MPBKENC1"
_HEADER_FORMAT = ">8sBBBB16s12s"
_HEADER_SIZE = struct.calcsize(_HEADER_FORMAT)
assert _HEADER_SIZE == 40

_VERSION = 1
_SALT_SIZE = 16
_NONCE_SIZE = 12
_KEY_SIZE = 32

# Scrypt cost parameters, stored in the header so a future format
# revision could raise them without breaking old archives.
_SCRYPT_N_LOG2 = 14  # N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256


class BackupDecryptionError(Exception):
    """Raised for a wrong password or a corrupt/tampered archive.

    Deliberately a single exception type covering both cases -- see
    the module docstring.
    """


@dataclass(frozen=True)
class _Header:
    version: int
    n_log2: int
    r: int
    p: int
    salt: bytes
    nonce: bytes


def is_encrypted(payload: bytes) -> bool:
    """True iff ``payload`` starts with the encrypted-backup magic marker."""
    return payload[: len(MAGIC)] == MAGIC


def _derive_key(password: str, salt: bytes, *, n_log2: int, r: int, p: int) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_SIZE, n=2**n_log2, r=r, p=p)
    return kdf.derive(password.encode("utf-8"))


def _pack_header(header: _Header) -> bytes:
    return struct.pack(
        _HEADER_FORMAT,
        MAGIC,
        header.version,
        header.n_log2,
        header.r,
        header.p,
        header.salt,
        header.nonce,
    )


def _unpack_header(payload: bytes) -> _Header:
    if len(payload) < _HEADER_SIZE:
        raise BackupDecryptionError("archive is too small to be an encrypted backup")
    magic, version, n_log2, r, p, salt, nonce = struct.unpack(
        _HEADER_FORMAT, payload[:_HEADER_SIZE]
    )
    if magic != MAGIC:
        raise BackupDecryptionError("not an encrypted backup archive")
    if version != _VERSION:
        raise BackupDecryptionError(f"unsupported encrypted-backup version {version}")
    return _Header(version=version, n_log2=n_log2, r=r, p=p, salt=salt, nonce=nonce)


def validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise ValueError("password must be str")
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise ValueError(
            f"password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters",
        )


def encrypt_archive(plaintext: bytes, password: str) -> bytes:
    """Return ``plaintext`` wrapped in an unencrypted header + AES-GCM ciphertext."""
    validate_password(password)
    salt = os.urandom(_SALT_SIZE)
    nonce = os.urandom(_NONCE_SIZE)
    header = _Header(
        version=_VERSION,
        n_log2=_SCRYPT_N_LOG2,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        salt=salt,
        nonce=nonce,
    )
    header_bytes = _pack_header(header)
    key = _derive_key(password, salt, n_log2=header.n_log2, r=header.r, p=header.p)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, header_bytes)
    return header_bytes + ciphertext


def decrypt_archive(payload: bytes, password: str) -> bytes:
    """Return the plain ``.tar.gz`` bytes, or raise :class:`BackupDecryptionError`."""
    header = _unpack_header(payload)
    header_bytes = payload[:_HEADER_SIZE]
    ciphertext = payload[_HEADER_SIZE:]
    key = _derive_key(password, header.salt, n_log2=header.n_log2, r=header.r, p=header.p)
    try:
        return AESGCM(key).decrypt(header.nonce, ciphertext, header_bytes)
    except InvalidTag as exc:
        raise BackupDecryptionError("incorrect password or corrupted archive") from exc
