from app.services import limits, settings_service


def _settings(monkeypatch, *, edits=3, per_day=2):
    monkeypatch.setattr(
        settings_service, "get_settings",
        lambda: settings_service.StudioSettings(edits, per_day, ""),
    )


def test_can_edit_respects_cap(monkeypatch):
    _settings(monkeypatch, edits=2)
    monkeypatch.setattr(limits, "edit_count", lambda sid: 1)
    assert limits.can_edit("s1") is True
    monkeypatch.setattr(limits, "edit_count", lambda sid: 2)
    assert limits.can_edit("s1") is False


def test_can_start_design_allows_when_no_email(monkeypatch):
    _settings(monkeypatch, per_day=2)
    assert limits.can_start_design(None) is True


def test_can_start_design_respects_daily_cap(monkeypatch):
    _settings(monkeypatch, per_day=2)
    monkeypatch.setattr(limits, "designs_today", lambda email: 2)
    assert limits.can_start_design("a@b.com") is False
    monkeypatch.setattr(limits, "designs_today", lambda email: 1)
    assert limits.can_start_design("a@b.com") is True
