"""Validation and sanitization for administrator-supplied HTML documents."""

from dataclasses import dataclass
import base64
import binascii
import hashlib
import hmac
from html import escape
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit


HTML_BODY_PREFIX = "<!-- ictlab:sanitized-html:v1:"
HTML_BODY_SEPARATOR = " -->"
IMAGE_PLACEHOLDER_PREFIX = "__ICTLAB_IMPORTED_IMAGE_"
MAX_ATTRIBUTE_LENGTH = 2_000

ALLOWED_TAGS = {
    "a", "abbr", "article", "b", "blockquote", "br", "caption", "code",
    "col", "colgroup", "dd", "del", "details", "div", "dl", "dt", "em",
    "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr",
    "i", "img", "li", "mark", "math", "menclose", "merror", "mfenced",
    "mfrac", "mi", "mmultiscripts", "mn", "mo", "mover", "mpadded",
    "mphantom", "mprescripts", "mroot", "mrow", "ms", "mspace", "msqrt",
    "mstyle", "msub", "msubsup", "msup", "mtable", "mtd", "mtext", "mtr",
    "munder", "munderover", "none", "ol", "p", "pre", "q", "s", "section",
    "semantics", "small", "span", "strong", "sub", "summary", "sup", "table",
    "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "annotation",
    "annotation-xml",
}
VOID_TAGS = {"br", "col", "hr", "img", "mspace", "none"}
DROP_CONTENT_TAGS = {"applet", "audio", "canvas", "embed", "form", "head", "iframe", "noscript", "object", "script", "style", "svg", "template", "video"}
GLOBAL_ATTRIBUTES = {"aria-label", "dir", "lang", "title"}
TAG_ATTRIBUTES = {
    "a": {"href"},
    "col": {"span"},
    "img": {"alt", "height", "width"},
    "ol": {"reversed", "start", "type"},
    "td": {"colspan", "headers", "rowspan"},
    "th": {"abbr", "colspan", "headers", "rowspan", "scope"},
    "math": {"display", "mathvariant"},
}
MATH_ATTRIBUTES = {
    "accent", "accentunder", "columnalign", "columnlines", "columnspacing",
    "columnspan", "denomalign", "depth", "display", "displaystyle", "encoding",
    "fence", "form", "height", "linethickness", "lspace", "mathbackground",
    "mathcolor", "mathsize", "mathvariant", "maxsize", "minsize", "movablelimits",
    "notation", "numalign", "open", "rowalign", "rowlines", "rowspacing",
    "rowspan", "rspace", "scriptlevel", "separator", "separators", "stretchy",
    "subscriptshift", "superscriptshift", "symmetric", "voffset", "width",
}
MATH_TAGS = {tag for tag in ALLOWED_TAGS if tag.startswith("m")} | {"annotation", "annotation-xml", "semantics"}
IMAGE_TYPES = {
    "image/png": ("png", b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": ("jpg", b"\xff\xd8\xff"),
    "image/gif": ("gif", (b"GIF87a", b"GIF89a")),
    "image/webp": ("webp", b"RIFF"),
}
DATA_IMAGE_RE = re.compile(r"^data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=\s]+)$", re.IGNORECASE)


class HtmlImportError(ValueError):
    """Raised when an uploaded document cannot be imported safely."""


@dataclass(frozen=True)
class ImportedImage:
    filename: str
    data: bytes


@dataclass(frozen=True)
class SanitizedDocument:
    html: str
    images: tuple[ImportedImage, ...]


def pack_sanitized_html(value: str, secret_key: str) -> str:
    signature = hmac.new(
        secret_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{HTML_BODY_PREFIX}{signature}{HTML_BODY_SEPARATOR}{value}"


def unpack_sanitized_html(value: str, secret_key: str) -> str | None:
    if not value.startswith(HTML_BODY_PREFIX):
        return None
    separator_at = value.find(HTML_BODY_SEPARATOR, len(HTML_BODY_PREFIX))
    if separator_at < 0:
        return None
    supplied = value[len(HTML_BODY_PREFIX):separator_at]
    body = value[separator_at + len(HTML_BODY_SEPARATOR):]
    expected = hmac.new(
        secret_key.encode("utf-8"), body.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if len(supplied) != 64 or not hmac.compare_digest(supplied, expected):
        return None
    return body


class _Sanitizer(HTMLParser):
    def __init__(self, max_image_bytes: int, max_images: int):
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.images: list[ImportedImage] = []
        self.max_image_bytes = max_image_bytes
        self.max_images = max_images
        self.drop_depth = 0
        self.open_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self.drop_depth:
            if tag in DROP_CONTENT_TAGS:
                self.drop_depth += 1
            return
        if tag in DROP_CONTENT_TAGS:
            self.drop_depth = 1
            return
        if tag not in ALLOWED_TAGS:
            return

        clean_attrs = self._clean_attrs(tag, attrs)
        if tag == "img":
            source = next((value for name, value in attrs if name.lower() == "src"), None)
            if not source:
                return
            placeholder = self._import_image(source)
            clean_attrs.append(("src", placeholder))

        rendered_attrs = "".join(
            f' {name}="{escape(value, quote=True)}"' if value else f" {name}"
            for name, value in clean_attrs
        )
        self.output.append(f"<{tag}{rendered_attrs}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.drop_depth:
            if tag in DROP_CONTENT_TAGS:
                self.drop_depth -= 1
            return
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self.open_tags:
            return
        while self.open_tags:
            current = self.open_tags.pop()
            self.output.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self.drop_depth:
            self.output.append(escape(data))

    def close_document(self) -> None:
        super().close()
        while self.open_tags:
            self.output.append(f"</{self.open_tags.pop()}>")

    def _clean_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
        allowed = GLOBAL_ATTRIBUTES | TAG_ATTRIBUTES.get(tag, set())
        if tag in MATH_TAGS:
            allowed |= MATH_ATTRIBUTES
        result = []
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = (raw_value or "").strip()
            if name not in allowed or len(value) > MAX_ATTRIBUTE_LENGTH:
                continue
            if name == "href" and not _safe_link(value):
                continue
            result.append((name, value))
        if tag == "a" and any(name == "href" for name, _ in result):
            result.extend((("rel", "noopener noreferrer"),))
        return result

    def _import_image(self, source: str) -> str:
        if len(self.images) >= self.max_images:
            raise HtmlImportError(f"이미지는 최대 {self.max_images}개까지 가져올 수 있습니다.")
        match = DATA_IMAGE_RE.fullmatch(source.strip())
        if not match:
            raise HtmlImportError("그림은 PNG, JPEG, GIF, WebP data: 이미지만 허용됩니다.")
        mime_type = match.group(1).lower()
        try:
            payload = base64.b64decode(re.sub(r"\s+", "", match.group(2)), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HtmlImportError("올바르지 않은 base64 이미지가 포함되어 있습니다.") from exc
        if not payload or len(payload) > self.max_image_bytes:
            raise HtmlImportError("이미지 한 개의 허용 크기를 초과했습니다.")
        extension, signature = IMAGE_TYPES[mime_type]
        valid_signature = any(payload.startswith(item) for item in signature) if isinstance(signature, tuple) else payload.startswith(signature)
        if mime_type == "image/webp":
            valid_signature = valid_signature and len(payload) >= 12 and payload[8:12] == b"WEBP"
        if not valid_signature:
            raise HtmlImportError("이미지 형식과 실제 파일 내용이 일치하지 않습니다.")
        filename = f"image-{len(self.images) + 1}.{extension}"
        self.images.append(ImportedImage(filename, payload))
        return f"{IMAGE_PLACEHOLDER_PREFIX}{len(self.images) - 1}__"


def sanitize_html_document(payload: bytes, *, max_bytes: int, max_image_bytes: int, max_images: int) -> SanitizedDocument:
    if not payload:
        raise HtmlImportError("HTML 파일이 비어 있습니다.")
    if len(payload) > max_bytes:
        raise HtmlImportError("HTML 파일의 허용 크기를 초과했습니다.")
    try:
        source = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HtmlImportError("HTML 파일은 UTF-8 인코딩이어야 합니다.") from exc
    parser = _Sanitizer(max_image_bytes, max_images)
    try:
        parser.feed(source)
        parser.close_document()
    except (RecursionError, AssertionError) as exc:
        raise HtmlImportError("HTML 구조를 해석할 수 없습니다.") from exc
    sanitized = "".join(parser.output).strip()
    if not sanitized:
        raise HtmlImportError("가져올 수 있는 본문 내용이 없습니다.")
    return SanitizedDocument(sanitized, tuple(parser.images))


def _safe_link(value: str) -> bool:
    if not value or value.startswith(("#", "/")):
        return True
    return urlsplit(value).scheme.lower() in {"http", "https", "mailto"}
