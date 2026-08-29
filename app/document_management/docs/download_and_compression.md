# Download & Compression — Implementation Detail

Source: PRD §4.11. UI reference: prototype screen 07 (download split-button).

## Tiers

```python
CompressionLevel = Literal["none", "standard", "high"]
```

| Tier | UI label | Intent |
|---|---|---|
| `none` | (default download button) | Original file, byte-for-byte |
| `standard` | "Readable, smaller — good for sharing" | Moderate quality loss |
| `high` | "Smallest file, softer images" | Aggressive |

## Sizes Are Computed, Not Estimated

The UI shows **exact KB values** per tier before the user picks one (screen 07 reads "744 KB" and "408 KB", not "~medium"). Per engineering handoff §3.2:

> Sizes shown must be computed server-side per file — not hardcoded ratios.

So a ratio table is not acceptable. `GET /documents/{id}/download/sizes` must actually produce the compressed artefacts to know their size.

```json
{
  "none":     { "bytes": 1258291 },
  "standard": { "bytes": 761856 },
  "high":     { "bytes": 417792 }
}
```

### Caching Compressed Variants

Compressing twice — once to report the size, once to serve the bytes — is wasteful and makes the two disagree if the algorithm is ever nondeterministic.

Compress once, cache the artefact, serve it on the follow-up download:

```
storage key layout:
  documents/{document_id}/original
  documents/{document_id}/thumb
  documents/{document_id}/compressed/standard
  documents/{document_id}/compressed/high
```

`GET .../download/sizes` generates any missing variants, caches them, and returns their real sizes. The subsequent `GET .../download?compression=standard` is then a cache hit.

Variants are derived data. The hard-delete job removes the whole `documents/{document_id}/` prefix, so no separate cleanup path is needed.

## Compression by File Type

| Type | Approach |
|---|---|
| PDF | Downsample embedded images, drop metadata. Keep text layers intact — text must stay selectable |
| JPEG / PNG | Re-encode at a lower quality factor; PNG → JPEG where there is no alpha channel |
| DOC / DOCX / XLS / XLSX | Already ZIP containers. Recompress at a higher deflate level; gains are small |
| CSV | Nothing useful to do — return the original for every tier |

When a tier cannot beat the original, **return the original size** for that tier rather than a larger number. The user should never be offered a "compressed" option that is bigger than the source.

## Download Endpoint

`GET /documents/{id}/download?compression=none|standard|high`

```
1. resolve_permission(document_id, account_id)
2. Require "owner" or "download"       → 403 for view-only members
3. Verify storage_key is not NULL      → 410 Gone if the file was purged
4. Resolve the variant key (generating + caching it if missing)
5. Fetch bytes, decrypt
6. INSERT AccessLog(event_type="download")
7. Stream the response
```

Preview and download are **distinct** permission levels — see `sharing_and_access.md`. A view-only member gets a 403 here, not a silent downgrade to preview.

The `download` log event is written once per request regardless of tier. The tier itself is not recorded; the log's job is who and when, not how.

## Streaming

Files run to 20 MB, and paid plans raise that. Stream both directions rather than buffering:

```python
return StreamingResponse(
    _decrypt_stream(storage.get_stream(key)),
    media_type=document.mime_type,
    headers={"Content-Disposition": f'attachment; filename="{document.name}"'},
)
```

## Decryption

Files are encrypted at rest (`shared/encryption.py`). Decryption happens on the way out, above the storage layer — the same place encryption happened on the way in. Compressed variants are encrypted at rest too; there is no plaintext path in storage.

## Preview vs Download

Preview (screen 06) serves the same bytes with an inline disposition and a lower permission bar:

| | Permission required | Disposition | Log event |
|---|---|---|---|
| Preview | any non-`None` | `inline` | `view` |
| Download | `owner` or `download` | `attachment` | `download` |

Compression applies only to download. Preview always serves the original.
