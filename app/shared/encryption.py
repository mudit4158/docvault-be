"""Encryption at rest for stored files.

AES-256-GCM (authenticated encryption): a tampered or truncated blob fails to
decrypt instead of returning garbage. Each blob is

    1 byte   format version (currently 0x01)
    12 bytes random nonce
    rest     ciphertext + 16-byte GCM tag

Encryption sits ABOVE the storage backend, so the local disk today and GCS
later both only ever see ciphertext — swapping the backend cannot weaken it.

Key handling: `settings.encryption_key` should be 32 random bytes encoded as
URL-safe base64 (generate with `python -c "import os,base64;
print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`). Any other string is
accepted and stretched with SHA-256 so local development works out of the box,
but that is only as strong as the string — production must use a real random
key, held in a secret manager rather than an .env file.

Key rotation is not implemented; the version byte exists so it can be added
without breaking existing blobs.
"""

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

_VERSION = b"\x01"
_NONCE_BYTES = 12


class DecryptionError(Exception):
    """The blob is corrupt, truncated, or was encrypted with a different key."""


def _key() -> bytes:
    material = settings.encryption_key
    try:
        decoded = base64.urlsafe_b64decode(material)
        if len(decoded) == 32:
            return decoded
    except (binascii.Error, ValueError):
        pass
    return hashlib.sha256(material.encode("utf-8")).digest()


def encrypt(plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE_BYTES)
    return _VERSION + nonce + AESGCM(_key()).encrypt(nonce, plaintext, None)


def decrypt(blob: bytes) -> bytes:
    if len(blob) < 1 + _NONCE_BYTES or blob[:1] != _VERSION:
        raise DecryptionError("Unrecognised encrypted file format")
    nonce = blob[1 : 1 + _NONCE_BYTES]
    try:
        return AESGCM(_key()).decrypt(nonce, blob[1 + _NONCE_BYTES :], None)
    except InvalidTag as exc:
        raise DecryptionError("Stored file failed its integrity check") from exc
