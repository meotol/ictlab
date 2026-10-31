import base64
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from sqlalchemy import select

from ictlab import create_app
from ictlab.db import Base, get_db_engine, get_db_session
from ictlab.html_import import HTML_BODY_PREFIX, HtmlImportError, sanitize_html_document, unpack_sanitized_html
from ictlab.models import CONTENT_TYPE_PE_QA, Content, NewsArticle


PNG_DATA = b"\x89PNG\r\n\x1a\n" + b"test-image"


class HtmlSanitizerTests(unittest.TestCase):
    def sanitize(self, source: str):
        return sanitize_html_document(
            source.encode(), max_bytes=100_000, max_image_bytes=10_000, max_images=3
        )

    def test_keeps_document_content_mathml_and_data_image(self):
        encoded = base64.b64encode(PNG_DATA).decode()
        result = self.sanitize(
            '<h1>제목</h1><p>문단</p><table><tr><th>항목</th><td>값</td></tr></table>'
            '<ul><li>목록</li></ul><math display="block"><mfrac><mi>x</mi><mn>2</mn></mfrac></math>'
            f'<img src="data:image/png;base64,{encoded}" alt="그림">'
        )
        self.assertIn("<table>", result.html)
        self.assertIn('<math display="block">', result.html)
        self.assertEqual(PNG_DATA, result.images[0].data)

    def test_removes_scripts_events_styles_and_unsafe_links(self):
        result = self.sanitize(
            '<script>alert(1)</script><p onclick="alert(2)" style="color:red">안전</p>'
            '<a href="javascript:alert(3)">링크</a><iframe src="https://bad.test">bad</iframe>'
        )
        self.assertEqual("<p>안전</p><a>링크</a>", result.html)

    def test_preserves_image_geometry_and_missing_image_notice(self):
        encoded = base64.b64encode(PNG_DATA).decode()
        result = self.sanitize(
            f'<img src="data:image/png;base64,{encoded}" width="640" height="360" style="width:999px">'
            '<figure class="missing-image evil"><div>잘못된 표시</div></figure>'
            '<figure class="missing-image"><div>이미지 누락: 복구 불가</div></figure>'
        )
        self.assertIn('width="640" height="360"', result.html)
        self.assertNotIn("style=", result.html)
        self.assertNotIn('class="missing-image evil"', result.html)
        self.assertIn('<figure class="missing-image">', result.html)

    def test_rejects_non_utf8_and_mismatched_image_signature(self):
        with self.assertRaises(HtmlImportError):
            sanitize_html_document(
                b"\xff\xfe", max_bytes=100, max_image_bytes=100, max_images=1
            )
        bad_image = base64.b64encode(b"not-png").decode()
        with self.assertRaises(HtmlImportError):
            self.sanitize(f'<img src="data:image/png;base64,{bad_image}">')

    def test_rejects_relative_and_external_images(self):
        for source in ("images/diagram.png", "https://example.test/diagram.png"):
            with self.subTest(source=source), self.assertRaises(HtmlImportError):
                self.sanitize(f'<img src="{source}" alt="diagram">')


