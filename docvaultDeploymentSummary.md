# DocVault Deployment Summary

## Google Cloud VM (Compute Engine)
This is the actual computer your backend runs on. Before this, your FastAPI backend only ran on your laptop, which obviously can't be a production server (it's off half the time, and nobody outside your LAN can reach it). We rent a tiny, always-on virtual machine from Google for exactly this — it has a public IP address and stays running 24/7. We picked the smallest free-tier size (e2-micro) since your traffic is genuinely light.

## Docker / docker-compose
Instead of installing Postgres and Python directly onto that VM (messy, hard to reproduce, easy to break), everything runs in isolated containers: one for Postgres, one for your API, one for Caddy. `docker-compose.yml` is the single file that says "run these three together, wired to each other this way." This is standard practice because it makes the whole setup reproducible — if this VM died tomorrow, a new one could be running the exact same stack in minutes.

## Postgres (replacing SQLite)
Your app used to store data in a single SQLite file sitting on disk. That's fine for one developer testing locally, but it can't safely handle multiple people hitting the server at once (SQLite locks the whole file per write). Postgres is a real database server designed for exactly this — many people reading/writing at the same time.

## Alembic migration
This is the file that tells Postgres what tables to create (accounts, documents, otp_attempts, etc.) and in what shape. Your code had never actually generated this file before — it's how the database structure gets built and evolved safely instead of you writing raw SQL by hand.

## GCP project consolidation
Before, your Firebase (phone login) and your file storage bucket lived in two separate Google Cloud projects, each needing its own separate secret key file to access. We moved storage into the same project as Firebase, and instead of secret key files at all, the VM authenticates as itself (it has an identity Google recognizes automatically) — one less category of secret to leak or lose.

## APK distribution
Firebase App Distribution was tried and removed — tester notification emails weren't reliable, so it added a Firebase dependency without actually delivering its main benefit. Distribution is now manual: build the signed release APK (`./gradlew assembleRelease -PdocvaultApiUrl=https://doc-vault.duckdns.org/`) and hand the file to testers directly (Drive, WhatsApp, etc.). Same signing key every time, so it installs over the existing app without losing their session.

## Where to check things
- **GCS bucket**: console.cloud.google.com/storage/browser/docvault-e8054-documents?project=docvault-e8054
- **Firebase project overview**: console.firebase.google.com/project/docvault-e8054/overview
- **Firebase Authentication (phone login users)**: same console → Build → Authentication
- **GCP project overview (billing, all resources)**: console.cloud.google.com/home/dashboard?project=docvault-e8054

## API call flow
```
Phone → DNS lookup "doc-vault.duckdns.org" → DuckDNS says "34.27.248.178"
Phone → https://34.27.248.178 → hits Caddy (has the valid cert, decrypts the request)
Caddy → forwards the plain request internally → your FastAPI app container
```

## Quick commands

**Backend (local)**
```
python scripts/init_dev_db.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Android — check SHA-1/SHA-256 (must match Firebase console fingerprints)**
```
./gradlew signingReport
```

**Android — build the latest APK**
```
# Local/debug
./gradlew clean :app:assembleDebug

# Release (signed, production backend baked in)
./gradlew assembleRelease -PdocvaultApiUrl=https://doc-vault.duckdns.org/
```
