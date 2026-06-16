# CLAUDE.md

Project context for working on this repo with Claude Code. Read this before
making changes.

## What this is

A multi-agent **Resume ↔ JD Tailor**: given a resume and a job description (both
plain text), it parses both, scores the fit per-skill, and rewrites resume
bullets to match the role **without fabricating experience**. Stack: **Google
ADK** (Agent Development Kit) for the agents, **FastAPI** for the HTTP service.

The author is building this as a learning project. The learning goals are
FastAPI, Google ADK, and multi-agent orchestration — so prefer changes that keep
the agent composition clear and idiomatic over clever abstractions. When adding
something non-obvious, leave a short comment explaining *why*, matching the
existing docstring style.

## Commands

```bash
# setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add GOOGLE_API_KEY

# run the API (Swagger UI at http://localhost:8000/docs)
uvicorn main:app --reload

# run the eval harness — fabrication failures MUST be 0
python eval.py
```

A `Makefile` wraps these: `make install`, `make run`, `make eval`.

## Architecture (the important part)

```
SequentialAgent (root_agent, name="resume_tailor")
├── ParallelAgent (intake)
│   ├── jd_parser        -> state["jd_parsed"]      (gemini-2.5-flash-lite)
│   └── resume_parser    -> state["resume_parsed"]  (gemini-2.5-flash-lite)
├── match_analyzer       -> state["analysis"]       (gemini-2.5-flash-lite)
└── tailor               -> state["tailored"]       (gemini-2.5-flash)
```

- **agents.py** — all agent + orchestration definitions. The multi-agent core.
- **schemas.py** — Pydantic models wired into each agent as `output_schema` so
  outputs are enforced JSON, not prose.
- **main.py** — FastAPI app, `run_pipeline()`, and the state-seeding logic.
- **eval.py / eval_data.py** — labeled test cases + the harness.

## Key conventions (don't break these)

1. **State-passing, not prompt-stuffing.** The two inputs (`resume`,
   `job_description`) are seeded into session state in `main.py` at session
   creation. Agents read inputs via `{placeholder}` templating in their
   `instruction` and write results via `output_key`. If you add an agent, give
   it an `output_key` and read upstream values with `{...}` placeholders — do
   not concatenate everything into one giant prompt.

2. **`output_key` names are a contract.** `jd_parsed`, `resume_parsed`,
   `analysis`, `tailored` are referenced by downstream agent instructions AND by
   `run_pipeline()` in main.py AND by `eval.py`. Rename in all three places or
   not at all.

3. **Schema fields are a contract too.** `eval.py` reads
   `analysis["matches"][i]["skill"|"status"]` and
   `tailored["tailored_bullets"][i]["tailored"]` and `tailored["honest_gaps"]`.
   Changing these schema field names requires updating the eval.

4. **Model routing is intentional.** Parsers/analyzer use `flash-lite` (cheap,
   structured extraction); only `tailor` uses `flash` (creative rewriting).
   Keep new structured-extraction agents on the lite model.

5. **The no-fabrication rule is the whole point.** The `tailor` agent's
   instruction forbids inventing skills and routes genuinely missing skills to
   `honest_gaps`. The eval's fabrication tripwire enforces this and must stay at
   0. Don't weaken that instruction or that check.

## ParallelAgent caveat (ADK gotcha)

`ParallelAgent` is used here **only because the sub-agent set is known
statically** (always exactly jd_parser + resume_parser, and they're
independent). It is not a general "do these in a loop" tool. Don't reach for it
for dynamic fan-out.

## Gotchas

- **`output_schema` constrains tool use.** In ADK, an agent with an
  `output_schema` is expected to emit only that structured object. Don't also
  give such an agent tools/transfer behavior and expect both to work — keep
  structured-output agents pure.
- **`InMemorySessionService` is ephemeral.** State is lost on restart; that's
  fine for this demo. Persistence is an explicit extension, not a bug.
- **`run_pipeline` reads results from state, not streamed events.** The
  `async for _ in runner.run_async(...): pass` loop intentionally drains events
  and ignores them; the structured results come from `get_session().state`.
- **Env**: requires `GOOGLE_API_KEY` and `GOOGLE_GENAI_USE_VERTEXAI=FALSE` in
  `.env` (AI Studio free tier). The API will fail at call time without a key.

## When adding features

- New endpoint? Add it to `main.py`, reuse `run_pipeline()` where possible.
- New agent? Define it in `agents.py`, add its `output_schema` to `schemas.py`,
  insert it into the right place in `root_agent`'s sequence, and surface its
  `output_key` in `run_pipeline()`'s return dict.
- Touching analysis/tailoring output shape? Update `eval.py` in the same change
  and re-run `python eval.py` to confirm fabrication failures are still 0.
