from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from temporial_graph_rag.graph.store import Neo4jGraphStore
from temporial_graph_rag.llm import LLMClient
from temporial_graph_rag.ontology.loader import Ontology
from temporial_graph_rag.retrieval import prompts
from temporial_graph_rag.retrieval.json_extract import extract_json_object
from temporial_graph_rag.retrieval.tools import RetrievalToolContext, RetrievalTools


@dataclass
class MultiStepRetrievalResult:
    answer: str
    initial_plan: str
    steps: list[dict[str, Any]] = field(default_factory=list)


class MultiStepRetriever:
    """Planner + tool loop patterned after ``temporal_agents.ipynb`` ``MultiStepRetriever`` (sync, HTTP LLM)."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        store: Neo4jGraphStore,
        ontology: Ontology,
        collection_name: str,
        max_steps: int = 10,
    ) -> None:
        self._llm = llm
        self._store = store
        self._ontology = ontology
        self._collection_name = collection_name
        self._max_steps = max(1, min(int(max_steps), 25))
        ctx = RetrievalToolContext(
            store=store,
            llm=llm,
            collection_name=collection_name,
            ontology=ontology,
        )
        self._tools = RetrievalTools(ctx)

    def run(self, user_question: str) -> MultiStepRetrievalResult:
        q = user_question.strip()
        plan_resp = self._llm.complete(
            task_name="retrieval_planner",
            messages=[
                {"role": "system", "content": prompts.PLANNER_SYSTEM},
                {"role": "user", "content": prompts.planner_user_message(user_question=q)},
            ],
        )
        initial_plan = str(plan_resp.get("content", "")).strip()

        system = prompts.executor_system_message(
            collection_name=self._collection_name,
            initial_plan=initial_plan,
        )
        transcript = ""
        steps: list[dict[str, Any]] = []

        for _ in range(self._max_steps):
            user_turn = prompts.executor_user_turn(user_question=q, transcript=transcript)
            resp = self._llm.complete(
                task_name="retrieval_step",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_turn},
                ],
            )
            raw = str(resp.get("content", "")).strip()
            try:
                data = extract_json_object(raw)
            except (json.JSONDecodeError, ValueError) as exc:
                steps.append({"parse_error": str(exc), "raw": raw[:2000]})
                transcript += f"\n[System] Model output was not valid JSON. Error: {exc}\n"
                continue

            action = str(data.get("action", "")).strip().lower()
            if action == "final":
                ans = str(data.get("answer", "")).strip()
                return MultiStepRetrievalResult(answer=ans or "(empty)", initial_plan=initial_plan, steps=steps)

            if action != "tool":
                steps.append({"unexpected_action": action, "data": data})
                transcript += f"\n[System] Expected action 'tool' or 'final', got {action!r}\n"
                continue

            tool_name = str(data.get("tool_name", "")).strip()
            args = data.get("arguments")
            if not isinstance(args, dict):
                args = {}
            out = self._tools.dispatch(tool_name, args)
            steps.append({"tool": tool_name, "arguments": args, "output_chars": len(out)})
            transcript += f"\nTool `{tool_name}` JSON result:\n{out}\n"

        return MultiStepRetrievalResult(
            answer="Stopped after maximum retrieval steps without a final answer.",
            initial_plan=initial_plan,
            steps=steps,
        )
