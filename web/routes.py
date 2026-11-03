from datetime import date
from pathlib import Path
import re
import secrets

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, send_from_directory, session, url_for
from markupsafe import Markup
from sqlalchemy import or_, select
from werkzeug.security import check_password_hash
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ictlab.categories import CATEGORY_INTERNATIONAL, CATEGORY_OPTIONS
from ictlab.db import get_db_session
from ictlab.models import (
    CONTENT_TYPE_LABELS,
    CONTENT_TYPE_NEWS_BRIEFING,
    CONTENT_TYPE_PE_QA,
    Content,
    NewsArticle,
    PeSummary,
    PeSummaryAsset,
)
from ictlab.pe_summary_files import UploadError, make_pdf_preview, save_upload
from ictlab.web.auth import admin_login_required, csrf_token, safe_next_url, validate_csrf
from ictlab.html_import import (
    HTML_BODY_PREFIX,
    IMAGE_PLACEHOLDER_PREFIX,
    HtmlImportError,
    pack_sanitized_html,
    sanitize_html_document,
    unpack_sanitized_html,
)


web = Blueprint("web", __name__)


@web.get("/")
def home():
    return redirect("/news")


@web.get("/health")
def health():
    return jsonify(service="ICT Lab", status="ok"), 200


@web.get("/news")
def news():
    session = get_db_session()
    selected_category = request.args.get("category")
    show_all_briefings = request.args.get("briefings") == "all"
    if selected_category and selected_category not in CATEGORY_OPTIONS:
        abort(400)
    recent_first = (
        NewsArticle.published_at.desc().nulls_last(),
        NewsArticle.collected_at.desc(),
    )
    if selected_category:
        filtered_articles = session.scalars(
            select(NewsArticle)
            .where(NewsArticle.category == selected_category)
            .order_by(*recent_first)
            .limit(100)
        ).all()
        domestic_articles = []
        international_articles = []
    else:
        filtered_articles = []
        domestic_articles = session.scalars(
            select(NewsArticle)
            .where(
                or_(
                    NewsArticle.category != CATEGORY_INTERNATIONAL,
                    NewsArticle.category.is_(None),
                )
            )
            .order_by(*recent_first)
            .limit(50)
        ).all()
        international_articles = session.scalars(
            select(NewsArticle)
            .where(NewsArticle.category == CATEGORY_INTERNATIONAL)
            .order_by(*recent_first)
            .limit(50)
        ).all()
    briefings_query = (
        select(Content)
        .where(
            Content.content_type == CONTENT_TYPE_NEWS_BRIEFING,
            Content.is_published.is_(True),
        )
        .order_by(Content.authored_at.desc(), Content.id.desc())
    )
    if not show_all_briefings:
        # Fetch one extra row so the page can decide whether to show "more"
        # without loading every briefing on the initial news page.
        briefings_query = briefings_query.limit(6)
    queried_briefings = session.scalars(briefings_query).all()
    has_more_briefings = not show_all_briefings and len(queried_briefings) > 5
    briefings = queried_briefings if show_all_briefings else queried_briefings[:5]
    return render_template(
        "news.html",
        category_options=CATEGORY_OPTIONS,
        selected_category=selected_category,
        filtered_articles=filtered_articles,
        domestic_articles=domestic_articles,
        international_articles=international_articles,
        briefings=briefings,
        has_more_briefings=has_more_briefings,
    )


@web.get("/professional-engineer")
def professional_engineer():
    contents = get_db_session().scalars(
        select(Content)
        .where(
            Content.content_type == CONTENT_TYPE_PE_QA,
            Content.is_published.is_(True),
        )
        .order_by(Content.authored_at.desc(), Content.id.desc())
    ).all()
    return render_template("professional_engineer.html", contents=contents)


