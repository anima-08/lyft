import logging
from dataclasses import dataclass

import litellm
from litellm.caching import Cache
from litellm.litellm_core_utils.hidden_params import served_from_cache

from .config import Settings
from .failover import simulated_status

logger = logging.getLogger(__name__)


class AllProvidersUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CompletionResult:
    reply: str
    resolution_source: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings

    def configure_cache(self) -> bool:
        litellm.telemetry = False
        litellm.suppress_debug_info = True
        litellm.cache = Cache(
            type="local",
            ttl=self.settings.cache_ttl_seconds,
            max_messages=None,
        )
        return litellm.cache is not None

    def complete(self, messages: list[dict], simulated_failures: dict[str, int]) -> CompletionResult:
        for index, api_key in enumerate(self.settings.llm_api_keys):
            key_id = f"key_{index + 1}"
            if simulated_status(simulated_failures, key_id) is not None:
                continue

            try:
                response = litellm.completion(**self._request_kwargs(messages, api_key))
                reply = self._extract_reply(response)
                input_tokens, output_tokens = self._extract_usage(response)
            except Exception as exc:
                logger.warning("Provider attempt %s failed (%s)", key_id, type(exc).__name__)
                continue

            if served_from_cache(response):
                return CompletionResult(
                    reply=reply,
                    resolution_source="LLM_CACHE",
                    model=self.settings.llm_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    key_id=None,
                    fallback_attempts=0,
                )

            return CompletionResult(
                reply=reply,
                resolution_source="LIVE_INFERENCE",
                model=self.settings.llm_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                key_id=key_id,
                fallback_attempts=index,
            )

        raise AllProvidersUnavailable("all providers unavailable")

    def _request_kwargs(self, messages: list[dict], api_key: str) -> dict:
        kwargs = {
            "model": self.settings.llm_model,
            "messages": messages,
            "api_key": api_key,
            "max_tokens": self.settings.max_output_tokens,
            "timeout": self.settings.request_timeout_seconds,
            "num_retries": 0,
        }
        # Gemini 3 models reject the temperature parameter outright.
        if self.settings.temperature is not None:
            kwargs["temperature"] = self.settings.temperature
        return kwargs

    @staticmethod
    def _extract_reply(response) -> str:
        if not response.choices:
            raise ValueError("provider returned no choices")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise ValueError("provider returned empty content")
        return content.strip()

    @staticmethod
    def _extract_usage(response) -> tuple[int, int]:
        usage = response.usage
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ValueError("provider returned invalid token usage")
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("provider returned negative token usage")
        return input_tokens, output_tokens
