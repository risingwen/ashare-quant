from __future__ import annotations

from quant_core import (
    compact_date,
    is_limit_down,
    is_limit_up,
    is_st_name,
    limit_threshold,
    make_meta,
    market_of,
    normalize_date,
    to_float,
)


def test_market_classification_and_eligibility() -> None:
    assert market_of("300750") == "ChiNext"
    assert market_of("688001") == "STAR"
    assert market_of("920001") == "BSE"
    assert market_of("600000") == "Mainboard"

    meta = make_meta("600000", "浦发银行")
    assert meta.market == "Mainboard"
    assert meta.eligible is True

    st_meta = make_meta("600001", "*ST示例")
    assert st_meta.is_st is True
    assert st_meta.eligible is False


def test_limit_thresholds() -> None:
    assert limit_threshold("Mainboard", False) == 9.8
    assert limit_threshold("ChiNext", False) == 19.5
    assert limit_threshold("STAR", False) == 19.5
    assert limit_threshold("BSE", False) == 29.5
    assert limit_threshold("Mainboard", True) == 4.8

    assert is_limit_up(9.8, "Mainboard", False)
    assert not is_limit_up(9.7, "Mainboard", False)
    assert is_limit_down(-19.5, "STAR", False)


def test_date_and_float_normalization() -> None:
    assert normalize_date("20260608") == "2026-06-08"
    assert normalize_date("2026-06-08 15:00:00") == "2026-06-08"
    assert compact_date("2026-06-08") == "20260608"
    assert to_float("1.23") == 1.23
    assert to_float("") is None
    assert to_float("nan") is None


def test_st_name_detection() -> None:
    assert is_st_name("*ST中迪")
    assert is_st_name("退市示例")
    assert not is_st_name("贵州茅台")
