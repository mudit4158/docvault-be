# Scan to PDF — Implementation Detail

Source: PRD §4.4 (Scan to PDF), §4.5 (Image Editing), engineering handoff §3.3. UI reference: prototype screens 13–14.

## Decision: A Scan Is Just an Upload

**There is no scan endpoint.** The app assembles the PDF on the device and sends it through the ordinary upload endpoint, `POST /documents`, exactly like a file picked from storage.

The only difference between a scan and an upload is *where the PDF came from*. Everything the server does is identical: same validation, same quota decrement, same encryption, same thumbnail generation, same `AccessLog` `upload` event.

An earlier version of this spec had a separate `POST /documents/scan`. It was dropped because the only justification was a different request shape, and neither difference holds:

| Field the scan endpoint carried | Why it is not needed |
|---|---|
| `page_count` | The server reads the page count from the PDF itself — for **every** PDF upload. A client-supplied count would be untrusted anyway. |
| Default name `"Scan <date>"` | The app sets the name before uploading. The server has no reason to know a file was scanned. |

A second endpoint would be a second path to keep consistent with the first, for no behavioural gain.

## The Client/Server Split

| Concern | Where |
|---|---|
| Camera capture, multi-page session | Client |
| Edge detection, auto-crop | Client |
| Crop, rotate, brightness, contrast, B&W filter | Client |
| Page reorder, delete page, retake page | Client |
| Downscale + compress each page | Client |
| PDF assembly | Client |
| Pre-upload size check | Client |
| Upload | Client → `POST /documents` |
| Validate, meter, encrypt, store, thumbnail, log | Server (standard upload pipeline) |

Per engineering handoff §3.3:

> Pages exist client-side only until "Save to vault" — no partial Document rows created per page.

So there is no draft state, no page table, no scan-session entity. An abandoned scan leaves **zero** server-side trace.

Quota: **one scan = one document = one quota unit**, regardless of page count.

### Why not assemble on the server?

The alternative — upload raw page images, server builds the PDF — was rejected:

- **More data over the network** — N full camera images instead of one compressed PDF.
- **Unprocessed identity-document photos leave the device** and reach the server before the user has even confirmed the scan.
- **It needs a server-side draft session** to hold pages between upload and assembly, contradicting "pages exist client-side only".
- It would also let scanning work only online. Client-side assembly lets a scan be made offline and the upload queued.

The one real cost of client-side: a future **web** capture flow would need its own in-browser PDF generation. Web is upload-only at launch (handoff §3.3), so this does not bite yet.

## Client Requirements

These are what make client-side editing safe and workable. They belong to the Android Scan slice.

### 1. Page size — the biggest risk

A phone camera image is 4–12 MB. A 3–5 page scan at native resolution exceeds the 20 MB upload cap (`settings.max_upload_size_bytes`), and the user would only discover that *after* doing all the editing.

So before assembly, each page must be:

- **Downscaled** to roughly A4 at 150–200 DPI (about 1240×1754 to 1654×2339 px). Enough to read fine print on an Aadhaar or PAN card; far beyond that is wasted bytes.
- **Re-encoded as JPEG at ~80% quality** before being placed in the PDF. Typical result: 200–500 KB per page.

And the app **checks the assembled PDF's size before uploading**. If it is still over the cap, tell the user before they tap save — suggest removing a page or retaking at lower detail — rather than surfacing a 413 after the fact.

### 2. Memory on low-end devices

Several full-resolution bitmaps held at once will crash a budget phone with an out-of-memory error.

- Process pages **one at a time** — decode, transform, compress, write, release.
- Decode previews and thumbnails **downsampled** (`BitmapFactory.Options.inSampleSize`), never at native resolution.
- Keep only compressed page files in the session, not live bitmaps.

### 3. Sensitive images on the device

During editing, identity documents exist unencrypted on the phone. That is the price of client-side processing, so contain it:

- Store in-progress pages in the **app-private cache directory** only — never shared storage, never the gallery.
- **Delete** them when the scan is saved *and* when it is abandoned (back out, app killed, process death — sweep stale session files on next launch).
- Set **`FLAG_SECURE`** on the scan capture and edit screens, blocking screenshots, screen recording, and the recents-screen preview. The handoff already requires no content in previews or recents (screen 01).

### 4. The server trusts nothing

A PDF built by our own app is no more trustworthy than one from the file system — the request can be forged. It goes through the standard upload checks unchanged:

- File type sniffed from the bytes, not the `Content-Type` header
- Size cap enforced before any quota mutation
- Page count read from the PDF by the server

## Baked-In Transforms

Two client-side rules the server depends on (engineering handoff §3.3):

**Rotation is baked into the exported image**, not stored as an orientation flag. The server never sees a rotation value and stores none.

> Avoids every downstream consumer needing to respect an orientation flag.

**Filters are destructive at save time** — colour / greyscale / high-contrast are applied to the final asset, not stored as a re-render setting. There is no "original" to revert to and no server-side re-render path.

Both mean the server treats the incoming PDF as final. Do not add columns for rotation, filter, or brightness. If the user wants a different result, they rescan.

## Build vs Buy — Open Product Decision

| Option | Gives | Costs |
|---|---|---|
| **ML Kit Document Scanner** (Google) | Capture, edge detection, crop, rotate, filters and PDF output in one API call. Most of the editing work disappears | Requires Google Play Services. Its UI is fixed and will not match the prototype's edit screen (screen 14) exactly |
| **Build it** — CameraX + custom editing + Android's built-in `PdfDocument` | Matches the prototype exactly. No extra dependency | Substantially more work: edge detection, crop handles, filters, reorder |

If an exact match to screen 14 is not a v1 requirement, ML Kit is the faster route. Either way, the output goes through the same upload endpoint, so this choice has **no backend impact**.

## Known Limitation — No Text Layer

A PDF assembled from photos contains images, not text. It cannot be searched by content or have text selected. That is consistent with MVP scope — search is filename + tags only, and OCR is explicitly deferred (PRD §6).

## What Is Out of Scope

- **PDF from video** — post-MVP paid feature (PRD §6, §7).
- **Auto document-type detection via OCR** — post-MVP paid feature. `doc_type` is user-supplied at upload.
- **Server-side image processing** — the server never manipulates page images.
- **Resumable scan sessions across devices** — a session lives and dies on one device.
- **Web scan capture** — web is upload-only at launch.
