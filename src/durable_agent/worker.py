import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from durable_agent.activities import llm_call, run_tool
from durable_agent.models import QUEUE
from durable_agent.workflows import AgentWorkflow


async def main() -> None:
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))
    await Worker(client, task_queue=QUEUE, workflows=[AgentWorkflow], activities=[llm_call, run_tool]).run()


if __name__ == "__main__":
    asyncio.run(main())
