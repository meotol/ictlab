from datetime import date
import secrets

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_, select
from werkzeug.security import check_password_hash

from ictlab.categories import CATEGORY_INTERNATIONAL, CATEGORY_OPTIONS
from ictlab.db import get_db_session
from ictlab.models import (
    CONTENT_TYPE_LABELS,
    CONTENT_TYPE_NEWS_BRIEFING,
    CONTENT_TYPE_PE_QA,
    Content,
    NewsArticle,
)
from ictlab.web.auth import admin_login_required, csrf_token, safe_next_url, validate_csrf


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
    return render_template(
        "content_detail.html",
        content=content,
        content_type_label=CONTENT_TYPE_LABELS[content.content_type],
    )


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
            session.commit()
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

    form_values = _content_form_values(content)
    errors, authored_at = _validate_content_form(form_values)
    if request.method == "POST":
        validate_csrf()
        if not errors:
            content.title = form_values["title"]
            content.content_type = form_values["content_type"]
            content.body = form_values["body"]
            content.authored_at = authored_at
            content.is_published = form_values["status"] == "published"
            session.commit()
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


def _content_form_values(content: Content | None = None) -> dict[str, str]:
    if request.method == "POST":
        return {
            "title": request.form.get("title", "").strip(),
            "content_type": request.form.get("content_type", ""),
            "body": request.form.get("body", "").strip(),
            "authored_at": request.form.get("authored_at", ""),
            "status": request.form.get("status", ""),
        }
    if content is not None:
        return {
            "title": content.title,
            "content_type": content.content_type,
            "body": content.body,
            "authored_at": content.authored_at.isoformat(),
            "status": "published" if content.is_published else "private",
        }
    return {
        "title": "",
        "content_type": CONTENT_TYPE_NEWS_BRIEFING,
        "body": "",
        "authored_at": date.today().isoformat(),
        "status": "private",
    }


def _validate_content_form(form_values: dict[str, str]) -> tuple[list[str], date]:
    errors = []
    if request.method != "POST":
        return errors, date.today()
    if not form_values["title"]:
        errors.append("제목을 입력해주세요.")
    if form_values["content_type"] not in CONTENT_TYPE_LABELS:
        errors.append("올바른 콘텐츠 유형을 선택해주세요.")
    if not form_values["body"]:
        errors.append("본문을 입력해주세요.")
    try:
        authored_at = date.fromisoformat(form_values["authored_at"])
    except ValueError:
        authored_at = date.today()
        errors.append("올바른 작성일을 입력해주세요.")
    if form_values["status"] not in {"published", "private"}:
        errors.append("올바른 공개 상태를 선택해주세요.")
    return errors, authored_at
