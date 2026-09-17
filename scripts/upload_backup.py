"""Upload a local file to the configured storage backend under `backups/`.

Reuses the same `StorageBackend`/ADC identity the app already uses for
documents — no separate GCS client or credentials needed. Called by
backup_db.sh, not meant to be run manually.

    python scripts/upload_backup.py <local-file-path>
"""

import asyncio
import sys
from pathlib import Path

from app.shared.storage.interface import get_storage


async def main(local_path: Path) -> None:
    key = f"backups/{local_path.name}"
    await get_storage().put(key, local_path.read_bytes())
    print(f"Uploaded {local_path} -> {key}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/upload_backup.py <local-file-path>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(Path(sys.argv[1])))
