"""Encryption at rest and the storage backends."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.api_core.exceptions import NotFound

from app.shared.encryption import DecryptionError, decrypt, encrypt
from app.shared.storage.interface import GCSStorage, LocalStorage


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


def _gcs_storage_with_mock_bucket() -> tuple[GCSStorage, MagicMock]:
    """A GCSStorage whose lazily-built client is a mock, so no real GCS is ever hit."""
    storage = GCSStorage("test-bucket")
    mock_bucket = MagicMock()
    storage._client = MagicMock()
    storage._client.bucket.return_value = mock_bucket
    return storage, mock_bucket


async def test_gcs_put_uploads_the_given_bytes_under_the_given_key() -> None:
    storage, bucket = _gcs_storage_with_mock_bucket()
    await storage.put("documents/abc/original", b"bytes")
    bucket.blob.assert_called_once_with("documents/abc/original")
    bucket.blob.return_value.upload_from_string.assert_called_once_with(b"bytes")


async def test_gcs_get_returns_the_downloaded_bytes() -> None:
    storage, bucket = _gcs_storage_with_mock_bucket()
    bucket.blob.return_value.download_as_bytes.return_value = b"bytes"
    assert await storage.get("documents/abc/original") == b"bytes"


async def test_gcs_get_of_a_missing_key_raises_file_not_found() -> None:
    storage, bucket = _gcs_storage_with_mock_bucket()
    bucket.blob.return_value.download_as_bytes.side_effect = NotFound("gone")
    with pytest.raises(FileNotFoundError):
        await storage.get("documents/never/existed")


async def test_gcs_delete_calls_through_to_the_blob() -> None:
    storage, bucket = _gcs_storage_with_mock_bucket()
    await storage.delete("documents/abc/original")
    bucket.blob.return_value.delete.assert_called_once_with()


async def test_gcs_deleting_a_missing_key_is_not_an_error() -> None:
    storage, bucket = _gcs_storage_with_mock_bucket()
    bucket.blob.return_value.delete.side_effect = NotFound("gone")
    await storage.delete("documents/never/existed")  # must not raise


def test_gcs_client_is_built_lazily_and_only_once() -> None:
    with patch("app.shared.storage.interface.gcs.Client") as mock_client_cls:
        storage = GCSStorage("test-bucket")
        mock_client_cls.assert_not_called()  # not built in __init__
        storage._bucket()
        storage._bucket()
        mock_client_cls.assert_called_once()  # built on first use, reused after
