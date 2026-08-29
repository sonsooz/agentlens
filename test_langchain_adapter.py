"""
Verifies the LangChain adapter against real langchain-core primitives
(a fake chain built from Runnable, not a mock of our own callback logic).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "sdk"))

from agentlens import AgentLens, AgentLensConfig
from agentlens.integrations.langchain import AgentLensCallbackHandler
from langchain_core.runnables import RunnableLambda

config = AgentLensConfig(endpoint="http://localhost:8420", project="langchain-test")
lens = AgentLens("lc_agent", run_id="lc-verify-1", config=config)
handler = AgentLensCallbackHandler(lens)


def step_one(x):
    time.sleep(0.1)
    return {"facts": ["fact A", "fact B"]}


def step_two(x):
    time.sleep(0.1)
    if "facts" not in x:
        raise ValueError("missing facts")
    return {"summary": "summary of " + str(x["facts"])}


def step_three_fails(x):
    time.sleep(0.05)
    raise RuntimeError("simulated downstream API failure")


chain = RunnableLambda(step_one, name="gather_facts") | RunnableLambda(step_two, name="summarize")

result = chain.invoke({"query": "test"}, config={"callbacks": [handler], "run_name": "research_chain"})
print("Chain result:", result)

failing_chain = RunnableLambda(step_three_fails, name="flaky_api_call")
try:
    failing_chain.invoke({"query": "test"}, config={"callbacks": [handler]})
except RuntimeError as e:
    print("Expected failure captured:", e)

lens.finish(status="completed")
print("Done — check http://localhost:8420/dashboard for run 'lc-verify-1'")
