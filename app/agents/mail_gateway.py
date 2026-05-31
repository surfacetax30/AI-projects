"""OTS Approval Helping Agent — Mail Gateway Agent (daily batch: rule engine + LLM classification)."""

import fnmatch
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import yaml

from app.agents.base import BaseAgent
from app.services.llm import llm
from app.services.sp_loader import load_sp

logger = logging.getLogger(__name__)

_PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PART_NO_PATTERN = re.compile(r"OTS-\d{4}-\d{3}", re.IGNORECASE)
_PLAIN_PART_NO = re.compile(r"\b\d{8,}\b")


def _extract_part_no(text: str) -> Optional[str]:
    m = PART_NO_PATTERN.search(text)
    if m:
        return m.group(0).upper()
    m2 = _PLAIN_PART_NO.search(text)
    if m2:
        return m2.group(0)
    return None


class MailGateway(BaseAgent):
    name = "mail_gateway"

    def __init__(self):
        self._system_prompt = load_sp("mail_gateway")
        self._rules = self._load_rules()

    # ------------------------------------------------------------------
    # 规则加载
    # ------------------------------------------------------------------
    def _load_rules(self) -> dict:
        rules_path = os.path.join(_PROJ, "config", "mail_rules.yaml")
        if not os.path.exists(rules_path):
            logger.warning(f"[MailGateway] rules file not found: {rules_path}, using defaults")
            return _default_rules()
        with open(rules_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or _default_rules()

    # ------------------------------------------------------------------
    # 规则引擎（Layer 1）
    # ------------------------------------------------------------------
    def _rule_engine_classify(self, mails: list[dict]) -> list[dict]:
        """对所有邮件执行规则引擎判定，返回带 rule_status 的列表。

        可能值：auto_accepted / auto_rejected / to_llm
        """
        wl = self._rules.get("whitelist", {})
        bl = self._rules.get("blacklist", {})
        results = []

        for m in mails:
            sender = m.get("mail_from", "")
            subject = m.get("mail_subject", "")
            attachments = m.get("attachments", [])

            # --- 黑名单检查 ---
            if any(fnmatch.fnmatch(sender.lower(), p.lower()) for p in bl.get("sender_patterns", [])):
                results.append({**m, "rule_status": "auto_rejected", "rule_reason": "blacklist_sender"})
                continue

            exclude_kw = bl.get("subject_exclude_keywords", [])
            if any(kw in subject for kw in exclude_kw):
                results.append({**m, "rule_status": "auto_rejected", "rule_reason": "blacklist_subject"})
                continue

            # --- 白名单检查 ---
            sender_ok = sender in wl.get("senders", [])
            subject_ok = any(kw in subject for kw in wl.get("subject_keywords", []))
            exts = wl.get("attachment_exts", [])
            att_ok = all(
                any(f.lower().endswith(e) for e in exts)
                for f in attachments
            ) if attachments else False

            if sender_ok and subject_ok and att_ok:
                results.append({**m, "rule_status": "auto_accepted", "rule_reason": "whitelist_full_match"})
            elif sender_ok and subject_ok and not attachments:
                results.append({**m, "rule_status": "to_llm", "rule_reason": "whitelist_no_attachment"})
            elif sender_ok and not subject_ok:
                results.append({**m, "rule_status": "to_llm", "rule_reason": "known_sender_unclear_subject"})
            elif not sender_ok and subject_ok:
                results.append({**m, "rule_status": "to_llm", "rule_reason": "unknown_sender_report_subject"})
            else:
                results.append({**m, "rule_status": "to_llm", "rule_reason": "no_rule_match"})

        return results

    # ------------------------------------------------------------------
    # LLM 分类（Layer 2）
    # ------------------------------------------------------------------
    async def _llm_classify(self, mails: list[dict]) -> list[dict]:
        """调用 DeepSeek V4 批量分类邮件。

        返回的 dict 中添加 llm_classification / llm_part_no / llm_confidence / llm_reason。
        """
        if not mails:
            return []

        payload = []
        for i, m in enumerate(mails):
            payload.append({
                "mail_index": i,
                "mail_from": m.get("mail_from", ""),
                "mail_subject": m.get("mail_subject", ""),
                "mail_body_preview": (m.get("mail_body_preview", "") or "")[:300],
                "attachments": m.get("attachments", []),
            })

        user_msg = json.dumps(payload, ensure_ascii=False)

        try:
            raw = await llm.chat(
                system_prompt=self._system_prompt,
                user_message=user_msg,
                temperature=0.1,
            )
        except Exception as e:
            logger.error(f"[MailGateway] LLM classify failed: {e}")
            return [{**m, "llm_status": "pending_human", "llm_reason": f"LLM error: {e}"} for m in mails]

        # 解析 LLM 返回
        parsed = self._parse_json_block(raw)
        if parsed is None:
            logger.warning("[MailGateway] LLM returned non-JSON, all → pending_human")
            return [{**m, "llm_status": "pending_human", "llm_reason": "LLM returned non-JSON"} for m in mails]

        results = []
        for i, m in enumerate(mails):
            llm_result = parsed[i] if i < len(parsed) else {}
            classification = llm_result.get("classification", "不确定")
            confidence = llm_result.get("confidence", 0.0)

            if classification == "不确定" or confidence < 0.60:
                final = "pending_human"
            elif classification in ("OTS报告提交",):
                final = "auto_accepted"
            else:
                final = "auto_rejected"

            results.append({
                **m,
                "llm_status": final,
                "llm_classification": classification,
                "llm_part_no": llm_result.get("part_no"),
                "llm_confidence": confidence,
                "llm_reason": llm_result.get("reason", ""),
            })

        return results

    def _parse_json_block(self, text: str) -> Optional[list]:
        """从 LLM 输出中提取 JSON 数组。"""
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # 每日批处理主入口
    # ------------------------------------------------------------------
    async def batch_process(self, mails: list[dict]) -> dict:
        """每日全量过滤主入口。

        Args:
            mails: 邮件列表，每封包含 mail_from / mail_subject / mail_body_preview / attachments

        Returns:
            batch_report: {batch_id, total, auto_accepted, auto_rejected, pending_human, results}
        """
        batch_id = uuid.uuid4().hex[:8]
        total = len(mails)

        if total == 0:
            return {
                "batch_id": batch_id, "total": 0,
                "auto_accepted": 0, "auto_rejected": 0, "pending_human": 0,
                "results": [],
            }

        # Step 1: 规则引擎
        rule_results = self._rule_engine_classify(mails)

        # Step 2: LLM 分类（仅 to_llm）
        to_llm = [m for m in rule_results if m["rule_status"] == "to_llm"]
        llm_results = await self._llm_classify(to_llm)

        # Step 3: 合并结果
        final_results = []
        llm_idx = 0
        for r in rule_results:
            if r["rule_status"] == "auto_accepted":
                r.update({
                    "final_status": "auto_accepted",
                    "classification": "OTS报告提交",
                    "confidence": 0.95,
                    "reason": r.get("rule_reason", "whitelist"),
                    "classified_by": "rule_engine",
                    "part_no": _extract_part_no(r.get("mail_subject", "")),
                })
            elif r["rule_status"] == "auto_rejected":
                r.update({
                    "final_status": "auto_rejected",
                    "classification": "非业务邮件",
                    "confidence": 0.95,
                    "reason": r.get("rule_reason", "blacklist"),
                    "classified_by": "rule_engine",
                    "part_no": None,
                })
            else:  # to_llm
                llm_r = llm_results[llm_idx] if llm_idx < len(llm_results) else {}
                llm_idx += 1
                final_status = llm_r.get("llm_status", "pending_human")
                r.update({
                    "final_status": final_status,
                    "classification": llm_r.get("llm_classification", "不确定"),
                    "confidence": llm_r.get("llm_confidence", 0.0),
                    "reason": llm_r.get("llm_reason", llm_r.get("llm_status", "")),
                    "classified_by": "llm",
                    "part_no": llm_r.get("llm_part_no") or _extract_part_no(r.get("mail_subject", "")),
                })

            final_results.append(r)

        auto_accepted = sum(1 for r in final_results if r["final_status"] == "auto_accepted")
        auto_rejected = sum(1 for r in final_results if r["final_status"] == "auto_rejected")
        pending_human = sum(1 for r in final_results if r["final_status"] == "pending_human")

        return {
            "batch_id": batch_id,
            "total": total,
            "auto_accepted": auto_accepted,
            "auto_rejected": auto_rejected,
            "pending_human": pending_human,
            "results": final_results,
        }

    # ------------------------------------------------------------------
    # 兼容旧接口（保留给 Pipeline 和 webhook 的向后兼容，实际已废弃）
    # ------------------------------------------------------------------
    async def process(self, payload: dict) -> dict:
        """向后兼容的 process 方法。新代码应使用 batch_process。

        此方法会直接接受所有邮件（不做过滤），因为过滤已前置到 batch_process。
        """
        sender = payload.get("mail_from", "")
        subject = payload.get("mail_subject", "")
        attachments = payload.get("attachments", [])

        return {
            "accepted": True,
            "part_no": payload.get("part_no", "") or _extract_part_no(subject),
            "task_id": payload.get("task_id", ""),
            "attachments": attachments,
            "mail_from": sender,
            "mail_subject": subject,
            "note": "filtering bypassed in process(), use batch_process() instead",
        }


def _default_rules() -> dict:
    return {
        "whitelist": {
            "senders": ["vendor1@example.com", "vendor2@supplier.cn", "lab@testing.org"],
            "subject_keywords": ["OTS", "认可", "测试报告", "PPAP", "交样"],
            "attachment_exts": [".pdf", ".docx", ".xlsx", ".csv", ".zip"],
        },
        "blacklist": {
            "subject_exclude_keywords": ["团建", "工资条", "会议邀请", "Newsletter"],
            "sender_patterns": ["noreply@*", "marketing@*"],
        },
        "batch": {"max_mails_per_batch": 50, "llm_timeout_seconds": 60},
    }


# 全局单例
mail_gateway = MailGateway()
