> Lightweight observability for multi-agent AI systems — see every decision, tool call, handoff, and failure across your agents, live.

# AgentLens

Lightweight observability for multi-agent AI systems. Drop a few lines into
your agent code and get a live timeline of every decision, tool call,
handoff, and failure — across all the agents in a run.

Built as the MVP for a "flight recorder for AI agents" product: a narrow,
concrete slice of the AI-agent-infrastructure space (see project notes).

## Why this niche

Teams building multi-agent systems (LangChain, CrewAI, AutoGen, custom
orchestration) can get an agent pipeline working, but have almost no
visibility into *why* it failed at 2am in production, or what context
agent B actually received from agent A. This is the "Sentry for agents"
gap — infrastructure, not another agent framework.

## Project layout

```
agentlens/
  sdk/            Python SDK — instrument your agent code with this
    agentlens/
      client.py   AgentLens class: .step(), .handoff(), .error(), .trace_tool()
  backend/        FastAPI server — ingests events, stores in SQLite, serves API
    main.py
  dashboard/      Single-file web dashboard — live timeline view
    index.html
  demo.py         Simulated 2-agent run so you can see it work immediately
```

## Quickstart

```bash
# 1. Install backend deps
cd backend
pip install -r requirements.txt

# 2. Install the SDK (editable, so your agent code can import it)
cd ../sdk
pip install -e .

# 3. Start the backend (serves API + dashboard)
cd ../backend
uvicorn main:app --host 0.0.0.0 --port 8420

# 4. In another terminal, run the demo to generate sample data
cd ..
python demo.py

# 5. Open the dashboard
# http://localhost:8420/dashboard
```

## Instrumenting your own agents

```python
from agentlens import AgentLens, AgentLensConfig

config = AgentLensConfig(endpoint="http://localhost:8420", project="my-app")
lens = AgentLens(agent_name="researcher", run_id="run-42", config=config)

# Time a unit of work and capture input/output
with lens.step("search_web", query=q) as s:
    result = search(q)
    s.output = result

# Decorate an existing tool function
@lens.trace_tool
def call_llm(prompt):
    return model.generate(prompt)

# Record a handoff to another agent
lens.handoff(to_agent="writer", context_summary="5 facts extracted")

# Record an error explicitly (also captured automatically inside .step)
try:
    risky_call()
except Exception as e:
    lens.error(e)

lens.finish(status="completed")
```

Every event is a simple JSON POST to `/events` — the SDK never blocks or
crashes your agent if the backend is unreachable (`fail_silently=True` by
default).

## What's here vs. what's next (roadmap for turning this into a real product)

**Already working (this MVP):**
- Python SDK: steps, tool decorator, handoffs, error capture, timing
- Backend: event ingestion, SQLite storage, query API
- Dashboard: live per-agent timeline, expandable event detail, error/handoff highlighting

**Natural next steps, roughly in priority order:**
1. **Auth + multi-tenant backend** — API keys per project, so this can be a hosted service, not just localhost.
2. **JS/TypeScript SDK** — most agent frameworks in the wild are JS/TS; the Python SDK alone limits your addressable market.
3. **Framework adapters** — auto-instrument LangChain/CrewAI/AutoGen callbacks instead of requiring manual `.step()` calls; this is the biggest lever for adoption since it drops integration time to near zero.
4. **Alerting** — webhook/Slack notification when error rate on a run/project crosses a threshold.
5. **Cost tracking** — capture token usage/cost per step if you tag LLM calls, aggregate per run/agent.
6. **Hosted free tier** — deploy the backend (Railway/Fly.io/Render all have generous free tiers), open the SDK on GitHub/PyPI, and let developers point at your hosted endpoint instead of self-hosting. This is usually the actual growth unlock: self-hosting is friction, "pip install and get a URL" is not.
7. **Open-core model** — keep SDK + single-project backend free/open source; charge for hosted multi-project, retention beyond N days, alerting, and team seats.

## Distribution plan (no ad budget needed)

- Open source the SDK + backend on GitHub under a permissive license.
- Post a "show, don't tell" demo GIF (the timeline populating live) in r/LangChain, r/AI_Agents, Hacker News "Show HN", and the CrewAI/AutoGen Discord servers — developers in these communities are exactly the buyer.
- Write one sharp blog post: "Why your multi-agent pipeline fails silently, and how to see it" — technical, not marketing-toned.
- Once there's real usage (GitHub stars, self-reported production use), that traction is the actual pitch material for accelerators/investors — not the idea alone.
