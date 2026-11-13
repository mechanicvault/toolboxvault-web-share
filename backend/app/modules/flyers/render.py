"""PDF rendering for flyers: page count + the first-page
thumbnail every surface teases with.

pypdfium2 (PDFium) does the rendering — pure wheel, no system
packages — at post time, ONCE: the thumbnail is stored beside
the PDF so lists and the Home widget never re-render. The
thumbnail is the flyer's own first page, small (480px wide
JPEG) — content, never decoration.
"""

import io

from PIL import Image

THUMB_WIDTH = 480


class RenderError(ValueError):
    """The bytes aren't a readable PDF."""


def pdf_thumbnail_jpeg(data: bytes) -> tuple[bytes, int]:
    """(thumbnail JPEG bytes, page count) for a PDF's first page."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        raise RenderError("That file isn't a readable PDF.") from exc
    try:
        count = len(pdf)
        if count == 0:
            raise RenderError("That PDF has no pages.")
        page = pdf[0]
        try:
            width, _height = page.get_size()
            scale = THUMB_WIDTH / width if width else 1.0
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
        finally:
            page.close()
    finally:
        pdf.close()
    if image.mode != "RGB":
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, "JPEG", quality=82)
    return out.getvalue(), count


def assemble_pdf(page_jpegs: list[bytes]) -> bytes:
    """Assemble cleaned page images into ONE PDF (the scanner's
    output). Pages keep their own sizes; 150 DPI metadata so
    viewers scale them sanely."""
    if not page_jpegs:
        raise RenderError("There are no pages to assemble.")
    images = []
    for raw in page_jpegs:
        image = Image.open(io.BytesIO(raw))
        if image.mode != "RGB":
            image = image.convert("RGB")
        images.append(image)
    out = io.BytesIO()
    first, rest = images[0], images[1:]
    first.save(
        out,
        "PDF",
        save_all=True,
        append_images=rest,
        resolution=150.0,
    )
    return out.getvalue()
