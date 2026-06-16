"""Labeled (resume, JD) pairs for the eval harness.

Each case carries ground truth:
  - expected_covered : skills the analyzer should mark covered/partial
  - expected_missing : skills genuinely absent -> should be marked 'missing'
  - fabrication_tripwire : a skill clearly NOT in the resume. If it ever shows
    up as a *claim* in the tailored bullets, that's a fabrication failure.
"""

EVAL_CASES = [
    {
        "name": "backend_python",
        "resume": """Priya Nair - Backend Engineer (5 years)

Experience:
- Designed and shipped REST APIs in Python using FastAPI, serving 2M requests/day.
- Built PostgreSQL schemas and optimized slow queries, cutting p95 latency by 40%.
- Implemented CI/CD with GitHub Actions and Docker for containerized deployments.
- Wrote unit and integration tests with pytest, raising coverage to 85%.

Skills: Python, FastAPI, PostgreSQL, Docker, REST, pytest, Git""",
        "job_description": """Senior Backend Engineer

Required:
- Strong Python and experience building REST APIs (FastAPI or Flask)
- Relational database design (PostgreSQL)
- Container orchestration with Kubernetes in production
- Experience writing Go services

Nice to have:
- CI/CD pipelines
- Observability / monitoring""",
        "expected_covered": ["python", "fastapi", "postgresql", "rest apis"],
        "expected_missing": ["kubernetes", "go"],
        "fabrication_tripwire": "kubernetes",
    },
    {
        "name": "fullstack_frontend",
        "resume": """Arjun Rao - Software Engineer (3 years)

Experience:
- Built React + TypeScript dashboards consumed by 500+ internal users.
- Developed Node.js/Express APIs integrating third-party payment providers.
- Created Python ETL scripts moving data into BigQuery for analytics.
- Set up Grafana dashboards for service monitoring.

Skills: JavaScript, TypeScript, React, Node.js, Express, Python, BigQuery, Grafana""",
        "job_description": """Frontend-Leaning Full-Stack Engineer

Required:
- Strong React and TypeScript
- Node.js backend experience
- Familiarity with monitoring/observability tools

Nice to have:
- GraphQL APIs
- AWS Lambda / serverless""",
        "expected_covered": ["react", "typescript", "node.js"],
        "expected_missing": ["graphql", "aws lambda"],
        "fabrication_tripwire": "graphql",
    },
]
