from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from durable_agent.activities import llm_call, run_tool
    from durable_agent.models import CAN_AFTER, MAX_STEPS, RISKY, AgentInput

LLM_RETRY = RetryPolicy(maximum_attempts=4, initial_interval=timedelta(seconds=1), backoff_coefficient=2.0)
TOOL_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1),
                         non_retryable_error_types=["ValueError"])  # bad SQL won't get better on retry
APPROVAL_TIMEOUT = timedelta(days=2)


@workflow.defn
class AgentWorkflow:
    def __init__(self) -> None:
        self.step = 0
        self.pending: str | None = None
        self.decisions: dict[str, bool] = {}

    @workflow.signal
    def approve(self, key: str, ok: bool) -> None:
        self.decisions[key] = ok

    @workflow.query
    def status(self) -> dict:
        return {"step": self.step, "pending_key": self.pending}

    @workflow.run
    async def run(self, inp: AgentInput) -> str:
        msgs = inp.msgs or [{"role": "user", "content": inp.task}]
        self.step = inp.step
        wid = workflow.info().workflow_id
        while self.step < MAX_STEPS:
            if self.step - inp.step >= CAN_AFTER:
                # Limitation: no history summarisation; add an llm_summarise activity if context grows
                workflow.continue_as_new(AgentInput(inp.task, msgs, self.step))
            self.step += 1
            reply = await workflow.execute_activity(
                llm_call, msgs, start_to_close_timeout=timedelta(seconds=60), retry_policy=LLM_RETRY
            )
            msgs.append({"role": "assistant", "content": reply["content"]})
            uses = [b for b in reply["content"] if b["type"] == "tool_use"]
            if not uses:
                return "".join(b.get("text", "") for b in reply["content"] if b["type"] == "text")
            results = [await self._tool(u, f"{wid}:{self.step}:{i}") for i, u in enumerate(uses)]
            msgs.append({"role": "user", "content": results})
        return "stopped: max steps reached"

    async def _tool(self, use: dict, key: str) -> dict:
        def result(text: str, err: bool = False) -> dict:
            return {"type": "tool_result", "tool_use_id": use["id"], "content": text, "is_error": err}

        if use["name"] in RISKY:
            self.pending = key
            try:  # durable wait: costs nothing while idle, survives worker restarts
                await workflow.wait_condition(lambda: key in self.decisions, timeout=APPROVAL_TIMEOUT)
            except TimeoutError:
                self.pending = None
                return result("approval timed out", True)
            self.pending = None
            if not self.decisions[key]:
                return result("denied by human", True)
        try:
            out = await workflow.execute_activity(
                run_tool, args=[use["name"], use["input"], key],
                start_to_close_timeout=timedelta(seconds=30), retry_policy=TOOL_RETRY,
            )
        except ActivityError as e:
            return result(f"tool failed: {e.cause}", True)
        return result(out)
