"""
AgentLens SDK — instrumentation client.

Sends structured events (decisions, tool calls, errors, handoffs) from your
agent code to a running AgentLens backend, so they show up live in the
dashboard as a timeline per agent / per run.
"""

from __future__ import annotations

import functools
import os
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests


def _default_endpoint() -> str:
    return os.environ.get("AGENTLENS_ENDPOINT", "http://localhost:8420")


def _default_project() -> str:
    return os.environ.get("AGENTLENS_PROJECT", "default")


@dataclass
class AgentLensConfig:
    # Reads AGENTLENS_ENDPOINT / AGENTLENS_PROJECT from the environment at
    # construction time if you don't pass explicit values — so
    # `export AGENTLENS_ENDPOINT=...` (or `$env:AGENTLENS_ENDPOINT = ...`
    # on PowerShell) actually takes effect without editing code.
    endpoint: str = field(default_factory=_default_endpoint)
    project: str = field(default_factory=_default_project)
    timeout: float = 2.0
    # If True, network errors instrumenting your app never raise —
    # observability must never crash the thing it's observing.
    fail_silently: bool = True


class AgentLens:
    """
    One AgentLens instance = one connection to a backend.
    Create it once per process and reuse it.

        lens = AgentLens(agent_name="researcher", run_id="run-123")

        with lens.step("search_web", input={"query": q}) as step:
            result = search(q)
            step.output = result

        @lens.trace_tool
        def call_llm(prompt): ...
    """

    def __init__(
        self,
        agent_name: str,
        run_id: Optional[str] = None,
        config: Optional[AgentLensConfig] = None,
    ):
        self.agent_name = agent_name
        self.run_id = run_id or str(uuid.uuid4())[:8]
        self.config = config or AgentLensConfig()
        self._session = requests.Session()
        self._emit_lifecycle("run_start")

    # ---------- low level ----------

    def _emit(self, payload: dict) -> None:
        payload.setdefault("project", self.config.project)
        payload.setdefault("agent", self.agent_name)
        payload.setdefault("run_id", self.run_id)
        payload.setdefault("ts", time.time())
        try:
            self._session.post(
                f"{self.config.endpoint}/events",
                json=payload,
                timeout=self.config.timeout,
            )
        except Exception:
            if not self.config.fail_silently:
                raise

    def _emit_lifecycle(self, event_type: str, **extra) -> None:
        self._emit({"type": event_type, **extra})

    # ---------- public API ----------

    def event(self, event_type: str, **data) -> None:
        """Emit a freeform event, e.g. lens.event('decision', reason='...')."""
        self._emit({"type": event_type, "data": data})

    def error(self, exc: BaseException, **context) -> None:
        self._emit(
            {
                "type": "error",
                "data": {
                    "message": str(exc),
                    "exc_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                    **context,
                },
            }
        )

    def handoff(self, to_agent: str, context_summary: str = "", **data) -> None:
        """Record that this agent is passing control/context to another agent."""
        self._emit(
            {
                "type": "handoff",
                "data": {"to_agent": to_agent, "context_summary": context_summary, **data},
            }
        )

    @contextmanager
    def step(self, name: str, **input_data):
        """
        Context manager for one unit of work (a tool call, a reasoning step,
        an LLM call). Automatically times it and records success/failure.

            with lens.step("call_llm", prompt=prompt) as s:
                s.output = model.generate(prompt)
        """
        step_id = str(uuid.uuid4())[:8]
        holder = _StepHandle()
        start = time.time()
        self._emit(
            {
                "type": "step_start",
                "step_id": step_id,
                "data": {"name": name, "input": input_data},
            }
        )
        try:
            yield holder
        except Exception as exc:
            self._emit(
                {
                    "type": "step_error",
                    "step_id": step_id,
                    "data": {
                        "name": name,
                        "duration_ms": int((time.time() - start) * 1000),
                        "message": str(exc),
                        "exc_type": type(exc).__name__,
                        "traceback": traceback.format_exc(),
                    },
                }
            )
            raise
        else:
            self._emit(
                {
                    "type": "step_end",
                    "step_id": step_id,
                    "data": {
                        "name": name,
                        "duration_ms": int((time.time() - start) * 1000),
                        "output": holder.output,
                    },
                }
            )

    def trace_tool(self, fn: Callable) -> Callable:
        """Decorator version of `step` for plain functions/tool calls."""

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with self.step(fn.__name__, args=repr(args)[:500], kwargs=repr(kwargs)[:500]) as s:
                result = fn(*args, **kwargs)
                s.output = repr(result)[:1000]
                return result

        return wrapper

    def finish(self, status: str = "completed", **data) -> None:
        self._emit_lifecycle("run_end", data={"status": status, **data})


@dataclass
class _StepHandle:
    output: Any = None
