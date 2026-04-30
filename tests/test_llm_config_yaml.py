from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_llm_task_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("LLM_TASK_"):
            monkeypatch.delenv(key, raising=False)


def test_llm_yaml_overrides_provider_and_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    yaml_path = tmp_path / "custom_llm.yaml"
    yaml_path.write_text(
        """
tasks:
  embeddings:
    provider: groq
    model: test-embed-model
  statement_extraction:
    provider: anthropic
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_CONFIG_PATH", str(yaml_path))

    from temporial_graph_rag.llm.config import LLMServiceConfig

    cfg = LLMServiceConfig.from_env()
    assert cfg.task("embeddings").provider == "groq"
    assert cfg.task("embeddings").model == "test-embed-model"
    assert cfg.task("statement_extraction").provider == "anthropic"
    # Unlisted task stays built-in default
    assert cfg.task("answer_synthesis").provider == "openai"


def test_llm_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    yaml_path = tmp_path / "x.yaml"
    yaml_path.write_text(
        "tasks:\n  embeddings:\n    provider: groq\n    model: from-yaml\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_CONFIG_PATH", str(yaml_path))
    monkeypatch.setenv("LLM_TASK_EMBEDDINGS_PROVIDER", "openai")
    monkeypatch.setenv("LLM_TASK_EMBEDDINGS_MODEL", "from-env")

    from temporial_graph_rag.llm.config import LLMServiceConfig

    cfg = LLMServiceConfig.from_env()
    assert cfg.task("embeddings").provider == "openai"
    assert cfg.task("embeddings").model == "from-env"


def test_triplet_alias_matches_event_task(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    yaml_path = tmp_path / "x.yaml"
    yaml_path.write_text(
        "tasks:\n  event_or_triplet_extraction:\n    provider: groq\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_CONFIG_PATH", str(yaml_path))

    from temporial_graph_rag.llm.config import LLMServiceConfig

    cfg = LLMServiceConfig.from_env()
    t = cfg.task("triplet_or_event_extraction")
    assert t.provider == "groq"
    assert t is cfg.task("event_or_triplet_extraction")