@web.get("/pe-summaries")
def pe_summaries():
    query_text = request.args.get("q", "").strip()[:100]
    selected_field = request.args.get("field", "").strip()[:100]
    statement = select(PeSummary).where(PeSummary.is_published.is_(True))
    if selected_field:
        statement = statement.where(PeSummary.field == selected_field)
    if query_text:
        pattern = f"%{query_text}%"
        statement = statement.where(or_(PeSummary.title.ilike(pattern), PeSummary.keywords.ilike(pattern)))
    db_session = get_db_session()
    summaries = db_session.scalars(statement.order_by(PeSummary.created_at.desc(), PeSummary.id.desc())).all()
    fields = db_session.scalars(select(PeSummary.field).where(PeSummary.is_published.is_(True)).distinct().order_by(PeSummary.field)).all()
    return render_template("pe_summary_list.html", summaries=summaries, fields=fields, query_text=query_text, selected_field=selected_field)


def _visible_summary(summary_id: int) -> PeSummary:
    summary = get_db_session().get(PeSummary, summary_id)
    if summary is None or (not summary.is_published and not session.get("is_admin")):
        abort(404)
    return summary


@web.get("/pe-summaries/<int:summary_id>")
def pe_summary_detail(summary_id: int):
    summary = _visible_summary(summary_id)
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="pe-summary-preview")
    preview_tokens = {
        asset.id: serializer.dumps({"summary": summary.id, "asset": asset.id, "sha256": asset.sha256})
        for asset in summary.assets
        if asset.kind == "document" and asset.preview_name
    }
    return render_template("pe_summary_detail.html", summary=summary, preview_tokens=preview_tokens)


@web.get("/pe-summaries/<int:summary_id>/assets/<int:asset_id>/<mode>")
def pe_summary_asset(summary_id: int, asset_id: int, mode: str):
    summary = _visible_summary(summary_id)
    asset = get_db_session().get(PeSummaryAsset, asset_id)
    if asset is None or asset.summary_id != summary.id or mode not in {"view", "download", "preview", "original"}:
        abort(404)
    root = Path(current_app.config["PE_SUMMARY_UPLOAD_ROOT"]) / str(summary.id)
    if mode == "preview":
        token = request.headers.get("X-ICTLab-Preview", "")
        serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="pe-summary-preview")
        try:
            claims = serializer.loads(token, max_age=3600)
        except (BadSignature, SignatureExpired):
            abort(403)
        if claims != {"summary": summary.id, "asset": asset.id, "sha256": asset.sha256}:
            abort(403)
        if not asset.preview_name or (asset.conversion_status == "converted_unverified" and not asset.preview_verified and not session.get("is_admin")):
            abort(404)
        # Never expose an original document through the public preview route.
        if asset.preview_name == asset.stored_name:
            abort(404)
        path, mimetype, download_name, as_attachment = root / asset.preview_name, "application/pdf", "ict-lab-reading-copy.pdf", False
    else:
        if (asset.kind == "document" or mode == "download") and not session.get("is_admin"):
            abort(403)
        if asset.kind != "document" and mode == "original":
            abort(404)
        path, mimetype, download_name = root / asset.stored_name, asset.mime_type, asset.original_name
        as_attachment = mode == "download" or (mode == "view" and asset.kind == "document" and asset.mime_type != "application/pdf")
    if not path.is_file():
        abort(404)
    response = send_file(path, mimetype=mimetype, as_attachment=as_attachment, download_name=download_name, conditional=True, etag=True, max_age=3600)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; media-src 'self'; img-src 'self'; style-src 'unsafe-inline'"
    if asset.kind == "image" or mode == "download" or (asset.kind == "document" and mode != "preview"):
        response.headers["Cache-Control"] = "private, no-store"
    elif mode == "preview":
        response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@web.route("/admin/pe-summaries/new", methods=["GET", "POST"])
@admin_login_required
def admin_pe_summary_new():
    return _admin_pe_summary_form(None)


@web.route("/admin/pe-summaries/<int:summary_id>/edit", methods=["GET", "POST"])
@admin_login_required
def admin_pe_summary_edit(summary_id: int):
    summary = get_db_session().get(PeSummary, summary_id)
    if summary is None:
        abort(404)
    return _admin_pe_summary_form(summary)


