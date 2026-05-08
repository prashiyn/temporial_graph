from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _repo_root() -> Path:
    # src/temporial_graph_rag/llm/config.py -> parents[3] == repository root
    return Path(__file__).resolve().parents[3]


def _default_llm_config_yaml_path() -> Path:
    return _repo_root() / "llm_config.yaml"


def _resolved_llm_config_path() -> Path:
    raw = (os.getenv("LLM_CONFIG_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _default_llm_config_yaml_path()


@dataclass(frozen=True)
class LLMTaskConfig:
    provider: str
    model: str | None = None
    reasoning_effort: str | None = None
    response_format: dict[str, Any] | None = None


@dataclass(frozen=True)
class LLMServiceConfig:
    base_url: str
    auth_mode: str
    auth_token: str | None
    timeout_seconds: int
    max_retries: int
    retry_base_delay_ms: int
    retry_max_delay_ms: int
    tasks: dict[str, LLMTaskConfig]

    @staticmethod
    def default_tasks() -> dict[str, LLMTaskConfig]:
        """Built-in defaults when no YAML / env override applies.

        ``provider`` is a logical label forwarded to **llm-service**;
        use ``llm_config.yaml`` (or env) to set groq, openai, anthropic, etc. per task.
        """
        return {
            "statement_extraction": LLMTaskConfig(provider="openai"),
            "temporal_range_extraction": LLMTaskConfig(provider="openai"),
            "event_or_triplet_extraction": LLMTaskConfig(provider="openai"),
            "entity_resolution_assist": LLMTaskConfig(provider="openai"),
            "retrieval_planner": LLMTaskConfig(provider="openai"),
            "retrieval_step": LLMTaskConfig(provider="openai"),
            "retrieval_trend_synthesis": LLMTaskConfig(provider="openai"),
            "answer_synthesis": LLMTaskConfig(provider="openai"),
            "embeddings": LLMTaskConfig(provider="openai"),
        }

    @staticmethod
    def _load_yaml_file(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required to read llm_config.yaml") from exc
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _yaml_service_section(data: dict[str, Any]) -> dict[str, Any]:
        svc = data.get("llm_service")
        if isinstance(svc, dict):
            return svc
        llm = data.get("llm")
        if isinstance(llm, dict) and isinstance(llm.get("service"), dict):
            return llm["service"]
        return {}

    @staticmethod
    def _yaml_tasks_section(data: dict[str, Any]) -> dict[str, Any]:
        t = data.get("tasks")
        if isinstance(t, dict):
            return t
        llm = data.get("llm")
        if isinstance(llm, dict) and isinstance(llm.get("tasks"), dict):
            return llm["tasks"]
        return {}

    @staticmethod
    def _task_from_yaml_dict(raw: dict[str, Any], base: LLMTaskConfig) -> LLMTaskConfig:
        prov = raw.get("provider", base.provider)
        provider = str(prov).strip() if prov is not None else base.provider
        if not provider:
            provider = base.provider

        if "model" in raw:
            m = raw["model"]
            if m is None or (isinstance(m, str) and not m.strip()):
                model: str | None = None
            else:
                model = str(m).strip()
        else:
            model = base.model

        if "reasoning_effort" in raw:
            re = raw["reasoning_effort"]
            reasoning = None if re is None or (isinstance(re, str) and not re.strip()) else str(re).strip()
        else:
            reasoning = base.reasoning_effort

        rf = raw.get("response_format")
        if rf is not None and not isinstance(rf, dict):
            rf = base.response_format

        return LLMTaskConfig(
            provider=provider,
            model=model,
            reasoning_effort=reasoning,
            response_format=rf if isinstance(rf, dict) else base.response_format,
        )

    @staticmethod
    def _task_from_env(task_name: str, default: LLMTaskConfig) -> LLMTaskConfig:
        prefix = f"LLM_TASK_{task_name.upper()}"
        provider = os.getenv(f"{prefix}_PROVIDER", default.provider)
        model = os.getenv(f"{prefix}_MODEL", default.model)
        reasoning_effort = os.getenv(f"{prefix}_REASONING_EFFORT", default.reasoning_effort)
        return LLMTaskConfig(
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            response_format=default.response_format,
        )

    @classmethod
    def from_env(cls) -> "LLMServiceConfig":
        path = _resolved_llm_config_path()
        data = cls._load_yaml_file(path)
        yaml_service = cls._yaml_service_section(data)
        yaml_tasks_raw = cls._yaml_tasks_section(data)

        auth_token = os.getenv("LLM_SERVICE_AUTH_TOKEN")
        auth_token = auth_token if auth_token else None

        def _svc_str(env_key: str, yaml_key: str, default: str) -> str:
            ev = os.getenv(env_key)
            if ev is not None and str(ev).strip() != "":
                return str(ev).strip()
            yv = yaml_service.get(yaml_key) if yaml_service else None
            if isinstance(yv, str) and yv.strip():
                return yv.strip()
            return default

        def _svc_int(env_key: str, yaml_key: str, default: int) -> int:
            ev = os.getenv(env_key)
            if ev is not None and str(ev).strip() != "":
                try:
                    return int(ev)
                except ValueError:
                    return default
            yv = yaml_service.get(yaml_key) if yaml_service else None
            if isinstance(yv, bool):
                return default
            try:
                if yv is not None and str(yv).strip() != "":
                    return int(yv)
            except (TypeError, ValueError):
                pass
            return default

        base_tasks = cls.default_tasks()
        yaml_layer: dict[str, LLMTaskConfig] = {}
        for name, raw in yaml_tasks_raw.items():
            if not isinstance(name, str) or not name.strip():
                continue
            key = name.strip()
            if key not in base_tasks:
                continue
            if not isinstance(raw, dict):
                continue
            yaml_layer[key] = cls._task_from_yaml_dict(raw, base_tasks[key])

        merged_defaults: dict[str, LLMTaskConfig] = {}
        for name, base in base_tasks.items():
            if name in yaml_layer:
                merged_defaults[name] = yaml_layer[name]
            else:
                merged_defaults[name] = base

        tasks = {name: cls._task_from_env(name, task) for name, task in merged_defaults.items()}
        tasks["triplet_or_event_extraction"] = tasks["event_or_triplet_extraction"]

        return cls(
            base_url=_svc_str("LLM_SERVICE_BASE_URL", "base_url", "http://localhost:8000"),
            auth_mode=_svc_str("LLM_SERVICE_AUTH_MODE", "auth_mode", "none").lower(),
            auth_token=auth_token,
            timeout_seconds=_svc_int("LLM_SERVICE_TIMEOUT_SECONDS", "timeout_seconds", 60),
            max_retries=_svc_int("LLM_SERVICE_MAX_RETRIES", "max_retries", 3),
            retry_base_delay_ms=_svc_int("LLM_SERVICE_RETRY_BASE_DELAY_MS", "retry_base_delay_ms", 500),
            retry_max_delay_ms=_svc_int("LLM_SERVICE_RETRY_MAX_DELAY_MS", "retry_max_delay_ms", 5000),
            tasks=tasks,
        )

    def task(self, name: str) -> LLMTaskConfig:
        try:
            return self.tasks[name]
        except KeyError as exc:
            raise KeyError(f"Unknown LLM task config: {name}") from exc
