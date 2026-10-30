"""CLI: start <id> <task> | status <id> | approve <id> <key> [--deny]"""
import argparse
import asyncio
import os

from temporalio.client import Client

from durable_agent.models import QUEUE, AgentInput
from durable_agent.workflows import AgentWorkflow


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["start", "status", "approve"])
    p.add_argument("wid")
    p.add_argument("arg", nargs="?")
    p.add_argument("--deny", action="store_true")
    a = p.parse_args()
    c = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    if a.cmd == "start":
        h = await c.start_workflow(AgentWorkflow.run, AgentInput(task=a.arg), id=a.wid, task_queue=QUEUE)
        print("started", h.id)
    elif a.cmd == "status":
        print(await c.get_workflow_handle(a.wid).query(AgentWorkflow.status))
    else:
        await c.get_workflow_handle(a.wid).signal(AgentWorkflow.approve, args=[a.arg, not a.deny])
        print("signalled")


if __name__ == "__main__":
    asyncio.run(main())
