"""
Demo: simulates a 2-agent pipeline (researcher -> writer) with a handoff,
a couple of tool calls, and one deliberate failure — so you can see the
dashboard populate with real events immediately after starting the backend.

Run:
    python demo.py
Then open http://localhost:8420/dashboard in your browser.
"""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "sdk"))

from agentlens import AgentLens, AgentLensConfig

config = AgentLensConfig(endpoint="http://localhost:8420", project="demo")
run_id = f"demo-{random.randint(1000, 9999)}"

researcher = AgentLens("researcher", run_id=run_id, config=config)

with researcher.step("search_web", query="best AI agent frameworks 2026") as s:
    time.sleep(0.3)
    s.output = "Found 12 relevant results"

with researcher.step("extract_facts", source="web_results") as s:
    time.sleep(0.4)
    s.output = "Extracted 5 key facts"

try:
    with researcher.step("call_pricing_api", provider="external") as s:
        time.sleep(0.2)
        raise ConnectionError("pricing API timed out after 3 retries")
except ConnectionError:
    pass  # error already logged by the SDK; pipeline continues below

researcher.handoff("writer", context_summary="5 facts + pricing data (partial, pricing API failed)")

writer = AgentLens("writer", run_id=run_id, config=config)

with writer.step("draft_summary", facts_count=5) as s:
    time.sleep(0.5)
    s.output = "Draft written, 340 words"

with writer.step("polish_tone", style="concise") as s:
    time.sleep(0.3)
    s.output = "Final version ready"

writer.finish(status="completed", output_length=340)

print(f"Demo run '{run_id}' sent. Open http://localhost:8420/dashboard and select it.")
