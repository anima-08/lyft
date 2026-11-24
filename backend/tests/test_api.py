import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_loaded_key_pool_and_cache(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_multi_turn_history_and_per_response_metadata(client, provider_calls):
    first = client.post("/chat", json={"session_id": "s-one", "message": "Capital of France?"})
    assert first.status_code == 200
    first_data = first.json()
    assert first_data["session_id"] == "s-one"
    assert first_data["reply"] == "A real provider answer."
    assert first_data["metadata"] == {
        "resolution_source": "LIVE_INFERENCE",
        "model": "gemini/gemini-2.5-flash",
        "latency_ms": first_data["metadata"]["latency_ms"],
        "input_tokens": 42,
        "output_tokens": 9,
        "key_id": "key_1",
        "fallback_attempts": 0,
    }
    assert isinstance(first_data["metadata"]["latency_ms"], int)

    second = client.post("/chat", json={"session_id": "s-one", "message": "And its population?"})
    assert second.status_code == 200
    sent_messages = provider_calls[1]["messages"]
    assert sent_messages == [
        {"role": "system", "content": provider_calls[0]["messages"][0]["content"]},
        {"role": "user", "content": "Capital of France?"},
        {"role": "assistant", "content": "A real provider answer."},
        {"role": "user", "content": "And its population?"},
    ]

    history = client.get("/sessions/s-one/messages")
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
    assert "metadata" not in messages[0]
    assert messages[1]["metadata"]["input_tokens"] == 42
    assert messages[1]["metadata"]["output_tokens"] == 9
    assert all(message["role"] != "system" for message in messages)


def test_sessions_stay_separate(client, provider_calls):
    client.post("/chat", json={"session_id": "s-one", "message": "Remember the number 17."})
    other = client.post("/chat", json={"session_id": "s-two", "message": "What number?"})
    assert other.status_code == 200
    assert provider_calls[1]["messages"] == [
        provider_calls[0]["messages"][0],
        {"role": "user", "content": "What number?"},
    ]
    assert client.get("/sessions/s-two/messages").json()["messages"] == [
        {"role": "user", "content": "What number?"},
        {
            "role": "assistant",
            "content": "A real provider answer.",
            "metadata": other.json()["metadata"],
        },
    ]


def test_system_prompt_is_used_and_persisted(client, provider_calls):
    first = client.post(
        "/chat",
        json={"session_id": "s-prompt", "message": "Hello", "system_prompt": "Answer in haiku."},
    )
    assert first.status_code == 200
    client.post("/chat", json={"session_id": "s-prompt", "message": "Follow up"})
    assert provider_calls[0]["messages"][0] == {"role": "system", "content": "Answer in haiku."}
    assert provider_calls[1]["messages"][0] == {"role": "system", "content": "Answer in haiku."}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"session_id": "s-one"},
        {"message": "Hello"},
        {"session_id": "", "message": "Hello"},
        {"session_id": "   ", "message": "Hello"},
        {"session_id": "x" * 129, "message": "Hello"},
        {"session_id": "s-one", "message": ""},
        {"session_id": "s-one", "message": "   "},
        {"session_id": "s-one", "message": "x" * 4001},
        {"session_id": "s-one", "message": "Hello", "system_prompt": "x" * 4001},
    ],
)
def test_invalid_requests_return_422_without_history(client, provider_calls, body):
    response = client.post("/chat", json=body)
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider_calls == []
    assert client.get("/sessions/s-one/messages").status_code == 404


def test_malformed_json_returns_structured_422(client, provider_calls):
    response = client.post(
        "/chat",
        content="{not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider_calls == []


def test_validation_failure_does_not_modify_existing_history(client, provider_calls):
    client.post("/chat", json={"session_id": "s-one", "message": "Valid"})
    before = client.get("/sessions/s-one/messages").json()
    response = client.post("/chat", json={"session_id": "s-one", "message": " "})
    assert response.status_code == 422
    assert client.get("/sessions/s-one/messages").json() == before
    assert len(provider_calls) == 1


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_simulated_key_failure_falls_over_to_next_key(client, provider_calls, status):
    response = client.post(
        "/chat",
        json={"session_id": f"s-failover-{status}", "message": "Give me a resilience tip."},
        headers={"X-Simulate-Failure": f"key_1={status}"},
    )
    assert response.status_code == 200
    metadata = response.json()["metadata"]
    assert response.json()["reply"] == "A real provider answer."
    assert metadata["key_id"] == "key_2"
    assert metadata["fallback_attempts"] == 1
    assert [call["api_key"] for call in provider_calls] == ["test-key-2"]


def test_every_key_failure_returns_503_and_writes_nothing(client, provider_calls):
    response = client.post(
        "/chat",
        json={"session_id": "s-failed", "message": "Do not store this"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert provider_calls == []
    assert client.get("/sessions/s-failed/messages").status_code == 404


def test_failed_follow_up_keeps_existing_history_unchanged(client, provider_calls):
    client.post("/chat", json={"session_id": "s-one", "message": "First"})
    before = client.get("/sessions/s-one/messages").json()
    response = client.post(
        "/chat",
        json={"session_id": "s-one", "message": "Second"},
        headers={"X-Simulate-Failure": "*=500"},
    )
    assert response.status_code == 503
    assert client.get("/sessions/s-one/messages").json() == before
    assert len(provider_calls) == 1


def test_disabled_simulation_header_is_ignored(settings, provider_calls):
    settings.enable_failure_simulation = False
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/chat",
            json={"session_id": "s-one", "message": "Hello"},
            headers={"X-Simulate-Failure": "*=429"},
        )
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_1"


@pytest.mark.parametrize("header", ["key_1", "key_1=401", "key_3=429", "key_1=429,"])
def test_invalid_simulation_header_returns_422(client, provider_calls, header):
    response = client.post(
        "/chat",
        json={"session_id": "s-one", "message": "Hello"},
        headers={"X-Simulate-Failure": header},
    )
    assert response.status_code == 422
    assert "detail" in response.json()
    assert provider_calls == []


def test_unknown_session_returns_404(client):
    response = client.get("/sessions/s-unknown/messages")
    assert response.status_code == 404
    assert response.json() == {"detail": "session not found"}


def test_cors_allows_configured_frontend(client):
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_database_history_survives_application_restart(settings, provider_calls):
    with TestClient(create_app(settings)) as first_client:
        first_client.post("/chat", json={"session_id": "s-persistent", "message": "Remember me"})
    with TestClient(create_app(settings)) as second_client:
        response = second_client.get("/sessions/s-persistent/messages")
    assert response.status_code == 200
    assert response.json()["messages"][0]["content"] == "Remember me"


def test_real_provider_exceptions_fall_over_without_leaking_details(client, provider_calls, monkeypatch):
    def failing_completion(**kwargs):
        if kwargs["api_key"] == "test-key-1":
            raise RuntimeError("sensitive provider diagnostic")
        return provider_calls_and_return(kwargs)

    def provider_calls_and_return(kwargs):
        provider_calls.append(kwargs)
        from types import SimpleNamespace

        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Recovered answer."))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
            _hidden_params={"cache_hit": False},
        )

    monkeypatch.setattr("app.llm_gateway.litellm.completion", failing_completion)
    response = client.post("/chat", json={"session_id": "s-recovery", "message": "Hello"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Recovered answer."
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert "sensitive" not in response.text
