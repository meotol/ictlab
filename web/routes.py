from flask import Blueprint, abort, jsonify, render_template, request
from sqlalchemy import or_, select

from ictlab.categories import CATEGORY_INTERNATIONAL, CATEGORY_OPTIONS
from ictlab.db import get_db_session
from ictlab.models import NewsArticle


web = Blueprint("web", __name__)


@web.get("/")
def home():
    return render_template("home.html")


@web.get("/health")
def health():
    return jsonify(service="ICT Lab", status="ok"), 200


@web.get("/news")
def news():
    session = get_db_session()
    selected_category = request.args.get("category")
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
    return render_template(
        "news.html",
        category_options=CATEGORY_OPTIONS,
        selected_category=selected_category,
        filtered_articles=filtered_articles,
        domestic_articles=domestic_articles,
        international_articles=international_articles,
    )
