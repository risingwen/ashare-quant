import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_popularity_excursion_dashboard.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("popularity_excursion_dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_strict_core_requires_rank_and_absence_from_same_source():
    assert MODULE._strict_core({"is_new": True, "rank": 4, "absent_days": 10}) is True
    assert MODULE._strict_core({"is_new": True, "rank": 4, "absent_days": 2}) is False
    assert MODULE._strict_core({"is_new": False, "rank": 2, "absent_days": 20}) is False


def test_render_embeds_excursion_data_safely(tmp_path):
    template = tmp_path / "template.html"
    output = tmp_path / "output.html"
    template.write_text(
        '<script>__EXCURSION_DATA__</script><script>__EXCURSION_METADATA__</script>',
        encoding="utf-8",
    )

    MODULE.render([{"name": "</script>"}], {"parameters": {}}, template, output)

    rendered = output.read_text(encoding="utf-8")
    assert "__EXCURSION" not in rendered
    assert "<\\/script>" in rendered


def test_template_contains_both_high_and_low_probability_views():
    template = (SCRIPT.parent / "popularity_excursion_dashboard.html").read_text(encoding="utf-8")

    assert "T+1最低≤−2%" in template
    assert "T+1最低≤−7%" in template
    assert "T+1最高≥+2%" in template
    assert "T+1最高≥+7%" in template
    assert 'id="lowDistribution"' in template
    assert 'id="highDistribution"' in template


def test_template_contains_drop7_followthrough_and_excess_views():
    template = (SCRIPT.parent / "popularity_excursion_dashboard.html").read_text(encoding="utf-8")

    assert "T+1跌7%成交后：T+1 / T+2 / T+3收益" in template
    assert 'id="t1Average"' in template
    assert 'id="t2Excess"' in template
    assert 'id="t3Excess"' in template
    assert 'id="drop7Records"' in template
    assert 'id="drop7Sort"' in template
    assert "时间倒序（最新优先）" in template
    assert "买卖成本合计0.19%" in template


def test_t1_mark_to_market_charges_only_buy_cost():
    result = MODULE._mark_to_market(100.0, 100.0)

    assert result == pytest.approx(-0.06995103427699467)


def test_limit_flags_distinguish_one_word_from_intraday_touch():
    one_word = {"open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0}
    intraday = {"open": 9.4, "high": 9.5, "low": 9.0, "close": 9.2}

    assert MODULE._limit_flags(one_word, 9.0) == (True, True, True)
    assert MODULE._limit_flags(intraday, 9.0) == (True, False, False)


def test_template_has_limit_down_filter_and_pagination():
    template = (SCRIPT.parent / "popularity_excursion_dashboard.html").read_text(encoding="utf-8")

    assert 'id="dropLimit"' in template
    assert "排除一字跌停" in template
    assert "一字跌停·未成交" in template
    assert 'id="drop7Prev"' in template
    assert 'id="drop7Next"' in template
    assert 'id="samplePrev"' in template
    assert 'id="sampleNext"' in template