def _admin_pe_summary_form(summary: PeSummary | None):
    errors = []
    existing_media = [asset for asset in summary.assets if asset.kind in {"audio", "video"}] if summary else []
    existing_lyrics = {asset.id: asset.lyrics or "" for asset in existing_media}
    values = {"title": summary.title if summary else "", "field": summary.field if summary else "", "keywords": summary.keywords if summary else "", "description": summary.description if summary else "", "status": "published" if summary and summary.is_published else "private", "lyrics": ""}
    if request.method == "POST":
        validate_csrf()
        values = {name: request.form.get(name, "") if name == "lyrics" else request.form.get(name, "").strip() for name in values}
        existing_lyrics = {asset.id: request.form.get(f"existing_lyrics_{asset.id}", "") for asset in existing_media}
        if not values["title"] or len(values["title"]) > 500:
            errors.append("제목을 500자 이내로 입력해주세요.")
        if not values["field"] or len(values["field"]) > 100:
            errors.append("출제 분야를 100자 이내로 입력해주세요.")
        if len(values["keywords"]) > 1000:
            errors.append("키워드는 1,000자 이내로 입력해주세요.")
        if values["status"] not in {"published", "private"}:
            errors.append("올바른 공개 상태를 선택해주세요.")
        uploads = [item for item in request.files.getlist("files") if item.filename]
        if len(uploads) > current_app.config.get("PE_SUMMARY_MAX_FILES", 20):
            errors.append("한 번에 업로드할 수 있는 파일 수를 초과했습니다.")
        if not errors:
            db_session = get_db_session()
            if summary is None:
                summary = PeSummary()
                db_session.add(summary)
            summary.title, summary.field, summary.keywords, summary.description = values["title"], values["field"], values["keywords"], values["description"]
            summary.is_published = values["status"] == "published"
            for asset in existing_media:
                asset.lyrics = existing_lyrics[asset.id] or None
            saved_paths = []
            removed_paths = []
            try:
                db_session.flush()
                directory = Path(current_app.config["PE_SUMMARY_UPLOAD_ROOT"]) / str(summary.id)
                for upload in uploads:
                    info = save_upload(upload, directory, current_app.config.get("PE_SUMMARY_MAX_FILE_BYTES", 100 * 1024 * 1024))
                    saved_paths.append(info["path"])
                    preview_name, conversion_status = make_pdf_preview(info["path"], directory, current_app.config.get("PE_SUMMARY_CONVERSION_TIMEOUT", 120)) if info["kind"] == "document" else (None, "not_applicable")
                    if preview_name:
                        saved_paths.append(directory / preview_name)
                    asset = PeSummaryAsset(summary_id=summary.id, kind=info["kind"], original_name=info["original_name"], stored_name=info["stored_name"], mime_type=info["mime_type"], size_bytes=info["size_bytes"], sha256=info["sha256"], preview_name=preview_name, conversion_status=conversion_status, lyrics=values["lyrics"] or None if info["kind"] in {"audio", "video"} else None)
                    db_session.add(asset)
                for raw_id in request.form.getlist("delete_asset"):
                    if raw_id.isdigit():
                        asset = next((a for a in summary.assets if a.id == int(raw_id)), None)
                        if asset:
                            for filename in {asset.stored_name, asset.preview_name} - {None}:
                                removed_paths.append(directory / filename)
                            db_session.delete(asset)
                verified_ids = {int(value) for value in request.form.getlist("verify_asset") if value.isdigit()}
                for asset in summary.assets:
                    if asset.conversion_status == "converted_unverified":
                        asset.preview_verified = asset.id in verified_ids
                db_session.commit()
                for path in removed_paths:
                    path.unlink(missing_ok=True)
            except UploadError as exc:
                db_session.rollback()
                for path in saved_paths:
                    path.unlink(missing_ok=True)
                errors.append(str(exc))
            except Exception:
                db_session.rollback()
                for path in saved_paths:
                    path.unlink(missing_ok=True)
                raise
            if not errors:
                flash("기술사 서머리를 저장했습니다.", "success")
                return redirect(url_for("web.pe_summary_detail", summary_id=summary.id))
    return render_template("admin_pe_summary_form.html", summary=summary, values=values, existing_lyrics=existing_lyrics, errors=errors, csrf_token=csrf_token())


