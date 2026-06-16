"""PDF resume text extraction.

This is the one place the no-fabrication guarantee is exposed to bad input: if a
resume PDF extracts to garbage (scanned/image-only PDFs yield little or no text),
the downstream agents would happily analyze noise and produce a silently wrong
honest_gaps list. So extraction lives here behind a hard floor — too little text
means we reject and ask the user to paste instead, rather than feed mush to the
pipeline.
"""

import io

from pypdf import PdfReader

# Below this many non-whitespace characters we treat the PDF as unreadable
# (almost certainly scanned/image-only). Starting point — tune against real PDFs.
MIN_RESUME_CHARS = 50


def extract_resume_text(data: bytes) -> str:
    """Extract plain text from a resume PDF.

    Raises ValueError if the PDF can't be read or yields too little text to be a
    real resume — the caller turns that into a "paste the text instead" response.
    """
    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
        text = "" if encrypted else "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except Exception as exc:  # pypdf raises a variety of types on malformed input
        raise ValueError(f"Could not read this PDF: {exc}") from exc

    # Raised outside the except so these clear messages aren't re-wrapped as a
    # generic parse error.
    if encrypted:
        raise ValueError(
            "This PDF is password-protected. Remove the password, or paste your "
            "resume text instead."
        )
    if len("".join(text.split())) < MIN_RESUME_CHARS:
        raise ValueError(
            "This PDF has almost no extractable text — it's likely a scanned "
            "image. Please paste your resume text instead."
        )
    return text.strip()


if __name__ == "__main__":
    # Smoke check for the guardrail edge case (see spec Verification).
    for bad in (b"", b"%PDF-1.4 not really a pdf"):
        try:
            extract_resume_text(bad)
            print("FAIL: expected ValueError")
        except ValueError as e:
            print(f"ok, rejected: {e}")
