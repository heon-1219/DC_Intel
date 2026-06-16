from types import SimpleNamespace

from app.intel.fetchers.kr_communities import (DcInsideFetcher, NaverFetcher,
                                               parse_dcinside, parse_naver)
from app.intel.fetchers.reddit_fetcher import RedditFetcher, parse_submission
from app.intel.fetchers.stocktwits_fetcher import StockTwitsFetcher, parse_stocktwits
from app.intel.fetchers.twitter_fetcher import TwitterFetcher


def test_parse_stocktwits_maps_fields_and_weak_label():
    data = {"messages": [{
        "id": 7, "body": "$AAPL ripping 🚀", "created_at": "2026-06-16T05:00:00Z",
        "user": {"username": "trader1", "followers": 1200, "join_date": "2022-06-16T00:00:00Z"},
        "symbols": [{"symbol": "AAPL"}],
        "entities": {"sentiment": {"basic": "Bullish"}}}]}
    evs = parse_stocktwits(data)
    assert len(evs) == 1
    e = evs[0]
    assert e.source == "stocktwits" and e.author_handle == "trader1"
    assert e.weak_label == "bullish" and e.engagement == 1200 and e.symbols == ["AAPL"]
    assert e.account_age_days and e.account_age_days > 1000


def test_parse_submission_extracts_cashtags_and_score():
    post = SimpleNamespace(title="NVDA earnings beat", selftext="$NVDA to the moon",
                           author="someuser", permalink="/r/stocks/comments/x/",
                           created_utc=1781000000, score=42)
    ri = parse_submission(post)
    assert ri.source == "reddit" and ri.author_handle == "u/someuser"
    assert "NVDA" in ri.symbols and ri.engagement == 42
    assert ri.url == "https://reddit.com/r/stocks/comments/x/"


def test_parse_submission_handles_deleted_author():
    post = SimpleNamespace(title="t", selftext="", author=None, permalink="/p/",
                           created_utc=1781000000, score=0)
    assert parse_submission(post).author_handle == "u/[deleted]"


def test_parse_dcinside_fixture():
    html = """<table class="gall_list"><tbody>
      <tr class="ub-content us-post"><td class="gall_num">1</td>
        <td class="gall_tit ub-word"><a href="/board/view/?id=stock_new1&no=123">삼성전자 어디까지 가나</a></td>
        <td class="gall_writer ub-writer" data-nick="개미왕"></td></tr>
    </tbody></table>"""
    evs = parse_dcinside(html, "https://gall.dcinside.com/board/lists/?id=stock_new1")
    assert len(evs) == 1
    assert evs[0].source == "dcinside" and evs[0].author_handle == "개미왕"
    assert evs[0].text == "삼성전자 어디까지 가나"
    assert evs[0].url.startswith("https://gall.dcinside.com/board/view")


def test_parse_naver_fixture():
    html = """<table><tr>
      <td class="title"><a href="/item/board_read.naver?code=005930&nid=1" title="오늘 삼성 분석">오늘 삼성 분석</a></td>
      <td class="p11">2026.06.16</td></tr></table>"""
    evs = parse_naver(html, "005930")
    assert len(evs) == 1
    assert evs[0].source == "naver" and evs[0].text == "오늘 삼성 분석"
    assert evs[0].symbols == ["005930"]


def test_fetcher_enabled_flags():
    assert RedditFetcher("", "").enabled is False
    assert RedditFetcher("id", "secret").enabled is True
    assert StockTwitsFetcher().enabled is True            # public best-effort
    assert TwitterFetcher().enabled is False              # no cookies
    assert TwitterFetcher(auth_token="t", ct0="c").enabled is True
    assert TwitterFetcher(auth_token="t", ct0="c", enabled_flag=False).enabled is False
    assert DcInsideFetcher().enabled is True and NaverFetcher().enabled is True
