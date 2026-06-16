# Resume ↔ JD Tailor

A small multi-agent service that compares a resume against a job description,
scores the match, and rewrites the resume's bullets to align with the role —
**without fabricating experience the candidate doesn't have.**

Built with **Google ADK** (Agent Development Kit) + **FastAPI**.

> Portfolio note: this project is a focused way to learn three things at once —
> FastAPI service design, Google ADK, and multi-agent orchestration (parallel +
> sequential composition with typed, schema-enforced hand-offs between agents).

## Architecture

```
SequentialAgent (resume_tailor)
├── ParallelAgent (intake)
│   ├── jd_parser        ← LLM   → state["jd_parsed"]
│   └── resume_parser    ← LLM   → state["resume_parsed"]
├── match_analyzer       ← LLM   → state["analysis"]
└── tailor               ← LLM   → state["tailored"]
```

Four LLM agents composed under two workflow (orchestration) agents. The two
parsers are independent, so they run **concurrently** under a `ParallelAgent`;
the rest of the pipeline is sequential because each step depends on the prior.

## How data flows

The pipeline has **two** inputs (resume + JD). Rather than concatenating them
into one prompt, they are seeded into **session state** at session creation.
Each agent then pulls exactly the slice it needs through `{placeholder}`
templating in its instruction, and writes its result back to a named
`output_key`. The API reads the four structured results out of state when the
run finishes.

```
state at start:  { resume, job_description }
after intake:    { ..., jd_parsed, resume_parsed }
after analyzer:  { ..., analysis }
after tailor:    { ..., tailored }
```

## Design decisions

- **Structured outputs everywhere.** Each parser/analyzer emits enforced JSON
  via ADK's `output_schema` (see `schemas.py`), so routing and analysis run on
  machine-readable data, not free-form text.
- **Per-agent model routing for cost control.** The parsers and analyzer do
  structured extraction and run on the cheaper `gemini-2.5-flash-lite`; only the
  tailoring agent (creative rewriting) uses `gemini-2.5-flash`.
- **No-fabrication guardrail.** The tailoring agent is instructed to rephrase
  only real experience and to surface genuinely missing skills under
  `honest_gaps` instead of inventing them. This is enforced as a hard check in
  the eval.
- **Two inputs via seeded state.** The pipeline has two inputs (resume + JD), so
  they're seeded into session state at session creation and read by each parser
  through `{resume}` / `{job_description}` templating.

## What goes in, what comes out

**Input** (`POST /tailor`, JSON body):

```json
{
  "resume_text": "plain text of your resume",
  "job_description": "plain text of the job description",
  "user_id": "demo-user"
}
```

> The current service takes **plain text** for both fields — not a PDF file and
> not a URL. PDF extraction and JD-from-URL fetching are listed as extensions
> below (and walked through in `BUILD_GUIDE.md`).

**Output**: a single JSON object with four sections —

| Field           | Contents                                                            |
| --------------- | ------------------------------------------------------------------- |
| `jd_parsed`     | title, seniority, required / nice-to-have skills, responsibilities, ATS keywords |
| `resume_parsed` | skills, technologies, verbatim experience bullets, years experience |
| `analysis`      | `match_score` (0–100), per-skill `covered/partial/missing` + evidence, summary |
| `tailored`      | rewritten bullets (original + tailored + rationale), ATS keywords to add, `honest_gaps` |

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # then add your Google AI Studio API key
```

Get a free key at https://aistudio.google.com — the free tier (≈1,000
requests/day) comfortably covers building, demoing, and running the eval.

## Run the API

```bash
uvicorn main:app --reload
```

Open the interactive docs at **http://localhost:8000/docs** (FastAPI gives you
Swagger UI for free — the easiest way to try the endpoint without curl).

```bash
curl -X POST http://localhost:8000/tailor \
  -H "Content-Type: application/json" \
  -d '{
    "resume_text": "Backend engineer. Built REST APIs in Python with FastAPI...",
    "job_description": "Senior Backend Engineer. Required: Python, FastAPI, Kubernetes..."
  }'
```

## Run the eval

```bash
python eval.py
```

Reports skill-match recall on a labeled set and, critically, **fabrication
failures** — the number of times a tailored bullet claimed a skill the
candidate doesn't have. That number must be 0.

## Possible extensions

- **PDF resume upload** — add a `/tailor/upload` endpoint that extracts text
  before the pipeline (great FastAPI `UploadFile` practice). Sketched in
  `BUILD_GUIDE.md`, Phase 5.
- **JD from URL** — fetch + strip a job posting page server-side.
- Swap the LLM skill matcher for embedding-based similarity.
- LLM-as-judge scoring for tailored-bullet quality.
- Persist sessions (swap `InMemorySessionService` for a database-backed one).

## Repo layout

```
resume-tailor/
├── agents.py        # ADK agents + orchestration (the multi-agent core)
├── schemas.py       # Pydantic models used as ADK output_schema
├── main.py          # FastAPI app + run_pipeline()
├── eval.py          # evaluation harness
├── eval_data.py     # labeled (resume, JD) test cases
├── requirements.txt
├── .env.example
├── Makefile         # make run / make eval / make install
├── README.md
├── CLAUDE.md        # project context for Claude Code
└── BUILD_GUIDE.md   # phased, build-it-yourself walkthrough
```
