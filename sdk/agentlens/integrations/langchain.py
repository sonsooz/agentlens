"""
AgentLens x LangChain — automatic instrumentation.

Instead of manually wrapping every call in `lens.step(...)`, attach this
callback handler once and every chain/tool/LLM call in your LangChain app
is captured automatically.

Usage:
    from agentlens import AgentLens, AgentLensConfig
    from agentlens.integrations.langchain import AgentLensCallbackHandler

    lens = AgentLens("researcher", config=AgentLensConfig(project="my-app"))
    handler = AgentLensCallbackHandler(lens)

    chain.invoke({"input": "..."}, config={"callbacks": [handler]})
    # or globally: llm = ChatOpenAI(callbacks=[handler])

Requires: langchain-core (only imported lazily, so the base SDK has no
hard dependency on LangChain).
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
from uuid import UUID

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "AgentLensCallbackHandler requires langchain-core. "
        "Install it with: pip install langchain-core"
    ) from e


def _short(obj: Any, limit: int = 500) -> str:
    try:
        s = str(obj)
    except Exception:
        s = repr(obj)
    return s if len(s) <= limit else s[:limit] + "…"


class AgentLensCallbackHandler(BaseCallbackHandler):
    """
    Drop-in LangChain callback handler. Every chain, tool, and LLM call
    becomes a step in the AgentLens timeline automatically — no manual
    `.step()` calls needed anywhere in your chain code.
    """

    def __init__(self, lens):
        self.lens = lens
        self._starts: Dict[UUID, Dict[str, Any]] = {}

    # ---------- internal helpers ----------

    def _begin(self, run_id: UUID, name: str, input_data: Any) -> None:
        # Use the full run_id as the step key/id — LangChain assigns a fresh
        # UUID per call, but truncating it (e.g. to 8 hex chars) creates real
        # collisions once you have more than a handful of calls in a run,
        # which silently corrupts timing/pairing between unrelated steps.
        self._starts[run_id] = {"name": name, "t0": time.time()}
        self.lens._emit(
            {
                "type": "step_start",
                "step_id": str(run_id),
                "data": {"name": name, "input": _short(input_data)},
            }
        )

    def _end(self, run_id: UUID, output: Any) -> None:
        started = self._starts.pop(run_id, None)
        if not started:
            return
        self.lens._emit(
            {
                "type": "step_end",
                "step_id": str(run_id),
                "data": {
                    "name": started["name"],
                    "duration_ms": int((time.time() - started["t0"]) * 1000),
                    "output": _short(output),
                },
            }
        )

    def _fail(self, run_id: UUID, error: BaseException) -> None:
        started = self._starts.pop(run_id, None)
        name = started["name"] if started else "unknown"
        duration = int((time.time() - started["t0"]) * 1000) if started else None
        self.lens._emit(
            {
                "type": "step_error",
                "step_id": str(run_id),
                "data": {
                    "name": name,
                    "duration_ms": duration,
                    "message": str(error),
                    "exc_type": type(error).__name__,
                },
            }
        )

    @staticmethod
    def _resolve_name(serialized, kwargs, fallback: str) -> str:
        # Modern langchain-core (Runnable-based chains) passes the human
        # given name via kwargs['name']; serialized is often None. Older
        # style integrations still populate serialized['name']/['id'].
        return (
            kwargs.get("name")
            or (serialized or {}).get("name")
            or (serialized or {}).get("id", [fallback])[-1]
            or fallback
        )

    # ---------- LangChain hooks: chains ----------

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs):
        name = self._resolve_name(serialized, kwargs, "chain")
        self._begin(run_id, f"chain:{name}", inputs)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id, outputs)

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._fail(run_id, error)

    # ---------- LangChain hooks: tools ----------

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        name = self._resolve_name(serialized, kwargs, "tool")
        self._begin(run_id, f"tool:{name}", input_str)

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id, output)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._fail(run_id, error)

    # ---------- LangChain hooks: LLM calls ----------

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        name = self._resolve_name(serialized, kwargs, "llm")
        self._begin(run_id, f"llm:{name}", prompts)

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        name = self._resolve_name(serialized, kwargs, "chat_model")
        self._begin(run_id, f"llm:{name}", messages)

    def on_llm_end(self, response, *, run_id, **kwargs):
        self._end(run_id, response)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._fail(run_id, error)

    # ---------- LangChain hooks: agent actions ----------

    def on_agent_action(self, action, *, run_id, **kwargs):
        self.lens._emit(
            {
                "type": "step_end",
                "step_id": str(run_id)[:8] + "-act",
                "data": {"name": f"agent_action:{getattr(action, 'tool', '?')}", "output": _short(action)},
            }
        )

    def on_agent_finish(self, finish, *, run_id, **kwargs):
        self.lens._emit(
            {
                "type": "step_end",
                "step_id": str(run_id)[:8] + "-fin",
                "data": {"name": "agent_finish", "output": _short(finish)},
            }
        )
