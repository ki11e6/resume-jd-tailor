"""FastAPI service.

The pipeline takes two inputs (resume + JD), so instead of cramming both into
one user message we seed them into session state at session creation. Each
parser then reads its slice via {resume} / {job_description} templating. After
the run we read the structured results back out of state.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents import SUPPORTED_PROVIDERS, build_root_agent
from pdf_utils import extract_resume_text

load_dotenv()
APP_NAME = "resume_tailor"

app = FastAPI(title="Resume <-> JD Tailor")
session_service = InMemorySessionService()

# One Runner per provider, built lazily and cached. All share the single,
# provider-agnostic session service, so run_pipeline's seeding logic is unchanged.
_runners: dict[str, Runner] = {}
PROVIDER_LABELS = {"gemini": "Google Gemini", "groq": "Groq"}


def _runner_for(provider: str) -> Runner:
    if provider not in _runners:
        _runners[provider] = Runner(
            agent=build_root_agent(provider),
            app_name=APP_NAME,
            session_service=session_service,
        )
    return _runners[provider]


class TailorRequest(BaseModel):
    resume_text: str
    job_description: str
    user_id: str = "demo-user"
    # "auto" tries Gemini then falls back to Groq if rate-limited.
    provider: Literal["auto", "gemini", "groq"] = "auto"


def _as_dict(value: Any) -> Any:
    """output_schema values land in state as dicts, but parse defensively."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


async def run_pipeline(
    resume_text: str, jd_text: str, user_id: str = "demo-user", provider: str = "gemini"
) -> dict:
    runner = _runner_for(provider)
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


def _exc_text(exc: BaseException | None, depth: int = 0) -> str:
    """Flatten an exception tree into one string. The rate-limit error surfaces
    inside a BaseExceptionGroup (ParallelAgent runs the parsers in a TaskGroup)
    and is also chained via __cause__/__context__, so str(exc) alone misses it."""
    if exc is None or depth > 6:
        return ""
    parts = [str(exc)]
    for sub in getattr(exc, "exceptions", None) or ():
        parts.append(_exc_text(sub, depth + 1))
    parts.append(_exc_text(getattr(exc, "__cause__", None), depth + 1))
    parts.append(_exc_text(getattr(exc, "__context__", None), depth + 1))
    return "\n".join(p for p in parts if p)


def _rate_limit_info(exc: Exception) -> dict | None:
    """If `exc` is a model rate-limit/quota error, build a 429 payload telling the
    user when to retry. Returns None for any other error (so it stays a real 500).

    Two shapes matter: a short per-minute throttle (retry in seconds, taken from
    the API's retryDelay) vs the daily free-tier quota, which only resets at
    midnight US Pacific — surfacing the API's tiny retryDelay there would be a lie.
    """
    text = _exc_text(exc)
    low = text.lower()
    markers = ("resource_exhausted", "quota", "rate limit", "rate_limit", "ratelimit", "too many requests")
    if not any(m in low for m in markers) and "429" not in text:
        return None

    now = datetime.now(timezone.utc)
    is_daily = "perday" in low.replace("_", "").replace(" ", "")

    if is_daily:
        try:
            pacific = ZoneInfo("America/Los_Angeles")
            tomorrow = (now.astimezone(pacific) + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ready = tomorrow.astimezone(timezone.utc)
        except Exception:
            ready = now + timedelta(hours=1)
        message = (
            "The AI model's free-tier daily quota is used up. This demo's key "
            "resets at midnight US Pacific — try again after that, or run it "
            "locally with your own API key."
        )
        scope = "daily"
    else:
        match = re.search(r"retrydelay['\"]?\s*[:=]\s*['\"]?(\d+)", low) or re.search(
            r"retry in (\d+)", low
        )
        ready = now + timedelta(seconds=int(match.group(1)) if match else 60)
        message = "The AI model is briefly rate-limited. Hang tight — you can retry shortly."
        scope = "short"

    seconds = max(1, int((ready - now).total_seconds()))
    return {
        "retry_after_seconds": seconds,
        "detail": {
            "error": "rate_limited",
            "scope": scope,
            "message": message,
            "retry_after_seconds": seconds,
            "ready_at": ready.isoformat().replace("+00:00", "Z"),
        },
    }


def _provider_order(provider: str) -> list[str]:
    if provider == "auto":
        return ["gemini", "groq"]
    if provider in SUPPORTED_PROVIDERS:
        return [provider]
    raise HTTPException(status_code=422, detail=f"Unknown provider: {provider!r}")


async def _tailor(resume_text: str, jd_text: str, user_id: str, provider: str) -> dict:
    """Run the pipeline on the chosen provider. In 'auto', transparently fall back
    to the next provider when one is rate-limited. If every attempted provider is
    rate-limited, return a 429 whose detail names any untried alternate, so the UI
    can offer a one-tap switch ('Use Groq now'). Real (non-rate-limit) errors are
    never masked by a fallback."""
    order = _provider_order(provider)
    last_info = None
    for index, name in enumerate(order):
        try:
            result = await run_pipeline(resume_text, jd_text, user_id, provider=name)
            result["provider_used"] = name
            result["fell_back"] = index > 0
            return result
        except HTTPException:
            raise
        except Exception as exc:
            info = _rate_limit_info(exc)
            if info is None:
                raise
            last_info = info

    untried = [p for p in SUPPORTED_PROVIDERS if p not in order]
    detail = dict(last_info["detail"])
    detail["alternate"] = untried[0] if untried else None
    detail["alternate_label"] = PROVIDER_LABELS.get(untried[0]) if untried else None
    raise HTTPException(
        status_code=429,
        detail=detail,
        headers={"Retry-After": str(last_info["retry_after_seconds"])},
    )


@app.post("/tailor")
async def tailor(req: TailorRequest):
    return await _tailor(req.resume_text, req.job_description, req.user_id, req.provider)


MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB — mirrors the client-side cap


@app.post("/tailor/upload")
async def tailor_upload(
    resume_pdf: UploadFile = File(...),
    job_description: str = Form(...),
    user_id: str = Form("demo-user"),
    provider: str = Form("auto"),
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

    return await _tailor(resume_text, job_description, user_id, provider)


@app.get("/health")
def health():
    return {"status": "ok"}


# Mounted LAST so the static page at "/" never shadows the API routes above
# (/tailor, /tailor/upload, /health) or the auto-generated /docs.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
