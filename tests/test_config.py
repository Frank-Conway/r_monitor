"""配置加载的校验/钳制逻辑单测。"""
from r_monitor.config import Settings


def _load_from(raw):
    """绕过磁盘，直接测字段钳制逻辑。"""
    from dataclasses import fields

    from r_monitor import config as c
    if not isinstance(raw, dict):
        raw = {}
    kwargs = {f.name: c._coerce(raw, f, f.default) for f in fields(Settings)}
    return Settings(**kwargs)


def test_defaults():
    s = _load_from({})
    assert s.refresh_interval_ms == 1000
    assert s.history_points == 300
    assert s.theme == "dark"
    assert s.close_action == "ask"


def test_clamps_out_of_range():
    s = _load_from({"refresh_interval_ms": 1, "history_points": 999999, "top_process_count": 99})
    assert s.refresh_interval_ms == 200      # 下限
    assert s.history_points == 6000          # 上限
    assert s.top_process_count == 10         # 上限


def test_invalid_types_fall_back():
    s = _load_from({
        "refresh_interval_ms": "abc",
        "upload_threshold_bps": "not-a-number",
        "theme": "neon",
        "close_action": "explode",
    })
    assert s.refresh_interval_ms == 1000
    assert s.upload_threshold_bps == 1024 * 1024
    assert s.theme == "dark"
    assert s.close_action == "ask"
