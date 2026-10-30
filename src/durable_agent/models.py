from dataclasses import dataclass, field

QUEUE = "durable-agent"
MAX_STEPS = 12
CAN_AFTER = 40  # steps per run before continue-as-new (bounds history size)
RISKY = {"send_report_email"}


@dataclass
class AgentInput:
    task: str
    msgs: list[dict] = field(default_factory=list)  # carried across continue-as-new
    step: int = 0
