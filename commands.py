import click
from flask import Flask

from ictlab.categories import CATEGORY_OPTIONS, classify_existing_articles
from ictlab.collectors import collect_rss
from ictlab.db import get_db_session


def register_commands(app: Flask) -> None:
    @app.cli.command("collect-news")
    def collect_news_command() -> None:
        """Collect the configured RSS feeds into the news database."""
        result = collect_rss(get_db_session())
        click.echo(
            f"Collected {result.inserted} new article(s); "
            f"skipped {result.duplicates} duplicate(s)."
        )

    @app.cli.command("classify-news")
    def classify_news_command() -> None:
        """Apply the current category rules to all stored news articles."""
        updated, counts = classify_existing_articles(get_db_session())
        click.echo(f"Updated {updated} article(s).")
        for category in CATEGORY_OPTIONS:
            click.echo(f"{category}: {counts[category]}")
