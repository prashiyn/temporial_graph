from __future__ import annotations

import time
from typing import Any

import httpx

from .config import LLMServiceConfig


class LLMClient:
    def __init__(self, config: LLMServiceConfig) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=self.config.base_url.rstrip("/"),
            timeout=self.config.timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def _auth_headers(self) -> dict[str, str]:
        mode = self.config.auth_mode
        token = self.config.auth_token

        if mode == "none":
            return {}
        if mode == "api_key" and token:
            return {"x-api-key": token}
        if mode == "bearer" and token:
            return {"Authorization": f"Bearer {token}"}
        return {}

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        retries = max(0, self.config.max_retries)
        base = max(1, self.config.retry_base_delay_ms)
        max_delay = max(base, self.config.retry_max_delay_ms)

        for attempt in range(retries + 1):
            try:
                response = self._client.request(
                    method,
                    path,
                    json=json_payload,
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
                if attempt >= retries:
                    raise
                delay_ms = min(base * (2**attempt), max_delay)
                time.sleep(delay_ms / 1000.0)

        raise RuntimeError("Unexpected retry loop termination")

    def models(self) -> dict[str, Any]:
        return self._request_with_retry("GET", "/llm/models")

    def complete(
        self,
        *,
        task_name: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        reasoning_effort: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self.config.task(task_name)
        payload: dict[str, Any] = {
            "provider": task.provider,
            "messages": messages,
        }

        chosen_model = model or task.model
        if chosen_model:
            payload["model"] = chosen_model

        chosen_reasoning = reasoning_effort or task.reasoning_effort
        if chosen_reasoning:
            payload["reasoning_effort"] = chosen_reasoning

        chosen_response_format = response_format or task.response_format
        if chosen_response_format:
            payload["response_format"] = chosen_response_format

        return self._request_with_retry("POST", "/llm/complete", json_payload=payload)

    def embeddings(
        self,
        *,
        task_name: str = "embeddings",
        input_value: str | list[str] = "",
        model: str | None = None,
        encoding_format: str | None = None,
        dimensions: int | None = None,
        input_type: str | None = None,
        user: str | None = None,
    ) -> dict[str, Any]:
        task = self.config.task(task_name)

        payload: dict[str, Any] = {
            "provider": task.provider,
            "input": input_value,
        }
        chosen_model = model or task.model
        if chosen_model:
            payload["model"] = chosen_model
        if encoding_format:
            payload["encoding_format"] = encoding_format
        if dimensions is not None:
            payload["dimensions"] = dimensions
        if input_type:
            payload["input_type"] = input_type
        if user:
            payload["user"] = user

        return self._request_with_retry("POST", "/llm/embeddings", json_payload=payload)
