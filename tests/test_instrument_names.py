"""Public-name identity/failure contracts; all persistence is synthetic."""

import json
from datetime import datetime, timezone

import pytest

from stock_tool.application.instrument_names import NameDirectory, parse_names
from stock_tool.dashboard.instrument_names import current_names, name_notice
from stock_tool.dashboard.presentation_mapper import format_taiwan_company_display


def company(code="3006", name="晶豪科"):
    return {
        "公司代號": code,
        "公司簡稱": name,
        "公司名稱": name + "股份有限公司",
        "出表日期": "1151002",
    }


def fetch(url):
    if "t187ap03_L" in url:
        return [company(), company("2330", "台積電")]
    if "t187ap03_O" in url:
        return [company("6488", "環球晶"), company("8069", "元太")]
    if "twse" in url:
        return [{"Code": "00935", "Name": "野村臺灣新科技50", "Date": "1151002"}]
    return [{"SecuritiesCompanyCode": "00679B", "CompanyName": "元大美債20年", "Date": "1151002"}]


def test_shared_identity_names_restart_and_failed_update(tmp_path):
    path = tmp_path / "names.json"
    directory = NameDirectory(path)
    directory.refresh(fetch)
    initial = directory.resolve("TWSE", "3006")[0]
    assert initial.name == "晶豪科"
    assert directory.resolve("TPEX", "3006")[0] is None
    assert directory.resolve("US", "3006")[0] is None
    assert directory.resolve("TWSE", "00935")[0].source.endswith("STOCK_DAY_ALL")
    assert directory.resolve("TPEX", "00679B")[0].source.endswith("daily_close_quotes")
    assert directory.resolve("TPEX", "8069")[0].name == "元太"
    token = current_names.set(directory)
    try:
        for symbol, market, expected in [
            ("3006", "TWSE", "晶豪科"),
            ("6488", "TPEX", "環球晶"),
            ("00935", "TWSE", "野村臺灣新科技50"),
            ("MU", "US", "MU"),
            ("3006", "TWSE", "晶豪科"),
        ]:
            assert format_taiwan_company_display(symbol, market=market).startswith(expected)
        assert name_notice("TWSE", "9999") == "中文名稱未確認"
    finally:
        current_names.reset(token)

    def offline(url):
        raise OSError("offline")

    directory.refresh(offline, force=True)
    recovered = NameDirectory(path)
    record, notice = recovered.resolve("TWSE", "3006")
    assert record == initial
    assert "沿用前次" in notice
    assert len(recovered.errors) == 4


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {},
        [{"公司代號": "3006"}],
        [company(), company(name="錯誤")],
        [{**company(), "Market": "TPEX"}],
    ],
)
def test_invalid_batch_does_not_overwrite_good_cache(tmp_path, bad):
    directory = NameDirectory(tmp_path / "names.json")
    directory.refresh(fetch)
    before = directory.resolve("TWSE", "3006")[0]
    directory.refresh(lambda url: bad, force=True)
    assert directory.resolve("TWSE", "3006")[0] == before
    assert directory.errors


def test_corrupted_cache_and_first_offline_are_unconfirmed(tmp_path):
    path = tmp_path / "names.json"
    path.write_text('{"sha256":"bad","data":{}}')
    directory = NameDirectory(path)
    assert directory.resolve("TWSE", "3006") == (None, "中文名稱未確認")
    directory.refresh(lambda url: [])
    assert directory.resolve("TWSE", "3006")[0] is None


def test_company_and_security_directories_stay_separate():
    now = datetime.now(timezone.utc).isoformat()
    names = parse_names([company()], "TWSE", "companies", now)
    assert "00935" not in names
    assert "公司" not in names["3006"].source
    with pytest.raises(ValueError):
        parse_names([company()], "US", "companies", now)


def test_official_chinese_full_name_when_short_name_is_latin():
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "公司代號": "6902",
        "公司簡稱": "GOGOLOOK",
        "公司名稱": "走著瞧股份有限公司",
        "出表日期": "1151002",
    }
    names = parse_names([row], "TWSE", "companies", now)
    assert names["6902"].name == "走著瞧股份有限公司"
    assert names["6902"].full_name == names["6902"].name


def test_display_does_not_mutate_provider_or_saved_research(tmp_path):
    source = {
        "symbol": "3006",
        "market": "TWSE",
        "company_name": "ESMT",
        "quantity": 7,
        "cost": 99,
        "score": 42,
    }
    before = json.dumps(source)
    directory = NameDirectory(tmp_path / "names.json")
    directory.refresh(fetch)
    token = current_names.set(directory)
    try:
        assert (
            format_taiwan_company_display(
                source["symbol"], source["company_name"], source["market"]
            )
            == "晶豪科 (3006)"
        )
    finally:
        current_names.reset(token)
    assert json.dumps(source) == before
