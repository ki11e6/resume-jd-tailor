"""FastAPI service.

The pipeline takes two inputs (resume + JD), so instead of cramming both into
one user message we seed them into session state at session creation. Each
parser then reads its slice via {resume} / {job_description} templating. After
the run we read the structured results back out of state.
"""

import json
import uuid
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents import root_agent
from pdf_utils import extract_resume_text

load_dotenv()
APP_NAME = "resume_tailor"

app = FastAPI(title="Resume <-> JD Tailor")
session_service = InMemorySessionService()
runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)


class TailorRequest(BaseModel):
    resume_text: str
    job_description: str
    user_id: str = "demo-user"


def _as_dict(value: Any) -> Any:
    """output_schema values land in state as dicts, but parse defensively."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def run_pipeline(resume_text: str, jd_text: str, user_id: str = "demo-user") -> dict:
    session_id = str(uuid.uuid4())
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={"job_description": jd_text, "resume": resume_text},
    )

    trigger = types.Content(role="user", parts=[types.Part(text="Analyze and tailor.")])
    async for _ in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=trigger
    ):
        pass  # results are read from state, not the streamed events

    session = await session_service.get_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    state = session.state
    return {
        "jd_parsed": _as_dict(state.get("jd_parsed")),
        "resume_parsed": _as_dict(state.get("resume_parsed")),
        "analysis": _as_dict(state.get("analysis")),
        "tailored": _as_dict(state.get("tailored")),
    }


@app.post("/tailor")
async def tailor(req: TailorRequest):
    return await run_pipeline(req.resume_text, req.job_description, req.user_id)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — mirrors the client-side cap


@app.post("/tailor/upload")
async def tailor_upload(
    resume_pdf: UploadFile = File(...),
    job_description: str = Form(...),
    user_id: str = Form("demo-user"),
):
    """Thin adapter for the web UI: extract text from an uploaded PDF, then run
    the exact same pipeline as /tailor. The JSON /tailor contract stays untouched
    (eval.py depends on it); this route just handles the PDF -> text step."""
    # Size cap before reading so a huge/zip-bomb upload can't exhaust memory (the
    # client cap is only a hint — a direct POST bypasses it).
    if resume_pdf.size is not None and resume_pdf.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="That PDF is too large (max 10 MB). Try a shorter, text-based resume.",
        )
    data = await resume_pdf.read()
    # Sniff the PDF magic bytes instead of trusting the client-sent content-type —
    # browsers/curl often send application/octet-stream for a real .pdf.
    if not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=415,
            detail="That doesn't look like a PDF. Upload a PDF, or paste your resume text instead.",
        )
    try:
        resume_text = extract_resume_text(data)
    except ValueError as exc:
        # Reject before any LLM call — protects the no-fabrication guarantee.
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return await run_pipeline(resume_text, job_description, user_id)


@app.get("/health")
def health():
    return {"status": "ok"}


# Mounted LAST so the static page at "/" never shadows the API routes above
# (/tailor, /tailor/upload, /health) or the auto-generated /docs.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
