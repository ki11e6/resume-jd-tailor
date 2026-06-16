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
so they run on the cheaper Flash-Lite; only the tailoring agent (creative
rewriting) uses the stronger Flash.
"""

from google.adk.agents import LlmAgent, SequentialAgent, ParallelAgent

from schemas import JDRequirements, ResumeProfile, MatchAnalysis, TailoredOutput

PARSER_MODEL = "gemini-2.5-flash-lite"
ANALYZER_MODEL = "gemini-2.5-flash-lite"
TAILOR_MODEL = "gemini-2.5-flash"


jd_parser = LlmAgent(
    name="jd_parser",
    model=PARSER_MODEL,
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
    model=PARSER_MODEL,
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
    model=ANALYZER_MODEL,
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
    model=TAILOR_MODEL,
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

root_agent = SequentialAgent(
    name="resume_tailor",
    sub_agents=[intake, analyzer, tailor],
    description="Parses a resume and JD, analyzes fit, and tailors honestly.",
)
