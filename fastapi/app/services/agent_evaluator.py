"""Agent evaluation engine.

Evaluates the LangGraph agent as a black box by sending predefined questions
and measuring task success rate, tool call efficiency, token consumption,
and response latency.

Usage:
    questions = AgentQuestionSetManager.load("evaluation/sample_agent_questions.json")
    evaluator = AgentEvaluator(questions)
    result = await evaluator.run()
    print(result.to_dict())
"""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentEvaluationQuestion:
    """A single test case for the agent.

    Each *expected_* field is optional — when None that dimension is skipped
    during evaluation.  An empty list (e.g. ``expected_tools=[]``) means
    "I expect the agent NOT to call any tools", which is semantically
    different from None ("don't check this dimension").
    """

    id: str
    question: str
    expected_action: Optional[str] = None
    expected_tools: Optional[list[str]] = None
    expected_data_fields: Optional[list[str]] = None
    expected_response_keywords: Optional[list[str]] = None
    description: str = ""


@dataclass
class AgentMetrics:
    """Quantifiable performance data for a single agent invocation."""

    latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls_count: int = 0
    tools_used: list[str] = field(default_factory=list)
    llm_calls_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentEvaluationResult:
    """Aggregate result of evaluating the agent over a question set."""

    per_question: list[dict] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
#  AgentEvaluator
# ═══════════════════════════════════════════════════════════════════════════════

