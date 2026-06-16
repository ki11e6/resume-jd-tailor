# Build Guide — Resume ↔ JD Tailor

A phased, build-it-yourself walkthrough. Your goal isn't to copy files; it's to
**understand FastAPI, Google ADK, and multi-agent orchestration** by adding one
concept at a time. Each phase has:

- **Concept** — the one idea this phase teaches.
- **Build** — what to create.
- **Verify** — how to know it works.
- **Claude Code prompt** — paste this into Claude Code to do (or pair on) the phase.

> Tip: do Phases 1–6 in order. Each leaves you with something runnable. Don't
> skip the "Verify" step — that's where the learning sticks.

---

## Phase 0 — Setup (15 min)

**Concept:** project scaffolding, virtual environments, secrets via `.env`.

**Build:**
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install google-adk fastapi "uvicorn[standard]" python-dotenv pydantic typing_extensions
pip freeze > requirements.txt   # or use the provided requirements.txt
cp .env.example .env
```
Get a free Google AI Studio key at https://aistudio.google.com and put it in
`.env` as `GOOGLE_API_KEY`. Keep `GOOGLE_GENAI_USE_VERTEXAI=FALSE`.

**Verify:** `python -c "import google.adk, fastapi; print('ok')"` prints `ok`.

**Claude Code prompt:**
> Set up a Python project for a FastAPI + Google ADK app. Create a `.venv`,
> a `requirements.txt` with google-adk, fastapi, uvicorn[standard],
> python-dotenv, pydantic, typing_extensions, a `.gitignore` that ignores
> `.env` and `__pycache__`, and a `.env.example` containing
> `GOOGLE_GENAI_USE_VERTEXAI=FALSE` and `GOOGLE_API_KEY=your_api_key_here`.

---

## Phase 1 — A bare FastAPI service (20 min)

**Concept:** FastAPI basics — app object, a GET route, request models, the
auto-generated Swagger docs at `/docs`. (No agents yet.)

**Build:** a `main.py` with a `/health` GET returning `{"status": "ok"}` and a
`/tailor` POST that, for now, just echoes back its input. Define the request
body as a Pydantic model:

```python
class TailorRequest(BaseModel):
    resume_text: str
    job_description: str
    user_id: str = "demo-user"
