# Scan to PDF — Implementation Detail

Source: PRD §4.4 (Scan to PDF), §4.5 (Image Editing). UI reference: prototype screens 13–14.

## The Client/Server Split

Almost all of this feature is **client-side**. The server's only involvement is a single save endpoint.

| Concern | Where |
|---|---|
| Camera capture, multi-page session | Client |
| Edge detection, auto-crop | Client |
| Crop, rotate, brightness, contrast, B&W filter | Client |
| Page reorder, delete page, retake page | Client |
| PDF assembly | Client |
| Persisting the result | **Server** |

Per engineering handoff §3.3:

> Pages exist client-side only until "Save to vault" — no partial Document rows created per page.

So there is no draft state, no page table, no scan-session entity, and no partial upload endpoint. A scan session that is abandoned leaves **zero** server-side trace.

## Save Endpoint

`POST /documents/scan`

The client assembles the final PDF and posts it as one multipart request:

```
name:      user-supplied document name (optional; default "Scan <date>")
doc_type:  document type enum
page_count: number of pages in the assembled PDF
file:      the assembled PDF bytes
```

The server path is then **identical to a regular upload** — same validation, same quota decrement, same encryption, same thumbnail generation, same `AccessLog` `upload` event. Implement it as a thin wrapper over `DocumentService.upload` rather than a parallel pipeline:

```python
class ScanService:
    async def save(self, account_id, name, doc_type, page_count, file) -> DocumentResponse:
        # Same pipeline as upload — scans are not a special kind of document.
        return await DocumentService(self.db).upload(
            account_id=account_id,
            file=file,
            name=name or f"Scan {date.today():%d %b %Y}",
            doc_type=doc_type,
            page_count=page_count,
            source="scan",
        )
```

A scanned document is not a distinct entity — it is a `Document` whose bytes happen to have come from a camera. The only reason for a separate endpoint is the differing request shape.

Quota applies exactly as it does to uploads: **one scan session = one document = one quota unit**, regardless of page count.

## Baked-In Transforms

Two client-side rules the server depends on (engineering handoff §3.3):

**Rotation is baked into the exported image**, not stored as an orientation flag. The server never sees a rotation value and stores none.

> Avoids every downstream consumer needing to respect an orientation flag.

**Filters are destructive at save time** — colour / greyscale / high-contrast are applied to the final asset, not stored as a re-render setting. There is no "original" to revert to and no server-side re-render path.

Both mean the server treats the incoming PDF as final. Do not add columns for rotation, filter, or brightness. If the user wants a different result, they rescan.

## Web Parity

Per engineering handoff §3.3: scan is camera-only on Android; **web is upload-only at launch**. The web client does not call `POST /documents/scan`.

The endpoint is not platform-gated server-side — if web capture ships later, it uses the same endpoint with no backend change.

## What Is Out of Scope

- **PDF from video** — post-MVP paid feature (PRD §6, §7).
- **Auto document-type detection via OCR** — post-MVP paid feature. `doc_type` is user-supplied on save.
- **Server-side image processing** — the server never manipulates page images.
- **Resumable scan sessions across devices** — a session lives and dies in one client.
