import pytest
from pydantic import ValidationError

from app.config import Settings


def test_comma_separated_environment_values_are_parsed(monkeypatch):
    monkeypatch.setenv("LLM_API_KEYS", " first-key , second-key ")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://one.test, http://two.test")
    settings = Settings(_env_file=None)
    assert settings.llm_api_keys == ["first-key", "second-key"]
    assert settings.allowed_origins == ["http://one.test", "http://two.test"]


def test_runtime_requires_at_least_two_keys(tmp_path):
    settings = Settings(
        llm_api_keys=["only-one"],
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        _env_file=None,
    )
    with pytest.raises(ValueError, match="at least two"):
        settings.validate_runtime()


def test_non_sqlite_database_is_rejected():
    with pytest.raises(ValidationError):
        Settings(llm_api_keys=["one", "two"], database_url="postgresql://localhost/app", _env_file=None)
