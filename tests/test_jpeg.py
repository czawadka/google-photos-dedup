import io

from PIL import Image

from gpdedup.jpeg import read_jpeg_dimensions


def _jpeg(size):
    buf = io.BytesIO()
    Image.new("RGB", size, (123, 50, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_reads_dimensions():
    assert read_jpeg_dimensions(_jpeg((640, 480))) == (640, 480)
    assert read_jpeg_dimensions(_jpeg((1920, 1080))) == (1920, 1080)


def test_rejects_non_jpeg():
    import pytest

    with pytest.raises(ValueError):
        read_jpeg_dimensions(b"\x89PNG\r\n\x1a\n not a jpeg")
