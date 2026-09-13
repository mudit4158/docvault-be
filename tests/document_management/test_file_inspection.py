"""What an uploaded file really is — decided from its bytes, not its name."""

import io
import zipfile

import pytest

from app.document_management.services.file_inspection import (
    UnsupportedFileError,
    inspect_file,
)
from tests.document_management.conftest import PNG_BYTES, pdf_bytes


def zip_with(member: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "<xml/>")
    return buffer.getvalue()


OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64


# --- accepted -------------------------------------------------------------


def test_pdf_page_count_is_read_from_the_file() -> None:
    inspected = inspect_file("Aadhaar.pdf", pdf_bytes(pages=3))
    assert inspected.mime_type == "application/pdf"
    assert inspected.page_count == 3


def test_password_protected_pdf_is_accepted_without_a_page_count() -> None:
    """e-Aadhaar and bank statements arrive encrypted; they must upload."""
    inspected = inspect_file("e-Aadhaar.pdf", pdf_bytes(password="1234"))
    assert inspected.page_count is None


@pytest.mark.parametrize(
    ("filename", "content", "mime"),
    [
        ("PAN.png", PNG_BYTES, "image/png"),
        ("photo.JPG", b"\xff\xd8\xff\xe0" + b"\x00" * 32, "image/jpeg"),
        ("letter.docx", zip_with("word/document.xml"), None),
        ("sheet.xlsx", zip_with("xl/workbook.xml"), None),
        ("old.doc", OLE, "application/msword"),
        ("old.xls", OLE, "application/vnd.ms-excel"),
        ("bills.csv", b"date,amount\n2026-09-01,1200\n", "text/csv"),
    ],
)
def test_allowed_types_are_accepted(filename: str, content: bytes, mime: str | None) -> None:
    inspected = inspect_file(filename, content)
    if mime:
        assert inspected.mime_type == mime
    assert inspected.page_count is None


def test_windows_style_path_uses_only_the_final_name() -> None:
    assert inspect_file("C:\\Users\\me\\Aadhaar.pdf", pdf_bytes()).extension == ".pdf"


# --- rejected -------------------------------------------------------------


def test_unknown_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedFileError, match="Unsupported file type"):
        inspect_file("setup.exe", b"MZ" + b"\x00" * 64)


def test_executable_renamed_to_pdf_is_rejected() -> None:
    with pytest.raises(UnsupportedFileError, match="do not match"):
        inspect_file("Aadhaar.pdf", b"MZ\x90\x00" + b"\x00" * 64)


def test_empty_file_is_rejected() -> None:
    with pytest.raises(UnsupportedFileError, match="empty"):
        inspect_file("Aadhaar.pdf", b"")


def test_pdf_header_with_garbage_body_is_rejected() -> None:
    with pytest.raises(UnsupportedFileError, match="not a readable PDF"):
        inspect_file("broken.pdf", b"%PDF-1.7\nthis is not a pdf")


def test_docx_without_word_content_is_rejected() -> None:
    """Any zip renamed to .docx must not pass."""
    with pytest.raises(UnsupportedFileError):
        inspect_file("letter.docx", zip_with("payload.bin"))


def test_binary_file_renamed_to_csv_is_rejected() -> None:
    with pytest.raises(UnsupportedFileError):
        inspect_file("data.csv", PNG_BYTES)
