from io import BytesIO
import re
from pathlib import Path
import tempfile
import unittest
import zipfile

from sqlalchemy import select

from ictlab import create_app
from ictlab.db import Base, get_db_engine, get_db_session
from ictlab.models import PeSummary, PeSummaryAsset


PDF = b"%PDF-1.4\n%%EOF\n"
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"audio-data"


class PeSummaryRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)

        class TestConfig:
            TESTING = True
            SECRET_KEY = "test-only"
            ENVIRONMENT = "testing"
            DATABASE_URL = f"sqlite:///{root / 'test.sqlite'}"
            DATABASE_ENGINE_OPTIONS = {}
            ADMIN_USERNAME = "admin"
            ADMIN_PASSWORD_HASH = "unused"
            CONTENT_UPLOAD_ROOT = str(root / "content")
            PE_SUMMARY_UPLOAD_ROOT = str(root / "summaries")
            PE_SUMMARY_MAX_FILE_BYTES = 1024 * 1024
            PE_SUMMARY_MAX_FILES = 5
            PE_SUMMARY_CONVERSION_TIMEOUT = 1
            MAX_HTML_IMPORT_BYTES = 100_000
            MAX_HTML_IMAGE_BYTES = 10_000
            MAX_HTML_IMAGES = 3

        self.app = create_app(TestConfig)
        with self.app.app_context():
            Base.metadata.create_all(get_db_engine())
        self.client = self.app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["is_admin"] = True
            browser_session["csrf_token"] = "csrf"

    def tearDown(self):
        self.tempdir.cleanup()

    def create_summary(self, status="published"):
        return self.client.post("/admin/pe-summaries/new", data={
            "csrf_token": "csrf", "title": "OSI 7계층 핵심", "field": "정보통신망",
            "keywords": "OSI, 네트워크", "description": "요약", "status": status,
            "lyrics": "일곱 계층을 외우자", "files": [
                (BytesIO(PDF), "../기술사-답안.pdf", "application/pdf"),
                (BytesIO(MP3), "memory.mp3", "audio/mpeg"),
            ],
        }, content_type="multipart/form-data")

    def test_admin_uploads_multiple_files_and_public_can_search_and_range_stream(self):
        response = self.create_summary()
        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            summary = get_db_session().scalar(select(PeSummary))
            assets = get_db_session().scalars(select(PeSummaryAsset).order_by(PeSummaryAsset.id)).all()
            self.assertEqual(2, len(assets))
            self.assertEqual("기술사-답안.pdf", assets[0].original_name)
            self.assertNotEqual(assets[0].stored_name, assets[0].preview_name)
            self.assertEqual("일곱 계층을 외우자", assets[1].lyrics)
            summary_id, pdf_id, audio_id = summary.id, assets[0].id, assets[1].id
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        listing = self.client.get("/pe-summaries?q=OSI&field=정보통신망")
        self.assertIn("OSI 7계층 핵심".encode(), listing.data)
        detail = self.client.get(f"/pe-summaries/{summary_id}")
        self.assertIn("ICT Lab | 기술사 서머리 | 열람용".encode(), (Path(__file__).parents[1] / "static/js/pe_summary_player.js").read_bytes())
        self.assertIn(b'controlslist="nodownload"', detail.data)
        self.assertIn(b'id="audio_repeat"', detail.data)
        self.assertIn(b'aria-controls="summary_audio" aria-pressed="false"', detail.data)
        self.assertIn("반복재생 켜기".encode(), detail.data)
        self.assertNotIn(b' loop', detail.data)
        self.assertIn(b"data-zoom-in", detail.data)
        self.assertIn(b"data-pdf-pages", detail.data)
        self.assertIn(b"pdf.min.mjs", (Path(__file__).parents[1] / "static/js/pe_summary_player.js").read_bytes())
        self.assertNotIn("원본 다운로드".encode(), detail.data)
        self.assertNotIn("원본 열람·인쇄".encode(), detail.data)
        self.assertNotIn(b">\xeb\x8b\xa4\xec\x9a\xb4\xeb\xa1\x9c\xeb\x93\x9c<", detail.data)
        self.assertEqual(403, self.client.get(f"/pe-summaries/{summary_id}/assets/{pdf_id}/download").status_code)
        self.assertEqual(403, self.client.get(f"/pe-summaries/{summary_id}/assets/{pdf_id}/original").status_code)
        self.assertEqual(403, self.client.get(f"/pe-summaries/{summary_id}/assets/{pdf_id}/view").status_code)
        self.assertEqual(403, self.client.get(f"/pe-summaries/{summary_id}/assets/{audio_id}/download").status_code)
        preview_url = f"/pe-summaries/{summary_id}/assets/{pdf_id}/preview"
        self.assertEqual(403, self.client.get(preview_url).status_code)
        token = re.search(rb'data-preview-token="([^"]+)"', detail.data).group(1).decode()
        preview = self.client.get(preview_url, headers={"X-ICTLab-Preview": token})
        self.assertEqual(PDF, preview.data)
        preview.close()
        partial = self.client.get(f"/pe-summaries/{summary_id}/assets/{audio_id}/view", headers={"Range": "bytes=0-2"})
        self.assertEqual(206, partial.status_code)
        self.assertEqual(b"ID3", partial.data)
        self.assertEqual("bytes 0-2/20", partial.headers["Content-Range"])
        partial.close()
        with self.client.session_transaction() as browser_session:
            browser_session["is_admin"] = True
            browser_session["csrf_token"] = "csrf"
        admin_detail = self.client.get(f"/pe-summaries/{summary_id}")
        self.assertIn("원본 다운로드".encode(), admin_detail.data)
        self.assertIn("원본 열람·인쇄".encode(), admin_detail.data)
        original = self.client.get(f"/pe-summaries/{summary_id}/assets/{pdf_id}/download")
        self.assertEqual(PDF, original.data)
        self.assertTrue(original.headers["Content-Disposition"].startswith("attachment;"))
        original.close()

    def test_unconvertible_docx_has_no_public_original_link(self):
        document = BytesIO()
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
        document.seek(0)
        response = self.client.post("/admin/pe-summaries/new", data={
            "csrf_token": "csrf", "title": "DOCX", "field": "정보통신망", "keywords": "",
            "description": "", "status": "published", "lyrics": "",
            "files": (document, "answer.docx"),
        }, content_type="multipart/form-data")
        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            summary = get_db_session().scalar(select(PeSummary))
            asset = summary.assets[0]
            self.assertEqual("tool_unavailable", asset.conversion_status)
            summary_id, asset_id = summary.id, asset.id
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        detail = self.client.get(f"/pe-summaries/{summary_id}")
        self.assertIn("미리보기가 없어 열람할 수 없습니다".encode(), detail.data)
        self.assertNotIn("원본 다운로드".encode(), detail.data)
        self.assertEqual(403, self.client.get(f"/pe-summaries/{summary_id}/assets/{asset_id}/download").status_code)
        self.assertEqual(404, self.client.get(f"/pe-summaries/{summary_id}/assets/{asset_id + 999}/download").status_code)

    def test_admin_edits_existing_media_lyrics_without_reuploading_files(self):
        self.create_summary()
        with self.app.app_context():
            summary = get_db_session().scalar(select(PeSummary))
            audio = next(asset for asset in summary.assets if asset.kind == "audio")
            audio.lyrics = "기존 1절\n\nSIP & RTP <핵심>"
            video = PeSummaryAsset(
                summary_id=summary.id, kind="video", original_name="lecture.mp4",
                stored_name="existing-video.mp4", mime_type="video/mp4", size_bytes=10,
                sha256="0" * 64, conversion_status="not_applicable", lyrics=None,
            )
            get_db_session().add(video)
            get_db_session().commit()
            summary_id, audio_id, video_id = summary.id, audio.id, video.id
            original_assets = [
                (asset.id, asset.original_name, asset.stored_name)
                for asset in get_db_session().scalars(
                    select(PeSummaryAsset).where(PeSummaryAsset.summary_id == summary.id).order_by(PeSummaryAsset.id)
                ).all()
            ]

        edit = self.client.get(f"/admin/pe-summaries/{summary_id}/edit")
        self.assertIn(f'name="existing_lyrics_{audio_id}"'.encode(), edit.data)
        self.assertIn("기존 1절\n\nSIP &amp; RTP &lt;핵심&gt;".encode(), edit.data)
        self.assertIn(f'name="existing_lyrics_{video_id}"'.encode(), edit.data)
        self.assertIn(b'name="lyrics"', edit.data)
        self.assertIn(b"data-new-media-lyrics hidden", edit.data)
        form_script = (Path(__file__).parents[1] / "static/js/pe_summary_form.js").read_text()
        self.assertIn("files.addEventListener(\"change\"", form_script)
        self.assertIn("(mp3|wav|mp4)", form_script)

        updated_audio = "  수정 1절\n\nIMS/SIP & RTP <원문>  "
        updated_video = "새 영상 가사\n2행: 5G·AI #1"
        response = self.client.post(f"/admin/pe-summaries/{summary_id}/edit", data={
            "csrf_token": "csrf", "title": "OSI 7계층 핵심", "field": "정보통신망",
            "keywords": "OSI, 네트워크", "description": "요약", "status": "published",
            "lyrics": "", f"existing_lyrics_{audio_id}": updated_audio,
            f"existing_lyrics_{video_id}": updated_video,
        })
        self.assertEqual(302, response.status_code)

        with self.app.app_context():
            assets = get_db_session().scalars(
                select(PeSummaryAsset).where(PeSummaryAsset.summary_id == summary_id).order_by(PeSummaryAsset.id)
            ).all()
            self.assertEqual(original_assets, [(asset.id, asset.original_name, asset.stored_name) for asset in assets])
            lyrics = {asset.id: asset.lyrics for asset in assets}
            self.assertEqual(updated_audio, lyrics[audio_id])
            self.assertEqual(updated_video, lyrics[video_id])

        detail = self.client.get(f"/pe-summaries/{summary_id}")
        self.assertIn("수정 1절\n\nIMS/SIP &amp; RTP &lt;원문&gt;".encode(), detail.data)
        self.assertIn("새 영상 가사\n2행: 5G·AI #1".encode(), detail.data)

    def test_private_summary_and_files_are_hidden_from_public(self):
        self.create_summary("private")
        with self.app.app_context():
            summary = get_db_session().scalar(select(PeSummary))
            asset = summary.assets[0]
            summary_id, asset_id = summary.id, asset.id
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(404, self.client.get(f"/pe-summaries/{summary_id}").status_code)
        self.assertEqual(404, self.client.get(f"/pe-summaries/{summary_id}/assets/{asset_id}/download").status_code)
        self.assertNotIn("OSI 7계층 핵심".encode(), self.client.get("/pe-summaries").data)

    def test_rejects_spoofed_extension_and_requires_admin(self):
        bad = self.client.post("/admin/pe-summaries/new", data={
            "csrf_token": "csrf", "title": "위조", "field": "보안", "keywords": "", "description": "",
            "status": "published", "lyrics": "", "files": (BytesIO(b"not a pdf"), "fake.pdf"),
        }, content_type="multipart/form-data")
        self.assertEqual(200, bad.status_code)
        self.assertIn("시그니처".encode(), bad.data)
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(302, self.client.get("/admin/pe-summaries/new").status_code)

    def test_audio_download_is_admin_only_and_not_cached(self):
        self.create_summary()
        with self.app.app_context():
            audio = get_db_session().scalar(select(PeSummaryAsset).where(PeSummaryAsset.kind == "audio"))
            summary_id, audio_id = audio.summary_id, audio.id
        detail_url = f"/pe-summaries/{summary_id}"
        download_url = f"{detail_url}/assets/{audio_id}/download"
        detail = self.client.get(detail_url)
        self.assertNotIn(b'controlslist="nodownload"', detail.data)
        response = self.client.get(download_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(MP3, response.data)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual("private, no-store", response.headers["Cache-Control"])
        response.close()
        with self.client.session_transaction() as browser_session:
            browser_session.clear()
        self.assertEqual(403, self.client.get(download_url).status_code)
        self.assertIn(b'controlslist="nodownload"', self.client.get(detail_url).data)
        stream = self.client.get(f"{detail_url}/assets/{audio_id}/view", headers={"Range": "bytes=0-2"})
        self.assertEqual(206, stream.status_code)
        stream.close()

    def test_rejects_hwp_with_only_an_ole_magic_header(self):
        fake_hwp = bytes.fromhex("D0CF11E0A1B11AE1") + bytes(504)
        response = self.client.post("/admin/pe-summaries/new", data={
            "csrf_token": "csrf", "title": "손상 HWP", "field": "보안", "keywords": "",
            "description": "", "status": "private", "lyrics": "",
            "files": (BytesIO(fake_hwp), "broken.hwp"),
        }, content_type="multipart/form-data")
        self.assertEqual(200, response.status_code)
        self.assertIn("시그니처".encode(), response.data)


if __name__ == "__main__":
    unittest.main()