class AgentEvaluator:
    """Evaluates the LangGraph agent as a black box.

    Calls ``agent_graph.ainvoke`` directly (not via HTTP) so internal metrics
    — token usage, tool invocation count, LLM call count — can be extracted
    from the returned LangGraph state.

    Each question runs with a unique ``thread_id`` to prevent cross-
    contamination.
    """

    def __init__(self, questions: list[AgentEvaluationQuestion]):
        self.questions = questions

    # ── public ─────────────────────────────────────────────────────────────

    async def run(self) -> AgentEvaluationResult:
        """Evaluate every question and aggregate metrics."""
        per_question: list[dict] = []

        for q in self.questions:
            pq = await self._evaluate_question(q)
            per_question.append(pq)

        # ── aggregate ──────────────────────────────────────────────────
        n = len(per_question)
        successes = sum(
            1 for pq in per_question if pq["checks"].get("success", False)
        )
        latencies = [pq["metrics"]["latency_ms"] for pq in per_question]
        prompt_toks = [pq["metrics"]["prompt_tokens"] for pq in per_question]
        completion_toks = [pq["metrics"]["completion_tokens"] for pq in per_question]
        total_toks = [pq["metrics"]["total_tokens"] for pq in per_question]
        tool_counts = [pq["metrics"]["tool_calls_count"] for pq in per_question]

        tool_dist: dict[str, int] = {}
        for pq in per_question:
            for tool in pq["metrics"]["tools_used"]:
                tool_dist[tool] = tool_dist.get(tool, 0) + 1

        aggregate = {
            "success_rate": round(successes / n, 4) if n > 0 else 0.0,
            "avg_latency_ms": round(sum(latencies) / n, 2) if n > 0 else 0.0,
            "max_latency_ms": round(max(latencies), 2) if latencies else 0.0,
            "min_latency_ms": round(min(latencies), 2) if latencies else 0.0,
            "avg_prompt_tokens": round(sum(prompt_toks) / n, 1) if n > 0 else 0.0,
            "avg_completion_tokens": round(sum(completion_toks) / n, 1) if n > 0 else 0.0,
            "avg_total_tokens": round(sum(total_toks) / n, 1) if n > 0 else 0.0,
            "avg_tool_calls_per_question": round(sum(tool_counts) / n, 2) if n > 0 else 0.0,
            "tool_usage_distribution": tool_dist,
            "total_questions": n,
        }

        return AgentEvaluationResult(
            per_question=per_question,
            aggregate=aggregate,
            config={
                "agent_model": os.getenv("AGENT_MODEL", "glm-4-flashx-250414"),
                "num_questions": n,
            },
        )

    # ── per-question ──────────────────────────────────────────────────────

    async def _evaluate_question(self, q: AgentEvaluationQuestion) -> dict:
        """Run one question through the agent graph and collect all metrics."""
        from app.agents.graph import agent_graph
        from app.agents.router import SYSTEM_PROMPT_TEMPLATE, _extract_json_payload
        from langchain_core.messages import HumanMessage, SystemMessage

        base_url = os.getenv("AGENT_BASE_APP_URL", "http://127.0.0.1:8000")
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(base_url=base_url)),
            HumanMessage(content=q.question),
        ]

        start = time.perf_counter()
        try:
            result = await agent_graph.ainvoke(
                {"messages": messages},
                config={"configurable": {"thread_id": f"eval-{q.id}"}},
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            all_messages = result["messages"]
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "question_id": q.id,
                "question": q.question,
                "description": q.description,
                "error": str(exc),
                "action": None,
                "response_preview": "",
                "data_keys": [],
                "tools_used": [],
                "metrics": AgentMetrics(latency_ms=round(elapsed_ms, 2)).to_dict(),
                "checks": {"success": False, "error": str(exc)},
            }

        # ── extract metrics from state ─────────────────────────────────
        token_usage = self._extract_token_usage(all_messages)
        tool_count, tools_used = self._count_tool_calls(all_messages)
        llm_calls = self._count_llm_calls(all_messages)

        metrics = AgentMetrics(
            latency_ms=round(elapsed_ms, 2),
            prompt_tokens=token_usage["prompt_tokens"],
            completion_tokens=token_usage["completion_tokens"],
            total_tokens=token_usage["total_tokens"],
            tool_calls_count=tool_count,
            tools_used=tools_used,
            llm_calls_count=llm_calls,
        )

        # ── parse final agent response ─────────────────────────────────
        final_message = all_messages[-1]
        response_content = getattr(final_message, "content", str(final_message))
        final_payload = _extract_json_payload(response_content) or {}

        # ── judge success ──────────────────────────────────────────────
        checks = self._evaluate_success(q, final_payload, tools_used)

        return {
            "question_id": q.id,
            "question": q.question,
            "description": q.description,
            "action": final_payload.get("action"),
            "response_preview": (final_payload.get("response", "") or "")[:500],
            "data_keys": (
                list(final_payload.get("data", {}).keys())
                if isinstance(final_payload.get("data"), dict)
                else []
            ),
            "tools_used": tools_used,
            "metrics": metrics.to_dict(),
            "checks": checks,
        }

    # ── static metrics extractors ──────────────────────────────────────────

    @staticmethod
    def _extract_token_usage(messages: list) -> dict:
        """Sum ``token_usage`` from every AIMessage in the state.

        Returns zeros when the provider does not include usage info
        (graceful degradation).
        """
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        for msg in messages:
            meta = getattr(msg, "response_metadata", None)
            if not isinstance(meta, dict):
                continue
            usage = meta.get("token_usage", {})
            if usage:
                prompt_tokens += usage.get("prompt_tokens", 0)
                completion_tokens += usage.get("completion_tokens", 0)
                total_tokens += usage.get("total_tokens", 0)

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    @staticmethod
    def _count_tool_calls(messages: list) -> tuple[int, list[str]]:
        """Count tool invocations and collect which tools were requested.

        Returns
        -------
        (tool_message_count, sorted_distinct_tool_names)
        """
        from langchain_core.messages import AIMessage, ToolMessage

        tool_message_count = 0
        tools_used: set[str] = set()

        for msg in messages:
            if isinstance(msg, ToolMessage):
                tool_message_count += 1
            if isinstance(msg, AIMessage):
                for tc in getattr(msg, "tool_calls", None) or []:
                    name = tc.get("name", "unknown")
                    if name:
                        tools_used.add(name)

        return tool_message_count, sorted(tools_used)

    @staticmethod
    def _count_llm_calls(messages: list) -> int:
        """Count how many times the LLM was invoked (number of AIMessages)."""
        from langchain_core.messages import AIMessage

        return sum(1 for msg in messages if isinstance(msg, AIMessage))

    # ── success evaluation ─────────────────────────────────────────────────

    @staticmethod
    def _evaluate_success(
        q: AgentEvaluationQuestion,
        final_payload: dict,
        tools_used: list[str],
    ) -> dict:
        """Compare agent output against expected values.

        Returns a dict of per-dimension checks.

        Check semantics
        ---------------
        * **action_match** — exact string equality (e.g. ``"file_info"``).
        * **tools_match** — *subset* when ``expected_tools`` is non-empty:
          every expected tool must appear in the tools the agent used, but
          the agent is allowed to call extra tools (e.g. a fallback search).
          When ``expected_tools`` is an empty list ``[]``, it means "the
          agent must call **no** tools at all" (exact empty-set match).
          When ``None``, this dimension is skipped entirely.
        * **data_fields_match** — expected fields must be a subset of the
          fields actually present in the ``data`` payload.
        * **keywords_match** — every keyword must appear (case‑insensitive)
          somewhere in the ``response`` text.

        ``success`` is True when every checked dimension passes (or when
        nothing was specified — vacuously True).
        """
        checks: dict = {}

        if q.expected_action is not None:
            checks["action_match"] = (
                final_payload.get("action") == q.expected_action
            )

        if q.expected_tools is not None:
            if len(q.expected_tools) == 0:
                # Explicit empty list → must call NO tools at all
                checks["tools_match"] = (len(tools_used) == 0)
            else:
                # Subset check: expected ⊆ actual (agent may use extra tools)
                checks["tools_match"] = (
                    set(q.expected_tools).issubset(set(tools_used))
                )

        if q.expected_data_fields is not None:
            data = final_payload.get("data")
            actual_fields = set(data.keys()) if isinstance(data, dict) else set()
            checks["data_fields_match"] = (
                set(q.expected_data_fields).issubset(actual_fields)
            )

        if q.expected_response_keywords is not None:
            response_text = (final_payload.get("response") or "").lower()
            checks["keywords_match"] = all(
                kw.lower() in response_text
                for kw in q.expected_response_keywords
            )

        checks["success"] = all(checks.values()) if checks else True
        return checks


# ═══════════════════════════════════════════════════════════════════════════════
#  Question-set persistence
# ═══════════════════════════════════════════════════════════════════════════════

class AgentQuestionSetManager:
    """Load / save agent evaluation question sets from JSON."""

    @staticmethod
    def load(path: str) -> list[AgentEvaluationQuestion]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("questions", [])
        return [AgentEvaluationQuestion(**item) for item in items]

    @staticmethod
    def save(questions: list[AgentEvaluationQuestion], path: str):
        data = {"questions": [asdict(q) for q in questions]}
        from pathlib import Path

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
