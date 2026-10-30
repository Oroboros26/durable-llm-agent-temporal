import asyncio
import os

import anthropic
from temporalio import activity

from durable_agent import tools
from durable_agent.models import RISKY  # noqa: F401  (re-exported for the workflow)

MODEL = "claude-sonnet-5-5"
SYSTEM = "You are a sales analyst. Use the tools. Email the report only after exporting it."


def _fake_llm(messages: list[dict]) -> list[dict]:
    """Scripted plan so chaos tests are free and reproducible. Turn = count of assistant messages."""
    sql = "SELECT region, SUM(amount) FROM sales GROUP BY region"
    plan = [
        ("describe_schema", {}),
        ("run_sql", {"sql": sql}),
        ("export_csv", {"sql": sql, "filename": "revenue.csv"}),
        ("send_report_email", {"to": "finance@example.com", "subject": "Revenue by region", "body": "See export."}),
    ]
    turn = sum(m["role"] == "assistant" for m in messages)
    if turn >= len(plan):
        return [{"type": "text", "text": "done: report exported and emailed"}]
    name, args = plan[turn]
    return [{"type": "tool_use", "id": f"fake-{turn}", "name": name, "input": args}]


@activity.defn
async def llm_call(messages: list[dict]) -> dict:
    if os.environ.get("FAKE_LLM"):
        return {"content": _fake_llm(messages)}
    r = await anthropic.AsyncAnthropic().messages.create(
        model=MODEL, max_tokens=1024, system=SYSTEM, tools=tools.TOOLS, messages=messages
    )
    return {"content": [b.model_dump(exclude_none=True) for b in r.content]}


@activity.defn
async def run_tool(name: str, args: dict, key: str) -> str:
    delay = float(os.environ.get("TOOL_DELAY_S", "0"))  # widens the kill window for chaos tests
    await asyncio.sleep(delay)
    if name == "describe_schema":
        out = await asyncio.to_thread(tools.describe_schema)
    elif name == "run_sql":
        out = await asyncio.to_thread(tools.run_sql, args["sql"])
    elif name == "export_csv":
        out = await asyncio.to_thread(tools.export_csv, args["sql"], args["filename"], key)
    elif name == "send_report_email":
        out = await asyncio.to_thread(tools.send_report_email, args["to"], args["subject"], args["body"], key)
    else:
        raise ValueError(f"unknown tool {name}")
    await asyncio.sleep(delay)  # a kill here = effect applied but result never reported: the retry must dedupe
    return out
