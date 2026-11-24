import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LLM_API_KEYS", "test-key-1,test-key-2")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm_api_keys=["test-key-1", "test-key-2"],
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        allowed_origins=["http://localhost:3000"],
        enable_failure_simulation=True,
    )


@pytest.fixture
def client(settings):
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture
def provider_calls(monkeypatch):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A real provider answer."))],
            usage=SimpleNamespace(prompt_tokens=42, completion_tokens=9),
            _hidden_params={"cache_hit": False},
        )

    monkeypatch.setattr("app.llm_gateway.litellm.completion", completion)
    return calls