@web.post("/admin/pe-summaries/<int:summary_id>/delete")
@admin_login_required
def admin_pe_summary_delete(summary_id: int):
    validate_csrf()
    db_session = get_db_session()
    summary = db_session.get(PeSummary, summary_id)
    if summary is None:
        abort(404)
    directory = Path(current_app.config["PE_SUMMARY_UPLOAD_ROOT"]) / str(summary.id)
    db_session.delete(summary)
    db_session.commit()
    if directory.is_dir():
        import shutil
        shutil.rmtree(directory)
    flash("기술사 서머리를 삭제했습니다.", "success")
    return redirect(url_for("web.pe_summaries"))


@web.get("/contents/<int:content_id>")
def content_detail(content_id: int):
    content = get_db_session().scalar(
        select(Content).where(
            Content.id == content_id,
            Content.is_published.is_(True),
        )
    )
    if content is None:
        abort(404)
    imported_body = unpack_sanitized_html(content.body, current_app.config["SECRET_KEY"])
    is_imported_html = imported_body is not None
    rendered_body = Markup(imported_body) if is_imported_html else content.body
    return render_template(
        "content_detail.html",
        content=content,
        content_type_label=CONTENT_TYPE_LABELS[content.content_type],
        is_imported_html=is_imported_html,
        rendered_body=rendered_body,
    )


@web.get("/contents/<int:content_id>/images/<path:filename>")
def content_image(content_id: int, filename: str):
    content = get_db_session().get(Content, content_id)
    if content is None or (not content.is_published and not session.get("is_admin")):
        abort(404)
    directory = Path(current_app.config["CONTENT_UPLOAD_ROOT"]) / str(content_id)
    return send_from_directory(directory, filename, max_age=31536000)


@web.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(safe_next_url(request.values.get("next")))

    error = None
    next_url = safe_next_url(request.values.get("next"))
    if request.method == "POST":
        validate_csrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        configured_username = current_app.config.get("ADMIN_USERNAME")
        password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
        valid = bool(
            configured_username
            and password_hash
            and secrets.compare_digest(username, configured_username)
            and check_password_hash(password_hash, password)
        )
        if valid:
            session.clear()
            session["is_admin"] = True
            csrf_token()
            return redirect(next_url)
        error = "관리자 계정 또는 비밀번호가 올바르지 않습니다."

    return render_template(
        "admin_login.html",
        csrf_token=csrf_token(),
        error=error,
        next_url=next_url,
    ), 401 if error else 200


@web.post("/admin/logout")
@admin_login_required
def admin_logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("web.admin_login"))


@web.get("/admin/contents")
@admin_login_required
def admin_contents():
    contents = get_db_session().scalars(
        select(Content).order_by(Content.authored_at.desc(), Content.id.desc())
    ).all()
    return render_template(
        "admin_content_list.html",
        contents=contents,
        content_type_labels=CONTENT_TYPE_LABELS,
        csrf_token=csrf_token(),
    )


