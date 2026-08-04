import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_ultra_short_research_report.py"
SPEC = importlib.util.spec_from_file_location("ultra_short_research_report", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_core_condition_keeps_rank_and_absence_on_same_source():
    crossed = {
        "dc_rank": "3", "dc_absent_days": "0",
        "ths_rank": "8", "ths_absent_days": "12",
    }
    strict = {
        "dc_rank": "3", "dc_absent_days": "12",
        "ths_rank": "8", "ths_absent_days": "0",
    }

    assert MODULE._is_core(crossed) is False
    assert MODULE._is_core(strict) is True


def test_report_embeds_json_safely(tmp_path):
    template = tmp_path / "template.html"
    output = tmp_path / "report.html"
    template.write_text('<script id="data">__REPORT_DATA__</script>', encoding="utf-8")

    MODULE.render_html({"value": "</script>"}, template, output)

    rendered = output.read_text(encoding="utf-8")
    assert "__REPORT_DATA__" not in rendered
    assert "<\\/script>" in rendered


def test_report_uses_primary_data_and_rule_sources():
    urls = {item["url"] for item in MODULE.SOURCES}

    assert "https://tushare.pro/document/2?doc_id=312" in urls
    assert any("sse.com.cn" in url for url in urls)
    assert any("szse.cn" in url for url in urls)
