from app.config import Settings


def test_flag_defaults_false():
    s = Settings()  # type: ignore[call-arg]
    assert s.canvas_orchestrator_v2 is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("CANVAS_ORCHESTRATOR_V2", "true")
    s = Settings()  # type: ignore[call-arg]
    assert s.canvas_orchestrator_v2 is True