```

**Verify:** `uvicorn main:app --reload`, open http://localhost:8000/docs, and
try both endpoints from the Swagger UI. Notice FastAPI validates the JSON body
against `TailorRequest` for free.

**Claude Code prompt:**
> Create `main.py`: a FastAPI app titled "Resume <-> JD Tailor" with a GET
> `/health` returning `{"status": "ok"}` and a POST `/tailor` that takes a
> Pydantic `TailorRequest` (resume_text: str, job_description: str,
> user_id: str = "demo-user") and, for now, echoes the request back as JSON.
> Show me how to run it and where the Swagger docs are.

**What you learned:** how a FastAPI app is wired, Pydantic request validation,
and that `/docs` is your free test client.

---

## Phase 2 — Typed outputs with Pydantic schemas (20 min)

**Concept:** ADK can force an LLM to return JSON matching a Pydantic model
(`output_schema`). Designing those models well is half the battle in a
multi-agent system — they're the contracts between agents.

**Build:** create `schemas.py` with four models:
- `JDRequirements` — title, seniority, required_skills, nice_to_have_skills,
  responsibilities, ats_keywords.
- `ResumeProfile` — skills, technologies, experience_bullets (verbatim),
  years_experience (optional float).
- `MatchAnalysis` — match_score (0–100), matches (list of `SkillMatch` with
  skill / status `covered|partial|missing` / evidence), summary.
- `TailoredOutput` — tailored_bullets (original/tailored/rationale),
  ats_keywords_to_add, honest_gaps.

Use `Field(description=...)` to coach the model, and `Literal[...]` for the
status enum. (See the provided `schemas.py` for the exact shape.)

**Verify:** `python -c "from schemas import MatchAnalysis; print(MatchAnalysis.model_json_schema())"`
prints a JSON schema. That schema is literally what the LLM will be told to fill.

**Claude Code prompt:**
> Create `schemas.py` with Pydantic models: JDRequirements, ResumeProfile,
> SkillMatch (status is a Literal of "covered"/"partial"/"missing"),
> MatchAnalysis (match_score int constrained 0–100), TailoredBullet, and
> TailoredOutput. Add `Field(description=...)` hints where an LLM filling these
> would benefit. These will be used as ADK `output_schema`.

**What you learned:** schema-as-contract thinking; constraining LLM output to
typed JSON instead of parsing prose.

---

## Phase 3 — Your first ADK agent (30 min)

**Concept:** an ADK `LlmAgent` — `instruction`, `model`, `output_schema`,
`output_key`. How `{placeholder}` templating pulls values from session state
into the instruction.

**Build:** in `agents.py`, create just `resume_parser`: an `LlmAgent` on
`gemini-2.5-flash-lite`, instruction reads `RESUME:\n{resume}`, `output_schema`
is `ResumeProfile`, `output_key` is `resume_parsed`.

Then in `main.py`, wire a minimal `run_pipeline()` that:
1. Creates a session with `InMemorySessionService`, seeding
   `state={"resume": resume_text, "job_description": jd_text}`.
2. Runs it via `Runner(...).run_async(...)`, draining events.
3. Reads `state["resume_parsed"]` back out.

**Verify:** POST a resume to `/tailor` and confirm `resume_parsed` comes back as
structured JSON (skills, bullets, etc.).

**Claude Code prompt:**
> In `agents.py`, create a single ADK `LlmAgent` called `resume_parser` on
> model "gemini-2.5-flash-lite" whose instruction extracts a structured profile
> from `{resume}`, with `output_schema=ResumeProfile` and
> `output_key="resume_parsed"`. Then update `main.py`'s `run_pipeline` to seed
> `resume` and `job_description` into session state via InMemorySessionService,
> run the agent with a Runner, and return `state["resume_parsed"]`. Explain how
> the `{resume}` placeholder gets filled from state.

**What you learned:** the anatomy of an ADK agent and the seed-state →
template → output_key data flow that the whole project is built on.

---

## Phase 4 — Compose agents: parallel + sequential (45 min)

**Concept:** orchestration agents. `ParallelAgent` runs independent agents
concurrently; `SequentialAgent` chains dependent steps. This is the multi-agent
heart of the project.

**Build:** add the remaining agents to `agents.py`:
- `jd_parser` (mirror of resume_parser, reads `{job_description}`, →
  `jd_parsed`).
- `intake = ParallelAgent(sub_agents=[jd_parser, resume_parser])` — the two
  parsers are independent, so run them concurrently.
- `match_analyzer` — reads `{jd_parsed}` and `{resume_parsed}`, →
  `analysis` (`MatchAnalysis`). Instruction: judge each skill
  covered/partial/missing **based only on the candidate profile**.
- `tailor` — reads `{resume}`, `{jd_parsed}`, `{analysis}`, → `tailored`
  (`TailoredOutput`), on the stronger `gemini-2.5-flash`. Instruction includes
  the **no-fabrication rules** (rephrase real experience only; missing skills go
  to `honest_gaps`).
- `root_agent = SequentialAgent(sub_agents=[intake, analyzer, tailor])`.

Update `run_pipeline()` to return all four state keys.

**Verify:** POST a real resume + JD. You should get `jd_parsed`,
`resume_parsed`, `analysis` (with a score and per-skill statuses), and
`tailored` (rewritten bullets + honest_gaps).

**Claude Code prompt:**
> Extend `agents.py` into the full pipeline: add `jd_parser` (parallel sibling
> of resume_parser reading `{job_description}` -> `jd_parsed`), wrap both in a
> `ParallelAgent` called `intake`, add `match_analyzer` (reads `{jd_parsed}` and
> `{resume_parsed}`, output_schema MatchAnalysis, output_key "analysis",
> flash-lite) and `tailor` (reads `{resume}`, `{jd_parsed}`, `{analysis}`,
> output_schema TailoredOutput, output_key "tailored", model
> "gemini-2.5-flash", with strict no-fabrication instructions routing missing
> skills to honest_gaps). Compose them as a `SequentialAgent` `root_agent` =
> [intake, analyzer, tailor]. Update `run_pipeline` to return all four results.
> Explain why intake is parallel but the rest is sequential.

**What you learned:** the core multi-agent pattern — concurrent independent
work, then a dependency chain — and how typed state hand-offs let agents
collaborate without sharing prose.

---

## Phase 5 — Evaluate it like an engineer (30 min)

**Concept:** you can't improve what you don't measure. Build a tiny eval harness
with ground-truth labels. The standout metric here is a **fabrication
tripwire**: a skill the candidate clearly lacks must never appear as a *claim*
in tailored output.

**Build:** `eval_data.py` (2+ labeled cases with `expected_covered`,
`expected_missing`, `fabrication_tripwire`) and `eval.py` that runs each case
through `run_pipeline`, computes covered/missing recall, and counts fabrication
failures (which must be 0). See the provided files for a working version.

**Verify:** `python eval.py` prints a summary with
`Fabrication failures: 0   (MUST be 0)`.

**Claude Code prompt:**
> Create `eval_data.py` with 2 labeled (resume, JD) cases, each with
> `expected_covered`, `expected_missing`, and a `fabrication_tripwire` skill the
> resume lacks. Then create `eval.py` that runs each case through
> `run_pipeline`, measures how often the analyzer labels skills correctly
> (covered/partial vs missing, with substring-tolerant matching), and counts
> "fabrication failures" — any time the tripwire skill appears in a tailored
> bullet. Print a summary; the fabrication count must be 0.

**What you learned:** lightweight LLM eval design, and encoding a safety
property (no fabrication) as an automated, non-negotiable check.

---

## Phase 6 (optional) — PDF upload, the FastAPI way (45 min)

**Concept:** real FastAPI file handling with `UploadFile`, and keeping the
agent pipeline unchanged by extracting text *before* it.

**Build:** add `pypdf` to requirements. Add an endpoint:

```python
from fastapi import UploadFile, File, Form
from pypdf import PdfReader
import io

