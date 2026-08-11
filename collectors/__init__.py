"""External content collectors."""

from .rss import RSS_SOURCES, CollectionResult, FeedSource, collect_rss


__all__ = [
    "RSS_SOURCES",
    "CollectionResult",
    "FeedSource",
    "collect_rss",
]
