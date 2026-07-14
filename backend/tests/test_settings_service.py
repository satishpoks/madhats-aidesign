from app.services import settings_service


def test_get_settings_falls_back_to_env_defaults(monkeypatch):
    # No DB row values -> env defaults from config.
    monkeypatch.setattr(settings_service, "_read_row", lambda: {})
    settings_service.invalidate_cache()
    s = settings_service.get_settings()
    assert s.regen_edits_per_session == 3
    assert s.designs_per_customer_per_day == 2
    assert s.faq_knowledge == ""


def test_db_row_overrides_env(monkeypatch):
    monkeypatch.setattr(
        settings_service,
        "_read_row",
        lambda: {"regen_edits_per_session": 5, "designs_per_customer_per_day": 1, "faq_knowledge": "hi"},
    )
    settings_service.invalidate_cache()
    s = settings_service.get_settings()
    assert s.regen_edits_per_session == 5
    assert s.designs_per_customer_per_day == 1
    assert s.faq_knowledge == "hi"


def test_watermark_text_defaults_and_overrides(monkeypatch):
    # Missing/blank -> default; a value overrides.
    monkeypatch.setattr(settings_service, "_read_row", lambda: {})
    settings_service.invalidate_cache()
    assert settings_service.get_settings().watermark_text == "MADHATS PREVIEW"

    monkeypatch.setattr(settings_service, "_read_row", lambda: {"watermark_text": "ACME CO"})
    settings_service.invalidate_cache()
    assert settings_service.get_settings().watermark_text == "ACME CO"


def test_cache_is_used_until_invalidated(monkeypatch):
    calls = {"n": 0}

    def _row():
        calls["n"] += 1
        return {"regen_edits_per_session": 7}

    monkeypatch.setattr(settings_service, "_read_row", _row)
    settings_service.invalidate_cache()
    settings_service.get_settings()
    settings_service.get_settings()
    assert calls["n"] == 1
    settings_service.invalidate_cache()
    settings_service.get_settings()
    assert calls["n"] == 2
