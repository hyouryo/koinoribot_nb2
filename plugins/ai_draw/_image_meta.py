import filetype


DEFAULT_IMAGE_FILENAME = "reference.png"
DEFAULT_IMAGE_CONTENT_TYPE = "image/png"


def detect_image_upload_meta(image_bytes: bytes) -> tuple[str, str]:
    """Return a filename and MIME type that match the uploaded image bytes."""
    kind = filetype.guess(image_bytes)
    if not kind or not kind.mime.startswith("image/"):
        return DEFAULT_IMAGE_FILENAME, DEFAULT_IMAGE_CONTENT_TYPE

    extension = kind.extension.lower()
    if extension == "jpeg":
        extension = "jpg"

    return f"reference.{extension}", kind.mime