@web.route("/admin/content/new", methods=["GET", "POST"])
@admin_login_required
def admin_content_new():
    form_values = _content_form_values()
    errors, authored_at = _validate_content_form(form_values)
    if request.method == "POST":
        validate_csrf()
        imported_document = None
        uploaded_html = request.files.get("html_file")
        if uploaded_html and uploaded_html.filename:
            if not uploaded_html.filename.lower().endswith((".html", ".htm")):
                errors.append(".html 또는 .htm 파일만 가져올 수 있습니다.")
            else:
                try:
                    imported_document = sanitize_html_document(
                        uploaded_html.stream.read(current_app.config["MAX_HTML_IMPORT_BYTES"] + 1),
                        max_bytes=current_app.config["MAX_HTML_IMPORT_BYTES"],
                        max_image_bytes=current_app.config["MAX_HTML_IMAGE_BYTES"],
                        max_images=current_app.config["MAX_HTML_IMAGES"],
                    )
                except HtmlImportError as exc:
                    errors.append(str(exc))
                else:
                    form_values["body"] = imported_document.html
                    errors = [error for error in errors if error != "본문을 입력해주세요."]
        elif form_values["body_format"] == "rich_html" and form_values["body"]:
            try:
                imported_document = sanitize_html_document(
                    str(form_values["body"]).encode("utf-8"),
                    max_bytes=current_app.config["MAX_HTML_IMPORT_BYTES"],
                    max_image_bytes=current_app.config["MAX_HTML_IMAGE_BYTES"],
                    max_images=current_app.config["MAX_HTML_IMAGES"],
                )
            except HtmlImportError as exc:
                errors.append(str(exc))
            else:
                form_values["body"] = imported_document.html
        if not errors:
            session = get_db_session()
            content = Content(
                title=form_values["title"],
                content_type=form_values["content_type"],
                body=form_values["body"],
                authored_at=authored_at,
                is_published=form_values["status"] == "published",
            )
            session.add(content)
            image_directory = None
            try:
                session.flush()
                if imported_document:
                    image_directory = Path(current_app.config["CONTENT_UPLOAD_ROOT"]) / str(content.id)
                    image_directory.mkdir(parents=True, exist_ok=False)
                    image_directory.chmod(0o700)
                    body = imported_document.html
                    for index, image in enumerate(imported_document.images):
                        destination = image_directory / image.filename
                        destination.write_bytes(image.data)
                        destination.chmod(0o600)
                        image_url = url_for("web.content_image", content_id=content.id, filename=image.filename)
                        body = body.replace(f"{IMAGE_PLACEHOLDER_PREFIX}{index}__", image_url)
                    content.body = pack_sanitized_html(body, current_app.config["SECRET_KEY"])
                session.commit()
            except Exception:
                session.rollback()
                if image_directory and image_directory.exists():
                    for path in image_directory.iterdir():
                        path.unlink()
                    image_directory.rmdir()
                raise
            flash("콘텐츠가 저장되었습니다.", "success")
            return redirect(url_for("web.admin_contents"))

    return render_template(
        "admin_content_form.html",
        page_title="콘텐츠 등록",
        submit_label="PostgreSQL에 저장",
        content_type_labels=CONTENT_TYPE_LABELS,
        csrf_token=csrf_token(),
        errors=errors,
        form_values=form_values,
    )


@web.route("/admin/contents/<int:content_id>/edit", methods=["GET", "POST"])
@admin_login_required
def admin_content_edit(content_id: int):
    session = get_db_session()
    content = session.get(Content, content_id)
    if content is None:
        abort(404)

    imported_body = unpack_sanitized_html(content.body, current_app.config["SECRET_KEY"])
    if content.body.startswith(HTML_BODY_PREFIX) and imported_body is None:
        if request.method == "POST":
            validate_csrf()
        abort(409, description="HTML 본문의 서명을 확인할 수 없어 안전하게 수정을 중단했습니다.")

    form_values = _content_form_values(content)
    errors, authored_at = _validate_content_form(form_values)
    if request.method == "POST":
        validate_csrf()
        imported_document = None
        if imported_body is not None and form_values["body"]:
            image_directory = Path(current_app.config["CONTENT_UPLOAD_ROOT"]) / str(content.id)
            allowed_sources = frozenset(
                url_for("web.content_image", content_id=content.id, filename=path.name)
                for path in image_directory.iterdir()
                if path.is_file()
            ) if image_directory.is_dir() else frozenset()
            existing_numbers = [
                int(match.group(1))
                for path in image_directory.iterdir()
                if path.is_file() and (match := re.fullmatch(r"image-(\d+)\.(?:png|jpg|gif|webp)", path.name))
            ] if image_directory.is_dir() else []
            try:
                imported_document = sanitize_html_document(
                    str(form_values["body"]).encode("utf-8"),
                    max_bytes=current_app.config["MAX_HTML_IMPORT_BYTES"],
                    max_image_bytes=current_app.config["MAX_HTML_IMAGE_BYTES"],
                    max_images=current_app.config["MAX_HTML_IMAGES"],
                    allowed_image_sources=allowed_sources,
                    image_filename_start=max(existing_numbers, default=0) + 1,
                )
            except HtmlImportError as exc:
                errors.append(str(exc))
        if not errors:
            content.title = form_values["title"]
            content.content_type = form_values["content_type"]
            content.authored_at = authored_at
            content.is_published = form_values["status"] == "published"
            new_images = []
            try:
                if imported_document:
                    image_directory.mkdir(parents=True, exist_ok=True)
                    image_directory.chmod(0o700)
                    body = imported_document.html
                    for index, image in enumerate(imported_document.images):
                        destination = image_directory / image.filename
                        with destination.open("xb") as output:
                            output.write(image.data)
                        destination.chmod(0o600)
                        new_images.append(destination)
                        image_url = url_for("web.content_image", content_id=content.id, filename=image.filename)
                        body = body.replace(f"{IMAGE_PLACEHOLDER_PREFIX}{index}__", image_url)
                    content.body = pack_sanitized_html(body, current_app.config["SECRET_KEY"])
                else:
                    content.body = form_values["body"]
                session.commit()
            except Exception:
                session.rollback()
                for path in new_images:
                    path.unlink(missing_ok=True)
                raise
            flash("콘텐츠를 수정했습니다.", "success")
            return redirect(url_for("web.admin_contents"))

    return render_template(
        "admin_content_form.html",
        page_title="콘텐츠 수정",
        submit_label="수정 내용 저장",
        content_type_labels=CONTENT_TYPE_LABELS,
        csrf_token=csrf_token(),
        errors=errors,
        form_values=form_values,
    )


