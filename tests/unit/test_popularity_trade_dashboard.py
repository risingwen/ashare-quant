import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_popularity_trade_dashboard.py"
SPEC = importlib.util.spec_from_file_location("popularity_trade_dashboard", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

_consecutive_absent_days = MODULE._consecutive_absent_days
_benchmark_comparison = MODULE._benchmark_comparison
_benchmark_for_symbol = MODULE._benchmark_for_symbol
_candle_label = MODULE._candle_label
_csv_value = MODULE._csv_value
_source_scope = MODULE._source_scope
render_html = MODULE.render_html


def test_counts_consecutive_complete_days_outside_top_ten():
    calendar = [f"2026-01-0{day}" for day in range(1, 7)]
    fillers = {f"S{index}" for index in range(10)}
    top10 = {("dc_hot", run_date): set(fillers) for run_date in calendar}
    top10[("dc_hot", calendar[1])].add("000001")

    absent, complete = _consecutive_absent_days("000001", "dc_hot", 5, calendar, top10)

    assert absent == 3
    assert complete is True


def test_stops_absence_count_when_a_prior_list_is_incomplete():
    calendar = [f"2026-01-0{day}" for day in range(1, 7)]
    fillers = {f"S{index}" for index in range(10)}
    top10 = {("dc_hot", run_date): set(fillers) for run_date in calendar}
    top10[("dc_hot", calendar[3])] = {"S1"}

    absent, complete = _consecutive_absent_days("000001", "dc_hot", 5, calendar, top10)

    assert absent == 1
    assert complete is False


def test_source_scope_merges_same_stock_day_without_losing_provenance():
    assert _source_scope({"dc_new_top10": True, "ths_new_top10": True}) == "双榜新进"
    assert _source_scope({"dc_new_top10": True, "ths_new_top10": False}) == "东方财富"
    assert _source_scope({"dc_new_top10": False, "ths_new_top10": True}) == "同花顺"


def test_source_scope_labels_all_top_ten_membership():
    assert _source_scope({"dc_rank": 3, "ths_rank": 7}, "all") == "双榜前十"
    assert _source_scope({"dc_rank": 9, "ths_rank": 20}, "all") == "东方财富"
    assert _source_scope({"dc_rank": None, "ths_rank": 5}, "all") == "同花顺"


def test_maps_complete_stock_code_families_to_requested_indices():
    assert _benchmark_for_symbol("600000") == ("000001.SH", "上证综指")
    assert _benchmark_for_symbol("601318") == ("000001.SH", "上证综指")
    assert _benchmark_for_symbol("002594") == ("399001.SZ", "深证成指")
    assert _benchmark_for_symbol("301236") == ("399006.SZ", "创业板指")
    assert _benchmark_for_symbol("688981") == ("000688.SH", "科创50")
    assert _benchmark_for_symbol("920001") is None


def test_labels_entry_candle_from_open_and_close():
    assert _candle_label(10.0, 10.1) == "阳线"
    assert _candle_label(10.0, 9.9) == "阴线"
    assert _candle_label(10.0, 10.0) == "平盘"


def test_reads_flattened_high_factor_for_csv_export():
    record = {"high_factors": {"120": {"distance_pct": -1.25, "close_breakout": False}}}

    assert _csv_value(record, "high_120_distance_pct") == -1.25
    assert _csv_value(record, "high_120_close_breakout") is False


def test_benchmark_comparison_reports_retention_and_performance_delta():
    records = [
        {"rule_return_pct": 3.0, "benchmark_above_ma5": True, "benchmark_code": "000001.SH"},
        {"rule_return_pct": -1.0, "benchmark_above_ma5": False, "benchmark_code": "000001.SH"},
        {"rule_return_pct": 1.0, "benchmark_above_ma5": True, "benchmark_code": "399001.SZ"},
    ]

    comparison = _benchmark_comparison(records)

    assert comparison["covered_records"] == 3
    assert comparison["above_ma5"]["records"] == 2
    assert comparison["retained_pct"] == 2 / 3 * 100
    assert comparison["baseline"]["win_rate_pct"] == 2 / 3 * 100
    assert comparison["above_ma5"]["win_rate_pct"] == 100


def test_render_html_embeds_json_safely(tmp_path):
    template = tmp_path / "template.html"
    output = tmp_path / "dashboard.html"
    template.write_text(
        '<script id="data">__DASHBOARD_DATA__</script>'
        '<script id="meta">__DASHBOARD_METADATA__</script>__GENERATED_AT__',
        encoding="utf-8",
    )

    render_html(
        [{"name": "</script>"}], {"parameters": {}}, template, output,
        {"title": "核心人气", "defaults": {"rankMax": 5}},
    )
    rendered = output.read_text(encoding="utf-8")

    assert "__DASHBOARD" not in rendered
    assert "<\\/script>" in rendered
    assert "核心人气" in rendered


def test_trade_detail_is_a_responsive_right_side_inspector():
    template = (SCRIPT.parent / "popularity_trade_dashboard.html").read_text(encoding="utf-8")

    assert 'class="records-layout" id="recordsLayout"' in template
    assert '.records-layout.has-detail { display:grid;' in template
    assert '.detail-panel { position:sticky;' in template
    assert '@media(max-width:980px)' in template
    assert 'window.matchMedia("(max-width: 980px)").matches' in template
    assert 'panel.scrollIntoView' in template
    assert 'layout.classList.add("has-detail")' in template


def test_rank_and_absence_filters_use_the_same_popularity_source():
    template = (SCRIPT.parent / "popularity_trade_dashboard.html").read_text(encoding="utf-8")

    assert "function rankAbsentMatch(record,rankMax,absent)" in template
    assert "return dc||ths;" in template
    assert "!rankAbsentMatch(record,rankMax,absent)" in template
    assert "record.dc_new_top10&&record.dc_rank<=5&&record.dc_absent_days>=10" in template
