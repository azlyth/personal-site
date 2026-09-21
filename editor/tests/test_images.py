import io

from PIL import Image

from editor.images import process_image, image_key, markdown_for, upload


def _jpeg_with_exif(size=(2400, 1800)) -> bytes:
    img = Image.new("RGB", size, (120, 140, 90))
    exif = Image.Exif()
    exif[0x010F] = "TestCamera"   # Make
    exif[0x8825] = {}             # GPSInfo slot
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_process_strips_exif():
    out = process_image(_jpeg_with_exif())
    assert dict(Image.open(io.BytesIO(out)).getexif()) == {}


def test_process_caps_longest_edge():
    out = process_image(_jpeg_with_exif((2400, 1800)), max_edge=1600)
    assert max(Image.open(io.BytesIO(out)).size) == 1600


def test_process_leaves_small_images_alone():
    small = _jpeg_with_exif((400, 300))
    out = process_image(small, max_edge=1600)
    assert Image.open(io.BytesIO(out)).size == (400, 300)


def test_key_is_descriptive_and_content_addressed():
    data = _jpeg_with_exif()
    key = image_key("guerilla-gardening", "Brick Border!", data)
    assert key.startswith("guerilla-gardening/brick-border-")
    assert key.endswith(".jpg")


def test_same_bytes_produce_the_same_key():
    data = _jpeg_with_exif()
    assert image_key("p", "a", data) == image_key("p", "a", data)


def test_key_without_alt_text_still_works():
    key = image_key("p", "", _jpeg_with_exif())
    assert key.startswith("p/")
    assert key.endswith(".jpg")


def test_single_image_renders_standalone():
    out = markdown_for(["https://img.cloudy.nyc/p/a.jpg"], ["a cat"])
    assert out == "![a cat](https://img.cloudy.nyc/p/a.jpg)"


def test_multiple_images_render_as_img_row():
    out = markdown_for(
        ["https://img.cloudy.nyc/p/a.jpg", "https://img.cloudy.nyc/p/b.jpg"],
        ["a", "b"],
    )
    assert out.startswith('<div class="img-row">')
    assert out.rstrip().endswith("</div>")
    assert out.count("<img ") == 2


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_upload_sets_immutable_cache_headers():
    client = FakeS3()
    url = upload(b"bytes", "p/a.jpg", "img.cloudy.nyc", client)

    call = client.calls[0]
    assert call["Bucket"] == "img.cloudy.nyc"
    assert call["Key"] == "p/a.jpg"
    assert call["ContentType"] == "image/jpeg"
    assert call["CacheControl"] == "public, max-age=31536000, immutable"
    assert url == "https://img.cloudy.nyc/p/a.jpg"
