"""Opt-in confidence check against a REAL GCS bucket.

Skipped unless GCS_INTEGRATION_TEST_BUCKET names a real dev/test bucket the
active credentials (GOOGLE_APPLICATION_CREDENTIALS / ADC) can write to. Never
runs in normal CI — this exists to catch things the mocked unit tests in
test_storage_and_encryption.py can't: wrong IAM role, wrong bucket name,
credential resolution actually failing, real network behaviour.

    GCS_INTEGRATION_TEST_BUCKET=<bucket> pytest tests/shared/test_gcs_storage_live.py
"""

import os
import uuid

import pytest

from app.shared.storage.interface import GCSStorage

BUCKET = os.getenv("GCS_INTEGRATION_TEST_BUCKET")

pytestmark = pytest.mark.skipif(
    not BUCKET,
    reason="set GCS_INTEGRATION_TEST_BUCKET to a real bucket to run this",
)


async def test_put_get_delete_round_trip_against_a_real_bucket() -> None:
    storage = GCSStorage(BUCKET)  # type: ignore[arg-type]
    key = f"integration-test/{uuid.uuid4()}"

    await storage.put(key, b"hello from docvault-be")
    assert await storage.get(key) == b"hello from docvault-be"

    await storage.delete(key)
    with pytest.raises(FileNotFoundError):
        await storage.get(key)

    await storage.delete(key)  # deleting again is still not an error