@web.post("/admin/contents/<int:content_id>/delete")
@admin_login_required
def admin_content_delete(content_id: int):
    validate_csrf()
    session = get_db_session()
    content = session.get(Content, content_id)
    if content is None:
        abort(404)
    session.delete(content)
    session.commit()
    flash("콘텐츠를 삭제했습니다.", "success")
    return redirect(url_for("web.admin_contents"))


def _content_form_values(content: Content | None = None) -> dict[str, str | bool]:
    imported_body = (
        unpack_sanitized_html(content.body, current_app.config["SECRET_KEY"])
        if content else None
    )
    is_imported_html = imported_body is not None
    if request.method == "POST":
        return {
            "title": request.form.get("title", "").strip(),
            "content_type": request.form.get("content_type", ""),
            "body": request.form.get("body", "").strip(),
            "authored_at": request.form.get("authored_at", ""),
            "status": request.form.get("status", ""),
            "body_format": "rich_html" if is_imported_html else request.form.get("body_format", "plain_text"),
            "is_imported_html": is_imported_html,
        }
    if content is not None:
        return {
            "title": content.title,
            "content_type": content.content_type,
            "body": imported_body if is_imported_html else content.body,
            "authored_at": content.authored_at.isoformat(),
            "status": "published" if content.is_published else "private",
            "body_format": "rich_html" if is_imported_html else "plain_text",
            "is_imported_html": is_imported_html,
        }
    return {
        "title": "",
        "content_type": CONTENT_TYPE_NEWS_BRIEFING,
        "body": "",
        "authored_at": date.today().isoformat(),
        "status": "private",
        "body_format": "rich_html",
        "is_imported_html": False,
    }


def _validate_content_form(form_values: dict[str, str | bool]) -> tuple[list[str], date]:
    errors = []
    if request.method != "POST":
        return errors, date.today()
    if not form_values["title"]:
        errors.append("제목을 입력해주세요.")
    if form_values["content_type"] not in CONTENT_TYPE_LABELS:
        errors.append("올바른 콘텐츠 유형을 선택해주세요.")
    if form_values["body_format"] not in {"plain_text", "rich_html"}:
        errors.append("올바른 본문 형식을 선택해주세요.")
    if not form_values["body"]:
        errors.append("본문을 입력해주세요.")
    if (
        isinstance(form_values["body"], str)
        and form_values["body"].startswith(HTML_BODY_PREFIX)
        and not form_values.get("is_imported_html")
    ):
        errors.append("예약된 HTML 형식 표식은 일반 본문에 사용할 수 없습니다.")
    try:
        authored_at = date.fromisoformat(form_values["authored_at"])
    except ValueError:
        authored_at = date.today()
        errors.append("올바른 작성일을 입력해주세요.")
    if form_values["status"] not in {"published", "private"}:
        errors.append("올바른 공개 상태를 선택해주세요.")
    return errors, authored_at
