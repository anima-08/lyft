import litellm
import pytest


@pytest.fixture
def cached_provider(monkeypatch):
    real_completion = litellm.completion

    def completion(**kwargs):
        return real_completion(
            **kwargs,
            mock_response="Cached provider answer.",
            mock_delay=0.05,
        )

    monkeypatch.setattr("app.llm_gateway.litellm.completion", completion)


def test_real_cache_hit_preserves_reply_usage_and_latency(client, cached_provider):
    first = client.post("/chat", json={"session_id": "s-cache-one", "message": "Cache this answer"})
    second = client.post("/chat", json={"session_id": "s-cache-two", "message": "Cache this answer"})

    assert first.status_code == second.status_code == 200
    first_data = first.json()
    second_data = second.json()
    assert first_data["reply"] == second_data["reply"] == "Cached provider answer."
    assert first_data["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert first_data["metadata"]["key_id"] == "key_1"
    assert first_data["metadata"]["fallback_attempts"] == 0
    assert second_data["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second_data["metadata"]["key_id"] is None
    assert second_data["metadata"]["fallback_attempts"] == 0
    assert second_data["metadata"]["input_tokens"] == first_data["metadata"]["input_tokens"] == 10
    assert second_data["metadata"]["output_tokens"] == first_data["metadata"]["output_tokens"] == 20
    measured_live = client.post(
        "/chat", json={"session_id": "s-cache-three", "message": "Measure a warm cache hit"}
    )
    measured_cached = client.post(
        "/chat", json={"session_id": "s-cache-four", "message": "Measure a warm cache hit"}
    )
    assert measured_live.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert measured_cached.json()["metadata"]["resolution_source"] == "LLM_CACHE"
    assert (
        measured_cached.json()["metadata"]["latency_ms"] + 20
        < measured_live.json()["metadata"]["latency_ms"]
    )

    history = client.get("/sessions/s-cache-two/messages").json()["messages"]
    assert history[1]["metadata"] == second_data["metadata"]


def test_real_cache_key_changes_with_message_or_system_prompt(client, cached_provider):
    requests = [
        {"session_id": "s-message-one", "message": "First cache key"},
        {"session_id": "s-message-two", "message": "First cache key"},
        {"session_id": "s-message-three", "message": "Different cache key"},
        {
            "session_id": "s-prompt-one",
            "message": "Prompt cache key",
            "system_prompt": "Answer in one sentence.",
        },
        {
            "session_id": "s-prompt-two",
            "message": "Prompt cache key",
            "system_prompt": "Answer in one sentence.",
        },
        {
            "session_id": "s-prompt-three",
            "message": "Prompt cache key",
            "system_prompt": "Answer in haiku.",
        },
    ]

    responses = [client.post("/chat", json=payload) for payload in requests]
    assert all(response.status_code == 200 for response in responses)
    assert [response.json()["metadata"]["resolution_source"] for response in responses] == [
        "LIVE_INFERENCE",
        "LLM_CACHE",
        "LIVE_INFERENCE",
        "LIVE_INFERENCE",
        "LLM_CACHE",
        "LIVE_INFERENCE",
    ]


def test_real_cache_hit_has_no_key_or_fallback_identity(client, cached_provider):
    client.post("/chat", json={"session_id": "s-first", "message": "Share this cached response"})
    cached = client.post(
        "/chat",
        json={"session_id": "s-second", "message": "Share this cached response"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )

    assert cached.status_code == 200
    metadata = cached.json()["metadata"]
    assert metadata["resolution_source"] == "LLM_CACHE"
    assert metadata["key_id"] is None
    assert metadata["fallback_attempts"] == 0
