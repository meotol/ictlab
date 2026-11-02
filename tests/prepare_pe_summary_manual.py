"""Prepare an isolated manual-validation DB and local upload fixtures."""
import argparse
import math
from pathlib import Path
import struct
import shutil
import wave
import zipfile

from ictlab import create_app
from ictlab.db import Base, get_db_engine


def fixtures(root: Path) -> None:
    fixture_root = root / "fixtures"
    fixture_root.mkdir(parents=True, exist_ok=True)
    (fixture_root / "summary.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )
    with zipfile.ZipFile(fixture_root / "summary.docx", "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>ICT Lab DOCX validation</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(fixture_root / "summary.hwpx", "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/content.hpf", "<package>ICT Lab HWPX validation</package>")
    hwp = bytearray(1024)
    hwp[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    hwp[24:28] = bytes.fromhex("3E000300")
    hwp[28:30] = bytes.fromhex("FEFF")
    hwp[30:34] = bytes.fromhex("09000600")
    hwp[48:52] = (0).to_bytes(4, "little")
    file_header_name = "FileHeader\0".encode("utf-16le")
    hwp[512 : 512 + len(file_header_name)] = file_header_name
    hwp[576:578] = len(file_header_name).to_bytes(2, "little")
    hwp[578] = 2
    (fixture_root / "summary.hwp").write_bytes(hwp)
    wav_path = fixture_root / "memory.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setparams((1, 2, 22050, 22050, "NONE", "not compressed"))
        output.writeframes(b"".join(struct.pack("<h", int(10000 * math.sin(2 * math.pi * 440 * index / 22050))) for index in range(22050)))
    mp3_sample = Path("/usr/local/Homebrew/Library/Homebrew/test/support/fixtures/test.mp3")
    mp4_sample = Path("/usr/local/Homebrew/Library/Homebrew/test/support/fixtures/test.mp4")
    if not mp3_sample.is_file() or not mp4_sample.is_file():
        raise RuntimeError("Local playable MP3/MP4 validation fixtures are unavailable")
    shutil.copyfile(mp3_sample, fixture_root / "memory.mp3")
    shutil.copyfile(mp4_sample, fixture_root / "memory.mp4")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    fixtures(args.root)
    app = create_app()
    with app.app_context():
        Base.metadata.create_all(get_db_engine())
    print(args.root)


if __name__ == "__main__":
    main()
