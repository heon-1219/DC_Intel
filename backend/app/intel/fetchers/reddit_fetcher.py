"""Reddit fetcher via PRAW (data-sources.md §4.2). Self-disables without OAuth creds. PRAW is
synchronous, so fetching runs in a thread. parse_submission is pure (duck-typed) for testing."""
import asyncio
from datetime import datetime, timezone

from app.intel.config import INTEL_SUBREDDITS
from app.intel.entities import extract_cashtags
from app.intel.models import RawIntel


def parse_submission(post) -> RawIntel:
    """Map a PRAW submission (or any object with the same attributes) to RawIntel."""
    author = getattr(post, "author", None)
    handle = f"u/{author}" if author else "u/[deleted]"
    title = getattr(post, "title", "") or ""
    body = getattr(post, "selftext", "") or ""
    text = f"{title}\n{body}".strip()
    permalink = getattr(post, "permalink", "")
    return RawIntel(
        source="reddit", author_handle=handle,
        url=f"https://reddit.com{permalink}" if permalink else None,
        text=text,
        posted_at=datetime.fromtimestamp(getattr(post, "created_utc", 0), tz=timezone.utc),
        symbols=extract_cashtags(text), engagement=getattr(post, "score", None))


class RedditFetcher:
    name = "reddit"

    def __init__(self, client_id: str = "", client_secret: str = "", user_agent: str = "",
                 subreddits: list[str] | None = None, limit: int = 25):
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.subreddits = subreddits or INTEL_SUBREDDITS
        self.limit = limit

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        if not self.enabled:
            return []
        try:
            return await asyncio.to_thread(self._fetch)
        except Exception:  # noqa: BLE001 - never abort the run
            return []

    def _fetch(self) -> list[RawIntel]:
        import praw  # lazy: keeps the offline suite import-light

        reddit = praw.Reddit(client_id=self.client_id, client_secret=self.client_secret,
                             user_agent=self.user_agent, check_for_async=False)
        out: list[RawIntel] = []
        for sub in self.subreddits:
            for post in reddit.subreddit(sub).new(limit=self.limit):
                out.append(parse_submission(post))
        return out
