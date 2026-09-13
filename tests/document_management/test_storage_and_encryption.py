"""Encryption at rest and the local storage backend."""

from pathlib import Path

import pytest

from app.shared.encryption import DecryptionError, decrypt, encrypt
from app.shared.storage.interface import LocalStorage


def test_round_trip() -> None:
    assert decrypt(encrypt(b"Aadhaar 1234 5678 9012")) == b"Aadhaar 1234 5678 9012"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    secret = b"PAN ABCDE1234F"
    assert secret not in encrypt(secret)


def test_same_input_encrypts_differently_each_time() -> None:
    """A fresh nonce per file: identical documents are not recognisable on disk."""
    assert encrypt(b"same") != encrypt(b"same")


def test_tampered_ciphertext_is_rejected() -> None:
    blob = bytearray(encrypt(b"important"))
    blob[-1] ^= 0x01
    with pytest.raises(DecryptionError):
        decrypt(bytes(blob))


def test_garbage_is_rejected() -> None:
    with pytest.raises(DecryptionError):
        decrypt(b"not an encrypted blob")


async def test_local_storage_round_trip(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path))
    await storage.put("documents/abc/original", b"bytes")
    assert await storage.get("documents/abc/original") == b"bytes"


async def test_deleting_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    await LocalStorage(str(tmp_path)).delete("documents/never/existed")


async def test_path_traversal_is_refused(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "root"))
    with pytest.raises(ValueError, match="outside the storage root"):
        await storage.put("../escape.txt", b"nope")
