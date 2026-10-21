"""Content and size checks for private user supplied documents."""

from pathlib import Path
import zipfile


MAX_PRIVATE_DOCUMENT_SIZE = 10 * 1024 * 1024
_MAX_DOCX_EXPANDED_SIZE = 50 * 1024 * 1024
_MAX_DOCX_ENTRIES = 5000


def validate_private_document(uploaded, *, max_size=MAX_PRIVATE_DOCUMENT_SIZE):
    """Return an error message when a PDF, DOCX, JPEG, PNG, or WebP is invalid."""
    if uploaded is None:
        return "Choose a document to upload."
    if uploaded.size <= 0 or uploaded.size > max_size:
        return "Choose a non-empty document within the upload size limit."

    suffix = Path(uploaded.name).suffix.lower()
    try:
        uploaded.seek(0)
        header = uploaded.read(1024)
        uploaded.seek(0)
    except (AttributeError, OSError):
        return "The uploaded file could not be read."

    valid = False
    if suffix == ".pdf":
        valid = b"%PDF-" in header
    elif suffix in {".jpg", ".jpeg"}:
        valid = header.startswith(b"\xff\xd8\xff")
    elif suffix == ".png":
        valid = header.startswith(b"\x89PNG\r\n\x1a\n")
    elif suffix == ".webp":
        valid = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    elif suffix == ".docx":
        try:
            with zipfile.ZipFile(uploaded) as archive:
                entries = archive.infolist()
                expanded_size = sum(entry.file_size for entry in entries)
                names = {entry.filename for entry in entries}
                valid = (
                    len(entries) <= _MAX_DOCX_ENTRIES
                    and expanded_size <= _MAX_DOCX_EXPANDED_SIZE
                    and "[Content_Types].xml" in names
                    and "word/document.xml" in names
                )
        except (OSError, RuntimeError, zipfile.BadZipFile):
            valid = False
        finally:
            uploaded.seek(0)

    if not valid:
        return "The file contents do not match a supported PDF, Word document, or image."
    return None
