"""X/Twitter fetcher via logged-in session cookies (data-sources.md §4.1). Self-disables unless
TWITTER_ENABLED and cookies are present. Uses twikit (lazy import) to query cashtag search — NO
detection-evasion (one account, polite volume, back off on challenge). The owner installs twikit
(`uv pip install twikit`) and supplies cookies to light up the live path; until then fetch()=[]"."""
from datetime import datetime, timezone

from app.intel.models import RawIntel

_PER_RUN = 30   # cashtags per cycle (polite budget)


class TwitterFetcher:
    name = "twitter"

    def __init__(self, auth_token: str = "", ct0: str = "", cookies_file: str = "",
                 enabled_flag: bool = True):
        self.auth_token = auth_token
        self.ct0 = ct0
        self.cookies_file = cookies_file
        self._enabled_flag = enabled_flag

    @property
    def enabled(self) -> bool:
        return bool(self._enabled_flag and ((self.auth_token and self.ct0) or self.cookies_file))

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        if not self.enabled:
            return []
        try:
            return await self._fetch(symbols)
        except Exception:  # noqa: BLE001 - back off / accept the gap, never raise
            return []

    async def _fetch(self, symbols: list[str]) -> list[RawIntel]:
        try:
            from twikit import Client  # lazy + optional; absent -> graceful no-op
        except ImportError:
            return []
        client = Client("en-US")
        client.set_cookies({"auth_token": self.auth_token, "ct0": self.ct0})
        out: list[RawIntel] = []
        for sym in symbols[:_PER_RUN]:
            tweets = await client.search_tweet(f"${sym}", "Latest")
            for t in tweets:
                out.append(_tweet_to_intel(t))
        return out


def _tweet_to_intel(t) -> RawIntel:
    user = getattr(t, "user", None)
    handle = f"@{getattr(user, 'screen_name', 'unknown')}" if user else "@unknown"
    created = getattr(t, "created_at_datetime", None) or datetime.now(timezone.utc)
    return RawIntel(
        source="twitter", author_handle=handle,
        url=f"https://x.com/i/web/status/{getattr(t, 'id', '')}",
        text=getattr(t, "text", "") or "", posted_at=created,
        engagement=getattr(user, "followers_count", None) if user else None)
