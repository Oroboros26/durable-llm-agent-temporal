"""Workflow tests on the Temporal time-skipping test server (downloaded on first use, no Docker).

They run the real workflow with the scripted model (FAKE_LLM=1):
  1. approval gate: the email is sent only after the approve signal, and not when denied;
  2. retry after the effect was applied: the email activity fails once after sending, Temporal
     retries it, and the outbox still holds exactly one email.
"""
import asyncio
import sqlite3

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from durable_agent import tools
from durable_agent.activities import llm_call, run_tool
from durable_agent.models import QUEUE, AgentInput
from durable_agent.workflows import AgentWorkflow


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("FAKE_LLM", "1")
    monkeypatch.chdir(tmp_path)  # export_csv writes ./out
    tools.seed()


@activity.defn(name="run_tool")
async def flaky_run_tool(name: str, args: dict, key: str) -> str:
    """Applies the effect, then fails on the first attempt, like a worker dying before it reports."""
    out = await run_tool(name, args, key)
    if name == "send_report_email" and activity.info().attempt == 1:
        raise RuntimeError("worker died after the effect was applied")
    return out


async def _run(approve: bool, tool_activity) -> str:
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(env.client, task_queue=QUEUE, workflows=[AgentWorkflow],
               activities=[llm_call, tool_activity]),
    ):
        handle = await env.client.start_workflow(
            AgentWorkflow.run, AgentInput(task="revenue report"), id="t1", task_queue=QUEUE)
        key = None
        for _ in range(400):  # wait for the risky step to ask for approval
            key = (await handle.query(AgentWorkflow.status))["pending_key"]
            if key:
                break
            await asyncio.sleep(0.05)
        assert key, "workflow never asked for approval"
        await handle.signal(AgentWorkflow.approve, args=[key, approve])
        return await handle.result()


def _outbox() -> tuple[int, list[int]]:
    con = sqlite3.connect(tools._db())
    sent = con.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    applied = [r[0] for r in con.execute("SELECT applied FROM effect_log ORDER BY rowid")]
    con.close()
    return sent, applied


def test_email_is_sent_once_after_approval():
    assert asyncio.run(_run(True, run_tool)).startswith("done")
    assert _outbox() == (1, [1])


def test_denied_email_is_not_sent():
    assert asyncio.run(_run(False, run_tool)).startswith("done")
    assert _outbox() == (0, [])


def test_retry_after_applied_effect_does_not_duplicate():
    assert asyncio.run(_run(True, flaky_run_tool)).startswith("done")
    sent, applied = _outbox()
    assert sent == 1, "the retry sent a duplicate email"
    assert applied == [1, 0], "second attempt must be recorded as a deduplicated no-op"
