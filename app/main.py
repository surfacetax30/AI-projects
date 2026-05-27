"""OTS Approval Helping Agent — FastAPI application entry point."""

from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.db.session import engine
from app.db.models import Base  # noqa: F401 — register models
from app.events.bus import event_bus
from app.events.types import EventType, Event
from app.agents.mail_gateway import MailGateway
from app.agents.parser import ReportParser
from app.agents.data_checker import DataChecker

logger = logging.getLogger(__name__)

mail_gateway = MailGateway()
parser = ReportParser()
data_checker = DataChecker()


async def _handle_report_received(event: Event):
    payload = event.payload
    task_id = payload.get("task_id", "")
    logger.info(f"[Pipeline] Received report for task={task_id}")

    gateway_result = await mail_gateway.process(payload)
    if not gateway_result.get("accepted"):
        logger.info(f"[Pipeline] MailGateway rejected: {gateway_result.get('reason')}")
        return

    parse_result = await parser.process({
        "task_id": task_id,
        "part_no": gateway_result.get("part_no", payload.get("part_no", "")),
        "filename": payload.get("filename", "unknown"),
        "storage_path": payload.get("storage_path", ""),
        "report_text": payload.get("report_text", ""),
    })
    logger.info(
        f"[Pipeline] Parser status={parse_result['status']} "
        f"confidence={parse_result.get('parsed', {}).get('overall_confidence', 'N/A')}"
    )

    if parse_result["status"] == "error":
        logger.warning(f"[Pipeline] Parser failed: {parse_result.get('error')}")
        return

    part_type = payload.get("part_type", "金属支架")
    parsed_fields = parse_result.get("parsed", {}).get("confidence_per_field", {})

    check_result = await data_checker.process({
        "task_id": task_id,
        "part_type": part_type,
        "parsed_fields": parsed_fields,
    })
    logger.info(
        f"[Pipeline] DataChecker result={check_result['overall_result']} "
        f"missing={check_result.get('total_missing', 0)}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    event_bus.subscribe(EventType.REPORT_RECEIVED, _handle_report_received)
    await event_bus.start()
    logger.info("[OTS-AHA] Event bus started. Pipeline: mail_gateway → parser → data_checker")
    yield
    await event_bus.stop()
    logger.info("[OTS-AHA] Shutdown complete.")


app = FastAPI(title="OTS Approval Helping Agent", version="0.1.0", lifespan=lifespan)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(_static_dir, "index.html"))


from app.api.parts import router as parts_router
from app.api.tasks import router as tasks_router
from app.api.tasks import webhook_router

app.include_router(parts_router)
app.include_router(tasks_router)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "OTS-AHA"}