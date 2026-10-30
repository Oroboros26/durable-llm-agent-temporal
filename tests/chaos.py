"""Chaos test: kill the worker N times mid-run; the task must still finish with 0 duplicate side effects.
Needs a Temporal server on localhost:7233 (`docker compose up -d`). Run: python tests/chaos.py --kills 3 --seed 42
"""
import argparse
import asyncio
import os
import random
import sqlite3
import subprocess
import sys
import tempfile

from temporalio.client import Client

from durable_agent import tools
from durable_agent.models import QUEUE, AgentInput
from durable_agent.workflows import AgentWorkflow


def start_worker(env: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "durable_agent.worker"], env=env)


async def main(kills: int, seed: int) -> None:
    rnd = random.Random(seed)
    tmp = tempfile.mkdtemp()
    env = {**os.environ, "AGENT_DB": f"{tmp}/chaos.db", "FAKE_LLM": "1", "TOOL_DELAY_S": "1.5"}
    os.environ["AGENT_DB"] = env["AGENT_DB"]
    tools.seed()

    client = await Client.connect("localhost:7233")
    wid = f"chaos-{seed}"
    handle = await client.start_workflow(AgentWorkflow.run, AgentInput(task="revenue report"), id=wid, task_queue=QUEUE)

    worker = start_worker(env)
    approved, killed = False, 0
    while True:
        await asyncio.sleep(rnd.uniform(0.5, 2.5))
        if not approved:  # approve as soon as the risky step is waiting
            key = (await handle.query(AgentWorkflow.status))["pending_key"]
            if key:
                await handle.signal(AgentWorkflow.approve, args=[key, True])
                approved = True
        if killed < kills:
            worker.kill()
            worker.wait()
            killed += 1
            print(f"killed worker #{killed}")
            worker = start_worker(env)
        try:
            result = await asyncio.wait_for(asyncio.shield(handle.result()), timeout=1)
            break
        except TimeoutError:
            continue
    worker.kill()

    con = sqlite3.connect(env["AGENT_DB"])
    sent = con.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    attempts = con.execute("SELECT COUNT(*) FROM effect_log").fetchone()[0]
    print(f"result={result!r} kills={killed} emails_sent={sent} send_attempts={attempts}")
    assert result.startswith("done"), "task did not complete"
    assert sent == 1, f"duplicate side effects: {sent} emails"
    print("PASS: completed, 0 duplicate side effects")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kills", type=int, default=3)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    asyncio.run(main(a.kills, a.seed))
