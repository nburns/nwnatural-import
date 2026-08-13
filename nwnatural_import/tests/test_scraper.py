from datetime import date

from nwnatural_import.scraper import _parse_row


def test_parses_standard_row():
    r = _parse_row(["07/21/2026", "July", "$16.56", "1.1"])
    assert r is not None
    assert r.read_date == date(2026, 7, 21)
    assert r.month_label == "July"
    assert r.total_bill_usd == 16.56
    assert r.therms == 1.1


def test_parses_row_with_thousands_separator():
    r = _parse_row(["12/18/2025", "December", "$1,138.69", "1,275.1"])
    assert r is not None
    assert r.total_bill_usd == 1138.69
    assert r.therms == 1275.1


def test_parses_row_with_zero_therms():
    r = _parse_row(["09/17/2025", "September", "$12.77", "0"])
    assert r is not None
    assert r.therms == 0.0


def test_rejects_row_with_bad_date():
    assert _parse_row(["not-a-date", "July", "$1", "1"]) is None


def test_rejects_short_row():
    assert _parse_row(["07/21/2026", "July"]) is None