@app.post("/tailor/upload")
async def tailor_upload(
    resume_pdf: UploadFile = File(...),
    job_description: str = Form(...),
    user_id: str = Form("demo-user"),
):
    raw = await resume_pdf.read()
    reader = PdfReader(io.BytesIO(raw))
    resume_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return await run_pipeline(resume_text, job_description, user_id)
```

**Verify:** in `/docs`, the new endpoint shows a file picker; upload a resume
PDF + paste a JD and confirm you get the same four-section response.

**Claude Code prompt:**
> Add a `/tailor/upload` endpoint to `main.py` that accepts a resume PDF via
> FastAPI `UploadFile` plus a `job_description` form field, extracts text with
> pypdf, and feeds it into the existing `run_pipeline` unchanged. Add `pypdf` to
> requirements.txt. Don't modify the agents — extraction happens before the
> pipeline.

**What you learned:** multipart/form-data uploads in FastAPI, and the design
instinct to adapt inputs at the edge so your core pipeline stays simple.

---

## Where to go next

- **Persistence:** swap `InMemorySessionService` for a database-backed session
  service so runs survive restarts.
- **Embeddings:** replace LLM skill-matching with embedding similarity and
  compare eval numbers — a great before/after to show in a portfolio writeup.
- **LLM-as-judge:** add an agent that scores tailored-bullet quality, and track
  that score in the eval over time.
- **Streaming:** surface ADK events to the client instead of draining them, to
  show progress per agent.

## Portfolio framing (for your README / resume)

When you write this up, lead with the *design decisions*, not the feature list:
parallel-then-sequential orchestration, schema-enforced hand-offs between
agents, per-agent model routing for cost, and a safety property (no
fabrication) enforced by an automated eval. Those are the things that signal you
understand multi-agent systems, not just that you called an LLM.
