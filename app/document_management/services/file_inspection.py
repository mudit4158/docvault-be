"""Deciding what an uploaded file really is.

The client-supplied Content-Type header, and even the filename, can be
anything. Allowed types are decided from the file's own bytes: the extension
must be on the allow-list AND the content must carry that format's signature.
A `.pdf` that is really an executable is rejected.

Allowed formats (PRD §4.1): PDF, CSV, JPEG, PNG, DOC, DOCX, XLS, XLSX.
"""

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MIME_BY_EXTENSION: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".csv": "text/csv",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

ALLOWED_TYPES_LABEL = "PDF, CSV, JPEG, PNG, DOC, DOCX, XLS or XLSX"

_PDF = b"%PDF-"
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_ZIP = b"PK\x03\x04"
# Legacy Office files (.doc, .xls) are OLE2 compound documents.
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_BINARY_SIGNATURES = (_PDF, _JPEG, _PNG, _ZIP, _OLE)


class UnsupportedFileError(Exception):
    """The file is not an allowed type, or its contents contradict its name."""


@dataclass(frozen=True)
class InspectedFile:
    extension: str
    mime_type: str
    page_count: int | None


def extension_of(filename: str) -> str:
    # Some clients send Windows paths; only the final component matters.
    return PurePosixPath(filename.replace("\\", "/")).suffix.lower()


def inspect_file(filename: str, data: bytes) -> InspectedFile:
    extension = extension_of(filename)
    if extension not in MIME_BY_EXTENSION:
        raise UnsupportedFileError(f"Unsupported file type. Upload a {ALLOWED_TYPES_LABEL} file.")
    if not data:
        raise UnsupportedFileError("The file is empty.")

    if not _content_matches(extension, data):
        raise UnsupportedFileError(
            f"The file's contents do not match its {extension} extension."
        )

    page_count = _pdf_page_count(data) if extension == ".pdf" else None
    return InspectedFile(
        extension=extension,
        mime_type=MIME_BY_EXTENSION[extension],
        page_count=page_count,
    )


def _content_matches(extension: str, data: bytes) -> bool:
    if extension == ".pdf":
        return data.startswith(_PDF)
    if extension in (".jpg", ".jpeg"):
        return data.startswith(_JPEG)
    if extension == ".png":
        return data.startswith(_PNG)
    if extension in (".doc", ".xls"):
        return data.startswith(_OLE)
    if extension in (".docx", ".xlsx"):
        return data.startswith(_ZIP) and _zip_contains(
            data, "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
        )
    if extension == ".csv":
        # CSV has no signature. Accept text: no NUL bytes, and not secretly one
        # of the binary formats above.
        head = data[:8192]
        return b"\x00" not in head and not head.startswith(_BINARY_SIGNATURES)
    return False


def _zip_contains(data: bytes, member: str) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return member in archive.namelist()
    except zipfile.BadZipFile:
        return False


def _pdf_page_count(data: bytes) -> int | None:
    """Page count read from the file itself — never trusted from the client.

    Password-protected PDFs are accepted with an unknown page count: e-Aadhaar
    and many bank statements arrive encrypted, and they are exactly the
    documents this product exists to hold.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return None
        return len(reader.pages)
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise UnsupportedFileError("The file is not a readable PDF.") from exc
