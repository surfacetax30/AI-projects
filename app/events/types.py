"""OTS Approval Helping Agent — Event type definitions.

All agents communicate through typed events on the asyncio.Queue bus.
Only the Orchestrator is allowed to change task state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


class EventType:
    REPORT_RECEIVED      = "report.received"       # MailGateway → Queue
    REPORT_PARSED        = "report.parsed"         # Parser → Orchestrator
    REPORT_PARSE_FAILED  = "report.parse_failed"   # Parser → Orchestrator
    COMPLETENESS_PASS    = "completeness.pass"     # DataChecker → Orchestrator
    COMPLETENESS_FAIL    = "completeness.fail"     # DataChecker → Orchestrator
    ANOMALY_DETECTED     = "anomaly.detected"      # ReportAgent → Orchestrator
    NO_ANOMALY           = "anomaly.none"          # ReportAgent → Orchestrator
    HUMAN_CONFIRMED      = "human.confirmed"       # PE review → Orchestrator
    HUMAN_CORRECTED      = "human.corrected"       # PE corrected → Orchestrator
    HUMAN_REJECTED       = "human.rejected"        # PE rejected → Orchestrator
    TASK_STATE_CHANGED   = "task.state_changed"    # Orchestrator → Notify
    REWORK_TRIGGERED     = "rework.triggered"      # Orchestrator → Notify
    NOTIFY_SEND          = "notify.send"           # → Notification consumer


@dataclass
class Event:
    type: str
    task_id: str
    source: str                                    # agent name
    payload: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
