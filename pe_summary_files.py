import hashlib
from pathlib import Path
import shutil
import subprocess
import uuid
import zipfile
import unicodedata
import warnings

from PIL import Image, UnidentifiedImageError

from werkzeug.datastructures import FileStorage


IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
MAX_IMAGE_PIXELS = 25_000_000

ALLOWED = {
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".webp": ("image", "image/webp"),
    ".pdf": ("document", "application/pdf"),
    ".docx": ("document", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".hwp": ("document", "application/x-hwp"),
    ".hwpx": ("document", "application/vnd.hancom.hwpx"),
    ".mp3": ("audio", "audio/mpeg"),
    ".wav": ("audio", "audio/wav"),
    ".mp4": ("video", "video/mp4"),
}


class UploadError(ValueError):
    pass


def _valid_signature(extension: str, data: bytes, path: Path) -> bool:
    if extension == ".pdf":
        return data.startswith(b"%PDF-")
    if extension == ".hwp":
        try:
            with path.open("rb") as source:
                header = source.read(512)
                if (
                    len(header) != 512
                    or not header.startswith(bytes.fromhex("D0CF11E0A1B11AE1"))
                    or header[28:30] != b"\xfe\xff"
                ):
                    return False
                major_version = int.from_bytes(header[26:28], "little")
                sector_shift = int.from_bytes(header[30:32], "little")
                if (major_version, sector_shift) not in {(3, 9), (4, 12)}:
                    return False
                directory_sector = int.from_bytes(header[48:52], "little")
                if directory_sector >= 0xFFFFFFFA:
                    return False
                sector_size = 1 << sector_shift
                source.seek((directory_sector + 1) * sector_size)
                directory = source.read(sector_size)
            for offset in range(0, len(directory), 128):
                entry = directory[offset : offset + 128]
                if len(entry) < 128:
                    continue
                name_length = int.from_bytes(entry[64:66], "little")
                if 2 <= name_length <= 64 and name_length % 2 == 0:
                    name = entry[: name_length - 2].decode("utf-16le", errors="ignore")
                    if name == "FileHeader" and entry[66] == 2:
                        return True
            return False
        except OSError:
            return False
    if extension in {".docx", ".hwpx"}:
        if not data.startswith(b"PK"):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
            return ("[Content_Types].xml" in names if extension == ".docx" else "Contents/content.hpf" in names)
        except (zipfile.BadZipFile, OSError):
            return False
    if extension == ".wav":
        return data.startswith(b"RIFF") and data[8:12] == b"WAVE"
    if extension == ".mp4":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if extension == ".mp3":
        return data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    return False


def save_upload(upload: FileStorage, directory: Path, max_bytes: int) -> dict:
    raw_name = unicodedata.normalize("NFC", upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    original = "".join(character for character in raw_name if character.isprintable()).strip().strip(".")[:255]
    extension = Path(original).suffix.lower()
    if not original or extension not in ALLOWED:
        raise UploadError("허용되지 않은 파일 형식입니다.")
    if extension in IMAGE_FORMATS and upload.mimetype not in {ALLOWED[extension][1], "application/octet-stream", ""}:
        raise UploadError("이미지 확장자와 MIME 형식이 일치하지 않습니다.")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    destination = directory / stored_name
    digest = hashlib.sha256()
    size = 0
    try:
        with destination.open("xb") as output:
            while chunk := upload.stream.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(f"파일 크기는 {max_bytes // (1024 * 1024)}MB 이하여야 합니다.")
                digest.update(chunk)
                output.write(chunk)
        destination.chmod(0o600)
        with destination.open("rb") as source:
            header = source.read(16)
        if extension in IMAGE_FORMATS:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(destination) as image:
                        if image.format != IMAGE_FORMATS[extension] or image.width * image.height > MAX_IMAGE_PIXELS or getattr(image, "n_frames", 1) != 1:
                            raise UploadError("이미지 형식이 일치하지 않거나 크기 제한(2,500만 화소)을 초과했거나 애니메이션입니다.")
                        image.verify()
                    with Image.open(destination) as image:
                        image.load()
            except UploadError:
                raise
            except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise UploadError(f"{original}: 유효한 이미지 파일이 아닙니다.") from exc
        elif not _valid_signature(extension, header, destination):
            raise UploadError(f"{original}: 확장자와 파일 시그니처가 일치하지 않습니다.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    kind, mime_type = ALLOWED[extension]
    return {"original_name": original, "stored_name": stored_name, "kind": kind, "mime_type": mime_type, "size_bytes": size, "sha256": digest.hexdigest(), "path": destination}


def make_pdf_preview(source: Path, directory: Path, timeout: int) -> tuple[str | None, str]:
    if source.suffix.lower() == ".pdf":
        preview_name = f"{uuid.uuid4().hex}.preview.pdf"
        preview_path = directory / preview_name
        shutil.copyfile(source, preview_path)
        preview_path.chmod(0o600)
        return preview_name, "original_pdf"
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        return None, "tool_unavailable"
    conversion_dir = directory / f"convert-{uuid.uuid4().hex}"
    conversion_dir.mkdir(mode=0o700)
    try:
        result = subprocess.run([executable, "--headless", "--convert-to", "pdf", "--outdir", str(conversion_dir), str(source)], capture_output=True, timeout=timeout, check=False)
        output = conversion_dir / f"{source.stem}.pdf"
        signature = b""
        if output.is_file():
            with output.open("rb") as converted:
                signature = converted.read(5)
        if result.returncode or not output.is_file() or output.stat().st_size < 5 or signature != b"%PDF-":
            return None, "conversion_failed"
        preview_name = f"{uuid.uuid4().hex}.pdf"
        output.replace(directory / preview_name)
        (directory / preview_name).chmod(0o600)
        return preview_name, "converted_unverified"
    except (OSError, subprocess.TimeoutExpired):
        return None, "conversion_failed"
    finally:
        shutil.rmtree(conversion_dir, ignore_errors=True)
