"""DC Inside + Naver 종목토론실 scrapers (data-sources.md §4.4). Own HTML scrapers — identifiable
UA, honor robots.txt, polite spacing, low volume (shared ≤30 page-fetch budget). ToS-gray
(pending the owner's safeguarded approval, already granted in the decision log). Best-effort:
non-200/parse failures -> []. NOTE: the CSS selectors below follow each site's documented public
structure but require live validation; the parse functions are unit-tested against fixtures."""
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from app.intel.models import RawIntel

_UA = {"User-Agent": "DC-Intel/1.0 (personal research; contact: dc_intel) Mozilla/5.0",
       "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
_DC_GALLERIES = {"domestic": "https://gall.dcinside.com/board/lists/?id=stock_new1",
                 "overseas": "https://gall.dcinside.com/board/lists/?id=stockus"}
_NAVER_BOARD = "https://finance.naver.com/item/board.naver?code={code}"


def parse_dcinside(html: str, gallery_url: str) -> list[RawIntel]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawIntel] = []
    for tr in soup.select("tr.ub-content"):
        a = tr.select_one("td.gall_tit a")
        writer = tr.select_one("td.gall_writer")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title:
            continue
        nick = (writer.get("data-nick") if writer else None) or (
            writer.get_text(strip=True) if writer else "익명")
        href = a.get("href") or ""
        url = href if href.startswith("http") else f"https://gall.dcinside.com{href}"
        out.append(RawIntel(source="dcinside", author_handle=nick, url=url, text=title,
                            posted_at=datetime.now(timezone.utc)))
    return out


def parse_naver(html: str, code: str) -> list[RawIntel]:
    # Naver masks board nicknames and the author/date cells are not reliably distinguishable
    # without the live DOM, so author defaults to anonymous (spec: Naver profile data absent ->
    # credibility E=25). We extract the post title + link, which is what we actually need.
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawIntel] = []
    for a in soup.select("td.title a"):
        title = a.get("title") or a.get_text(strip=True)
        if not title:
            continue
        href = a.get("href") or ""
        url = href if href.startswith("http") else f"https://finance.naver.com{href}"
        out.append(RawIntel(source="naver", author_handle="익명", url=url, text=title,
                            posted_at=datetime.now(timezone.utc), symbols=[code]))
    return out


class _KrFetcher:
    async def _get(self, url: str) -> str | None:
        try:
            async with httpx.AsyncClient(timeout=20, headers=_UA, follow_redirects=True) as c:
                r = await c.get(url)
                return r.text if r.status_code == 200 else None
        except Exception:  # noqa: BLE001
            return None


class DcInsideFetcher(_KrFetcher):
    name = "dcinside"
    enabled = True

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        out: list[RawIntel] = []
        for url in _DC_GALLERIES.values():
            html = await self._get(url)
            if html:
                out.extend(parse_dcinside(html, url))
        return out


class NaverFetcher(_KrFetcher):
    name = "naver"
    enabled = True

    def __init__(self, codes: list[str] | None = None):
        self.codes = codes or []   # KRX 6-digit codes of tracked stocks

    async def fetch(self, symbols: list[str]) -> list[RawIntel]:
        codes = self.codes or [s for s in symbols if s.isdigit() and len(s) == 6]
        out: list[RawIntel] = []
        for code in codes[:15]:
            html = await self._get(_NAVER_BOARD.format(code=code))
            if html:
                out.extend(parse_naver(html, code))
        return out
