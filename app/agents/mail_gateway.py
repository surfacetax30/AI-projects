"""OTS Approval Helping Agent — Mail Gateway Agent (MVP: rule-based + webhook)."""

import re
import asyncio
from typing import Optional

from app.agents.base import BaseAgent
from app.events.types import EventType, Event


class MailGateway(BaseAgent):
    name = "mail_gateway"

    VALID_SENDERS = [
        "vendor1@example.com",
        "vendor2@supplier.cn",
        "lab@testing.org",
    ]
    VALID_SUBJECT_KEYWORDS = ["OTS", "认可", "测试报告"]
    VALID_ATTACHMENT_EXTS = [".pdf", ".docx", ".xlsx", ".csv", ".zip"]
    PART_NO_PATTERN = re.compile(r"OTS-\d{4}-\d{3}", re.IGNORECASE)

    def __init__(self):
        # Inbound queue used by webhook endpoint.
        self._inbound: asyncio.Queue = asyncio.Queue()

    @property
    def inbound_queue(self) -> asyncio.Queue:
        return self._inbound

    def _subject_matches(self, subject: str) -> bool:
        if not subject:
            return False
        return any(kw in subject for kw in self.VALID_SUBJECT_KEYWORDS)

    def _attachment_valid(self, filename: str) -> bool:
        lowered = filename.lower()
        return any(lowered.endswith(ext) for ext in self.VALID_ATTACHMENT_EXTS)

    def _should_accept(
        self,
        sender: str,
        subject: str,
        attachments: list[str],
    ) -> bool:
        if sender not in self.VALID_SENDERS:
            return False
        if not self._subject_matches(subject):
            return False
        if attachments and not all(self._attachment_valid(a) for a in attachments):
            return False
        return True

    def _extract_part_no(self, subject: str) -> Optional[str]:
        match = self.PART_NO_PATTERN.search(subject)
        return match.group(0).upper() if match else None

    async def process(self, payload: dict) -> dict:
        sender = payload.get("mail_from", "")
        subject = payload.get("mail_subject", "")
        attachments = payload.get("attachments", [])

        if not self._should_accept(sender, subject, attachments):
            return {"accepted": False, "reason": "filter_rejected"}

        part_no = self._extract_part_no(subject)
        task_id = payload.get("task_id", "")

        return {
            "accepted": True,
            "part_no": part_no,
            "task_id": task_id,
            "attachments": attachments,
        }

    def publish_event(self, event: Event):
        pass