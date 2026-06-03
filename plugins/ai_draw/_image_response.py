import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any


class ImageResponseParseError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageReference:
    url: str | None = None
    b64_json: str | None = None


def parse_image_response_json(body: bytes, content_type: str = "") -> dict[str, Any]:
    content_type = _normalize_content_type(content_type)
    if not body:
        raise ImageResponseParseError(
            f"empty response body; content_type={content_type}"
        )

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImageResponseParseError(
            f"response body is not UTF-8 JSON; content_type={content_type}"
        ) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImageResponseParseError(
            "response body is not JSON; "
            f"content_type={content_type}; body_preview={_one_line(text[:200])}"
        ) from exc

    if not isinstance(data, dict):
        raise ImageResponseParseError(
            f"expected JSON object, got {type(data).__name__}"
        )
    return data


def extract_image_reference(data: dict[str, Any]) -> ImageReference:
    api_error = data.get("error") or data.get("RelayError")
    if api_error:
        raise ImageResponseParseError(f"API returned error: {_error_message(api_error)}")

    items = data.get("data")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        raise ImageResponseParseError("missing JSON field: data[0]")

    item = items[0]
    url = item.get("url")
    if isinstance(url, str) and url:
        return ImageReference(url=url)

    b64_json = item.get("b64_json")
    if isinstance(b64_json, str) and b64_json:
        return ImageReference(b64_json=b64_json)

    raise ImageResponseParseError("missing JSON field: data[0].url or data[0].b64_json")


def decode_base64_image(value: str) -> bytes:
    if value.startswith("data:"):
        _, sep, value = value.partition(",")
        if not sep:
            raise ImageResponseParseError("invalid data URL image payload")

    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageResponseParseError("image base64 decode failed") from exc


def format_response_body_dump(body: bytes, content_type: str = "") -> str:
    content_type = _normalize_content_type(content_type)
    header = f"content_type={content_type}\nbody_bytes={len(body)}"
    if not body:
        return f"{header}\nbody=<empty>"

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return f"{header}\nbody_encoding=hex\nbody={body.hex()}"

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return f"{header}\nbody_encoding=utf-8\nbody={text}"

    return f"{header}\nbody_encoding=utf-8\nbody_json={format_response_json_dump(data)}"


def format_response_json_dump(data: Any) -> str:
    return json.dumps(_shorten_base64_fields(data), ensure_ascii=False, indent=2)


def _shorten_base64_fields(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _shorten_base64_fields(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten_base64_fields(item, key) for item in value]
    if isinstance(value, str) and _is_base64_key(key):
        return _shorten_base64_string(value)
    return value


def _is_base64_key(key: str) -> bool:
    normalized = key.lower()
    return "b64" in normalized or "base64" in normalized


def _shorten_base64_string(value: str) -> str:
    if value.startswith("data:") and "," in value:
        prefix, b64_value = value.split(",", 1)
        if len(b64_value) > 10:
            return f"{prefix},{b64_value[:10]}..."
        return value
    if len(value) > 10:
        return f"{value[:10]}..."
    return value


def _normalize_content_type(content_type: str) -> str:
    return (content_type or "unknown").split(";", 1)[0].strip().lower() or "unknown"


def _error_message(error: Any) -> str:
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error)


def _one_line(text: str) -> str:
    return " ".join(text.split())
