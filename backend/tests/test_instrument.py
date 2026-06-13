import pytest

from app.core.instrument import InvalidInstrument, parse_instrument


def test_parses_and_uppercases():
    assert parse_instrument("aapl:nasdaq") == ("AAPL", "NASDAQ")
    assert parse_instrument("005930:KRX") == ("005930", "KRX")


@pytest.mark.parametrize("bad", ["AAPL", "AAPL:FOO", ":KRX", "AAPL:", "A B:KRX", "AAPL:NASDAQ:X"])
def test_rejects_bad(bad):
    with pytest.raises(InvalidInstrument):
        parse_instrument(bad)
