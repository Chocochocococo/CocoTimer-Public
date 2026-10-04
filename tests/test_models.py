from cocotimer.models import Event, Settings, TaskItem, ThemeConfig


def test_missing_optional_fields_use_defaults():
    task = TaskItem.from_dict({"id": "t", "project_name": "p", "title": "x",
                               "due_date": "2026-10-03", "due_time": "18:00"})
    assert task.currency == "NTD"
    assert task.price_items == []
    assert task.completion == 0


def test_unknown_fields_survive_round_trip():
    event = Event.from_dict({"id": "e", "title": "t", "date": "2026-10-03", "time": "10:00",
                             "color": "blue", "tags": ["a"]})
    data = event.to_dict()
    assert data["color"] == "blue"
    assert data["tags"] == ["a"]
    assert data["title"] == "t"


def test_known_fields_win_over_stale_extras():
    event = Event.from_dict({"id": "e", "title": "old", "date": "d", "time": "t"})
    event.title = "new"
    assert event.to_dict()["title"] == "new"


def test_settings_theme_is_parsed_and_keeps_its_extras():
    settings = Settings.from_dict({"volume": 0.5, "theme": {"bg_color": "#000000", "glow": 3}})
    assert isinstance(settings.theme, ThemeConfig)
    assert settings.theme.bg_color == "#000000"
    data = settings.to_dict()
    assert data["volume"] == 0.5
    assert data["theme"]["glow"] == 3


def test_settings_without_theme_gets_default_theme():
    assert Settings.from_dict({}).theme == ThemeConfig()


def test_required_fields():
    assert Event.required_fields() == ["id", "title", "date", "time"]


def test_new_settings_start_with_welcome_and_ntd():
    s = Settings.from_dict({"volume": 0.5})  # 舊版設定檔沒有這兩個欄位
    assert s.welcome_done is False and s.default_currency == "NTD"


def test_work_sessions_never_count_negative_time():
    from cocotimer.models import WorkRecord
    rec = WorkRecord(date="2026-10-04", sessions=[{"start": "2026-10-04T09:00:00", "end": "2026-10-04T10:30:00"},
                                                  {"start": "2026-10-04T14:00:00", "end": "2026-10-04T13:00:00"}])
    assert rec.calculate_total_hours() == 1.5
