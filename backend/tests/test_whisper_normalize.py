import pytest

from app.intel.whisper.normalize import parse_eps


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1.51", 1.51),
        ("1.51", 1.51),
        ("0.34 EPS", 0.34),
        ("($0.12)", -0.12),       # accounting-parenthesis negative
        ("-0.12", -0.12),
        ("loss of 12c", -0.12),   # cents + 'loss'
        ("12c", 0.12),
        ("12 cents", 0.12),
        ("EPS of $2.00 per share", 2.00),
        ("beat by", None),        # no number
        ("beat by 5%", None),     # percentage, not EPS
        ("whisper", None),
        ("", None),
        (None, None),
        ("150.0", None),          # > PLAUSIBLE_ABS_CAP — a price/units error, not EPS
    ],
)
def test_parse_eps(raw, expected):
    got = parse_eps(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)
