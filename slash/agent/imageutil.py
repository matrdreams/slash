"""Screenshot scaling and blunt redaction. Both operate on PNG bytes."""

from io import BytesIO

from PIL import Image, ImageDraw


def scale_long_edge(png: bytes, long_edge: int) -> bytes:
    if long_edge <= 0 or not png:
        return png
    with Image.open(BytesIO(png)) as image:
        width, height = image.size
        longest = max(width, height)
        if longest <= long_edge:
            return png
        ratio = long_edge / longest
        resized = image.convert("RGB").resize(
            (max(1, int(width * ratio)), max(1, int(height * ratio))),
            Image.Resampling.LANCZOS,
        )
    buffer = BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


def redact_png(png: bytes) -> bytes:
    """Cover the whole frame. Region-level masks need a detector we do not have yet."""
    with Image.open(BytesIO(png)) as image:
        canvas = image.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, canvas.width, canvas.height), fill=(0, 0, 0))
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
