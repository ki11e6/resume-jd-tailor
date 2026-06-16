"""Agent definitions.

Composition:

    SequentialAgent (resume_tailor)
    ├── ParallelAgent (intake)
    │   ├── jd_parser        -> state["jd_parsed"]
    │   └── resume_parser    -> state["resume_parsed"]
    ├── match_analyzer       -> state["analysis"]
    └── tailor               -> state["tailored"]

The two parsers are independent, so they run concurrently under a
ParallelAgent. This is a legitimate use of ParallelAgent because the set of
sub-agents is known statically. Each agent reads its inputs from session state
via {placeholder} templating and writes its output to `output_key`.

Model routing is deliberate: the parsers and analyzer do structured extraction,
so they run on the cheaper "lite" model; only the tailoring agent (creative
rewriting) uses the stronger model.

Provider routing: the same composition is built per provider via
`build_root_agent(provider)`. Gemini is the default; Groq (reached through ADK's
LiteLLM wrapper) is a free-tier-friendly alternative whose `gpt-oss` models
support strict structured output, which the `output_schema` contract requires.
"""

from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent

from schemas import JDRequirements, ResumeProfile, MatchAnalysis, TailoredOutput

# Gemini (default) — cheap lite model for extraction, stronger model for the rewrite.
GEMINI_LITE = "gemini-2.5-flash-lite"
GEMINI_STRONG = "gemini-2.5-flash"

# Groq equivalents (via LiteLLM). gpt-oss supports strict structured output, so the
# enforced-JSON `output_schema` contract holds. Same routing idea: 20b for
# extraction, 120b for the creative no-fabrication rewrite.
GROQ_LITE = "groq/openai/gpt-oss-20b"
GROQ_STRONG = "groq/openai/gpt-oss-120b"

SUPPORTED_PROVIDERS = ("gemini", "groq")


def _model_for(provider: str, role: str):
    """Return the model for a given provider + role ('lite' or 'strong').

    Gemini uses a plain model-name string; Groq is wrapped in ADK's LiteLlm. The
    LiteLlm import is local so a missing litellm dependency never breaks the
    Gemini-only path at import time.
    """
    if provider == "gemini":
        return GEMINI_LITE if role == "lite" else GEMINI_STRONG
    if provider == "groq":
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(model=GROQ_LITE if role == "lite" else GROQ_STRONG)
    raise ValueError(f"unknown provider: {provider!r} (expected one of {SUPPORTED_PROVIDERS})")


def build_root_agent(provider: str = "gemini") -> SequentialAgent:
    """Build the full agent tree for one provider. Agents are cheap config
    objects; the caller caches the result per provider (see main.py)."""
    lite = _model_for(provider, "lite")
    strong = _model_for(provider, "strong")

    jd_parser = LlmAgent(
        name="jd_parser",
        model=lite,
        description="Extracts structured requirements from a job description.",
        instruction=(
            "Extract the key requirements from this job description.\n\n"
            "JOB DESCRIPTION:\n{job_description}\n\n"
            "Identify the role title, seniority level, required skills, "
            "nice-to-have skills, core responsibilities, and ATS keywords."
        ),
        output_schema=JDRequirements,
        output_key="jd_parsed",
    )

    resume_parser = LlmAgent(
        name="resume_parser",
        model=lite,
        description="Extracts a structured profile from a resume.",
        instruction=(
            "Extract a structured profile from this resume.\n\n"
            "RESUME:\n{resume}\n\n"
            "List the candidate's skills, technologies, individual experience "
            "bullet points (quoted verbatim), and approximate total years of "
            "experience."
        ),
        output_schema=ResumeProfile,
        output_key="resume_parsed",
    )

    intake = ParallelAgent(
        name="intake",
        sub_agents=[jd_parser, resume_parser],
        description="Parses the job description and resume concurrently.",
    )

    analyzer = LlmAgent(
        name="match_analyzer",
        model=lite,
        description="Compares the resume profile against the JD requirements.",
        instruction=(
            "Compare the candidate against the job's requirements.\n\n"
            "JOB REQUIREMENTS:\n{jd_parsed}\n\n"
            "CANDIDATE PROFILE:\n{resume_parsed}\n\n"
            "For each required and nice-to-have skill, decide whether it is "
            "'covered' (clear evidence in the resume), 'partial' (related but weak "
            "evidence), or 'missing' (no evidence). Cite the resume evidence for "
            "covered/partial items. Give an overall match_score (0-100) and a "
            "short summary. Base every judgment ONLY on what is actually in the "
            "candidate profile."
        ),
        output_schema=MatchAnalysis,
        output_key="analysis",
    )

    tailor = LlmAgent(
        name="tailor",
        model=strong,
        description="Rewrites resume bullets to align with the JD, without fabricating.",
        instruction=(
            "Help tailor this resume to the job.\n\n"
            "ORIGINAL RESUME:\n{resume}\n\n"
            "JOB REQUIREMENTS:\n{jd_parsed}\n\n"
            "MATCH ANALYSIS:\n{analysis}\n\n"
            "Rewrite relevant existing resume bullets to emphasize the language and "
            "keywords the job asks for.\n\n"
            "CRITICAL RULES:\n"
            "1. NEVER invent skills, tools, employers, or experience that are not "
            "in the original resume. Rephrasing real experience is allowed; "
            "fabrication is not.\n"
            "2. Only rewrite bullets that map to skills marked 'covered' or "
            "'partial' in the analysis.\n"
            "3. Put genuinely 'missing' skills into honest_gaps so the candidate "
            "can address them truthfully. Do NOT bury or fake them.\n"
            "4. Suggest ATS keywords to add ONLY where they reflect real experience."
        ),
        output_schema=TailoredOutput,
        output_key="tailored",
    )

    return SequentialAgent(
        name="resume_tailor",
        sub_agents=[intake, analyzer, tailor],
        description="Parses a resume and JD, analyzes fit, and tailors honestly.",
    )


# Default tree (Gemini), kept as a module-level export for backwards compatibility.
root_agent = build_root_agent("gemini")