class HtmlImportRouteTests(unittest.TestCase):
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
            CONTENT_UPLOAD_ROOT = str(root / "uploads")
            MAX_HTML_IMPORT_BYTES = 100_000
            MAX_HTML_IMAGE_BYTES = 10_000
            MAX_HTML_IMAGES = 3

        self.app = create_app(TestConfig)
        with self.app.app_context():
            Base.metadata.create_all(get_db_engine())
        self.client = self.app.test_client()
        with self.client.session_transaction() as browser_session:
            browser_session["is_admin"] = True
            browser_session["csrf_token"] = "test-csrf"

    def tearDown(self):
        self.tempdir.cleanup()

    def test_admin_import_persists_sanitized_html_and_image(self):
        encoded = base64.b64encode(PNG_DATA).decode()
        document = (
            '<h1>답안</h1><script>alert(1)</script>'
            '<table><thead><tr><th colspan="2">구분</th></tr></thead>'
            '<tbody><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></tbody></table>'
            '<math display="block"><msup><mi>x</mi><mn>2</mn></msup></math>'
            f'<img src="data:image/png;base64,{encoded}" alt="구성도">'
        ).encode()
        response = self.client.post(
            "/admin/content/new",
            data={
                "csrf_token": "test-csrf",
                "title": "HTML 답안",
                "content_type": CONTENT_TYPE_PE_QA,
                "body": "",
                "authored_at": "2026-10-31",
                "status": "published",
                "html_file": (BytesIO(document), "answer.html", "text/html"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            content = get_db_session().scalar(select(Content))
            imported_body = unpack_sanitized_html(content.body, self.app.config["SECRET_KEY"])
            self.assertIsNotNone(imported_body)
            self.assertNotIn("script", content.body)
            self.assertIn('colspan="2"', imported_body)
            self.assertIn('rowspan="2"', imported_body)
            self.assertIn("<msup><mi>x</mi><mn>2</mn></msup>", imported_body)
            self.assertIn(f"/contents/{content.id}/images/image-1.png", content.body)
            image_path = Path(self.app.config["CONTENT_UPLOAD_ROOT"]) / str(content.id) / "image-1.png"
            self.assertEqual(PNG_DATA, image_path.read_bytes())
            content_id = content.id

        detail = self.client.get(f"/contents/{content_id}")
        self.assertIn(b"<table>", detail.data)
        self.assertIn(b'colspan="2"', detail.data)
        self.assertIn(b'rowspan="2"', detail.data)
        self.assertIn(b"<msup><mi>x</mi><mn>2</mn></msup>", detail.data)
        image = self.client.get(f"/contents/{content_id}/images/image-1.png")
        self.assertEqual(PNG_DATA, image.data)
        image.close()

        edit = self.client.post(
            f"/admin/contents/{content_id}/edit",
            data={
                "csrf_token": "test-csrf",
                "title": "수정된 제목",
                "content_type": CONTENT_TYPE_PE_QA,
                "body": '<script>alert("bypass")</script>',
                "authored_at": "2026-10-31",
                "status": "published",
            },
        )
        self.assertEqual(200, edit.status_code)
        with self.app.app_context():
            content = get_db_session().get(Content, content_id)
            self.assertIsNotNone(
                unpack_sanitized_html(content.body, self.app.config["SECRET_KEY"])
            )
            self.assertNotIn("bypass", content.body)

        traversal = self.client.get(
            f"/contents/{content_id}/images/%2e%2e%2f%2e%2e%2fconfig.py"
        )
        self.assertEqual(404, traversal.status_code)

    def test_rich_paste_persists_format_mathml_and_clipboard_image(self):
        encoded = base64.b64encode(PNG_DATA).decode()
        rich_body = (
            '<h2>정기 브리핑</h2><p><strong>핵심</strong> 내용</p>'
            '<table><tr><th>구분</th><th>설명</th></tr><tr><td>A</td><td>B</td></tr></table>'
            '<ol><li>첫째</li><li>둘째</li></ol>'
            '<math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>'
            f'<img src="data:image/png;base64,{encoded}" alt="클립보드 그림">'
        )
        response = self.client.post(
            "/admin/content/new",
            data={
                "csrf_token": "test-csrf",
                "title": "서식 붙여넣기",
                "content_type": CONTENT_TYPE_PE_QA,
                "body_format": "rich_html",
                "body": rich_body,
                "authored_at": "2026-10-31",
                "status": "published",
            },
        )
        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            content = get_db_session().scalar(select(Content))
            imported = unpack_sanitized_html(content.body, self.app.config["SECRET_KEY"])
            self.assertIn("<table>", imported)
            self.assertIn("<mfrac><mi>a</mi><mi>b</mi></mfrac>", imported)
            self.assertIn(f"/contents/{content.id}/images/image-1.png", imported)
            content_id = content.id
        detail = self.client.get(f"/contents/{content_id}")
        self.assertIn(b"<strong>", detail.data)
        self.assertIn(b"<table>", detail.data)
        self.assertIn(b"<math>", detail.data)

        edit_form = self.client.get(f"/admin/contents/{content_id}/edit")
        self.assertEqual(200, edit_form.status_code)
        self.assertIn(b'contenteditable="true"', edit_form.data)
        self.assertIn(b'tabindex="0"', edit_form.data)
        self.assertIn(b"data-trusted-html=\"true\"", edit_form.data)
        self.assertIn(b"\\u003cmfrac", edit_form.data)

        original_image = (
            Path(self.app.config["CONTENT_UPLOAD_ROOT"])
            / str(content_id)
            / "image-1.png"
        )
        original_image_bytes = original_image.read_bytes()
        updated_body = (
            '<h2>수정된 브리핑</h2><table><tr><td>수정</td></tr></table>'
            '<math><msup><mi>x</mi><mn>3</mn></msup></math>'
            f'<img src="/contents/{content_id}/images/image-1.png" width="640" height="360">'
            '<script>alert("removed")</script>'
            f'<img src="data:image/png;base64,{encoded}" alt="추가 그림">'
        )
        update = self.client.post(
            f"/admin/contents/{content_id}/edit",
            data={
                "csrf_token": "test-csrf",
                "title": "수정된 서식 붙여넣기",
                "content_type": CONTENT_TYPE_PE_QA,
                "body_format": "rich_html",
                "body": updated_body,
                "authored_at": "2026-10-31",
                "status": "published",
            },
        )
        self.assertEqual(302, update.status_code)
        self.assertEqual(original_image_bytes, original_image.read_bytes())
        self.assertEqual(
            PNG_DATA,
            (original_image.parent / "image-2.png").read_bytes(),
        )
        with self.app.app_context():
            updated = get_db_session().get(Content, content_id)
            unpacked = unpack_sanitized_html(updated.body, self.app.config["SECRET_KEY"])
            self.assertIn("수정된 브리핑", unpacked)
            self.assertIn("<msup><mi>x</mi><mn>3</mn></msup>", unpacked)
            self.assertIn('width="640" height="360"', unpacked)
            self.assertIn(f"/contents/{content_id}/images/image-1.png", unpacked)
            self.assertIn(f"/contents/{content_id}/images/image-2.png", unpacked)
            self.assertNotIn("script", unpacked)
        refreshed = self.client.get(f"/contents/{content_id}")
        self.assertIn("수정된 브리핑".encode(), refreshed.data)
        self.assertIn(b"image-1.png", refreshed.data)
        self.assertIn(b"image-2.png", refreshed.data)

    def test_rich_post_preserves_twenty_two_answer_lines_after_reload(self):
        answer_lines = [f"{index:02d} 기술사 답안 항목" for index in range(1, 23)]
        rich_body = (
            "<h2>기술사 모범답안</h2><p>"
            + "\n".join(answer_lines)
            + "</p><table><tr><th>구분</th><td>내용</td></tr></table>"
            + "<math><msqrt><mi>x</mi></msqrt></math>"
        )
        response = self.client.post(
            "/admin/content/new",
            data={
                "csrf_token": "test-csrf",
                "title": "22줄 답안",
                "content_type": CONTENT_TYPE_PE_QA,
                "body_format": "rich_html",
                "body": rich_body,
                "authored_at": "2026-10-31",
                "status": "published",
            },
        )
        self.assertEqual(302, response.status_code)
        with self.app.app_context():
            content = get_db_session().scalar(select(Content))
            unpacked = unpack_sanitized_html(content.body, self.app.config["SECRET_KEY"])
            self.assertEqual(21, unpacked.count("\n"))
            for line in answer_lines:
                self.assertIn(line, unpacked)
            content_id = content.id
        detail = self.client.get(f"/contents/{content_id}")
        self.assertIn("\n".join(answer_lines).encode(), detail.data)
        for line in answer_lines:
            self.assertIn(line.encode(), detail.data)
        self.assertIn(b"<table>", detail.data)
        self.assertIn(b"<msqrt>", detail.data)

    def test_html_edit_rejects_invalid_signature_without_changing_data(self):
        forged = f'{HTML_BODY_PREFIX}{"0" * 64} --><p>forged</p>'
        with self.app.app_context():
            content = Content(
                title="서명 오류",
                content_type=CONTENT_TYPE_PE_QA,
                body=forged,
                authored_at=__import__("datetime").date(2026, 10, 31),
                is_published=True,
            )
            get_db_session().add(content)
            get_db_session().commit()
            content_id = content.id
        self.assertEqual(409, self.client.get(f"/admin/contents/{content_id}/edit").status_code)
        post = self.client.post(
            f"/admin/contents/{content_id}/edit",
            data={
                "csrf_token": "test-csrf",
                "title": "덮어쓰기 시도",
                "content_type": CONTENT_TYPE_PE_QA,
                "body_format": "rich_html",
                "body": "<p>replacement</p>",
                "authored_at": "2026-10-31",
                "status": "published",
            },
        )
        self.assertEqual(409, post.status_code)
        with self.app.app_context():
            unchanged = get_db_session().get(Content, content_id)
            self.assertEqual("서명 오류", unchanged.title)
            self.assertEqual(forged, unchanged.body)

    def test_admin_form_exposes_rich_paste_and_individual_image_controls(self):
        response = self.client.get("/admin/content/new")
        self.assertEqual(200, response.status_code)
        self.assertIn(b'value="rich_html"', response.data)
        self.assertIn(b'contenteditable="true"', response.data)
        self.assertIn(b'tabindex="0"', response.data)
        self.assertIn(b'inputmode="text"', response.data)
        self.assertIn(b'content_editor.js?v=20261031-3', response.data)
        self.assertIn(b'id="editor_image"', response.data)
        self.assertIn(b'id="html_file"', response.data)
        script_path = Path(__file__).parents[1] / "static" / "js" / "content_editor.js"
        script = script_path.read_text(encoding="utf-8")
        self.assertIn('addEventListener("paste"', script)
        self.assertIn("readAsDataURL", script)
        self.assertIn("editor.innerHTML", script)
        self.assertIn("looksLikeMarkdown", script)
        self.assertIn("markdownToHtml", script)
        self.assertIn("plainTextToHtml", script)
        self.assertIn('lines.join("<br>")', script)
        self.assertIn("recoverReferencedImages", script)
        self.assertIn('credentials: "omit"', script)
        self.assertIn("markMissingImage", script)
        self.assertIn("await pendingPaste", script)
        self.assertIn("fillTitleFromPastedContent", script)
        self.assertIn('addEventListener("touchstart", focusRichEditor', script)
        self.assertIn("{ passive: true }", script)
        self.assertNotIn('touchstart", (event) => {\n    event.preventDefault()', script)
        css_path = Path(__file__).parents[1] / "static" / "css" / "style.css"
        css = css_path.read_text(encoding="utf-8")
        self.assertIn('[hidden] { display: none !important; }', css)
        self.assertIn('-webkit-user-select: text', css)
        self.assertIn('touch-action: manipulation', css)
        self.assertIn('.content-body.imported-html { white-space: pre-wrap; }', css)

    def test_forged_html_marker_is_rejected_and_never_rendered(self):
        forged = f'{HTML_BODY_PREFIX}{"0" * 64} --><script>alert("forged")</script>'
        response = self.client.post(
            "/admin/content/new",
            data={
                "csrf_token": "test-csrf",
                "title": "위조",
                "content_type": CONTENT_TYPE_PE_QA,
                "body": forged,
                "authored_at": "2026-10-31",
                "status": "published",
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertIn("예약된 HTML 형식 표식".encode(), response.data)
        with self.app.app_context():
            self.assertIsNone(get_db_session().scalar(select(Content)))

            direct_forgery = Content(
                title="직접 위조",
                content_type=CONTENT_TYPE_PE_QA,
                body=forged,
                authored_at=__import__("datetime").date(2026, 10, 31),
                is_published=True,
            )
            get_db_session().add(direct_forgery)
            get_db_session().commit()
            content_id = direct_forgery.id
        detail = self.client.get(f"/contents/{content_id}")
        self.assertNotIn(b'<script>alert("forged")</script>', detail.data)
        self.assertIn(b"&lt;script&gt;", detail.data)

    def test_existing_plain_text_remains_escaped(self):
        with self.app.app_context():
            db_session = get_db_session()
            content = Content(
                title="기존 글",
                content_type=CONTENT_TYPE_PE_QA,
                body='<script>alert("unsafe")</script> 일반 본문',
                authored_at=__import__("datetime").date(2026, 10, 31),
                is_published=True,
            )
            db_session.add(content)
            db_session.commit()
            content_id = content.id
        response = self.client.get(f"/contents/{content_id}")
        self.assertNotIn(b'<script>alert("unsafe")</script>', response.data)
        self.assertIn(b"&lt;script&gt;", response.data)

    def test_news_page_and_existing_news_model_remain_operational(self):
        with self.app.app_context():
            db_session = get_db_session()
            db_session.add(
                NewsArticle(
                    title="기존 뉴스",
                    original_url="https://example.test/news",
                    source_name="테스트",
                    category="기타",
                )
            )
            db_session.commit()
        response = self.client.get("/news")
        self.assertEqual(200, response.status_code)
        self.assertIn("기존 뉴스".encode(), response.data)


if __name__ == "__main__":
    unittest.main()
