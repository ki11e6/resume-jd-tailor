"""Evaluation harness.

Measures two things:
  1. Skill-match recall  - does the analyzer label covered/missing skills right?
  2. Fabrication failures - does the tailored output ever *claim* a skill the
     candidate doesn't have? This must be 0.

Run:  python eval.py
"""

import asyncio
import sys

from main import run_pipeline
from eval_data import EVAL_CASES


def _norm(s: str) -> str:
    return s.strip().lower()


async def evaluate(provider: str = "gemini") -> None:
    print(f"Running eval on provider: {provider}")
    covered_hits = covered_total = 0
    missing_hits = missing_total = 0
    fabrication_failures = 0

    for case in EVAL_CASES:
        print(f"\n--- {case['name']} ---")
        result = await run_pipeline(
            case["resume"], case["job_description"], "eval", provider=provider
        )
        analysis = result.get("analysis") or {}
        tailored = result.get("tailored") or {}

        status_by_skill = {
            _norm(m["skill"]): m["status"] for m in analysis.get("matches", [])
        }

        def lookup(skill: str) -> str:
            # tolerate substring matches like "rest apis" vs "rest"
            key = _norm(skill)
            if key in status_by_skill:
                return status_by_skill[key]
            for s, st in status_by_skill.items():
                if key in s or s in key:
                    return st
            return "unknown"

        for skill in case["expected_covered"]:
            covered_total += 1
            if lookup(skill) in ("covered", "partial"):
                covered_hits += 1
            else:
                print(f"  [miss] expected covered: '{skill}' -> {lookup(skill)}")

        for skill in case["expected_missing"]:
            missing_total += 1
            if lookup(skill) == "missing":
                missing_hits += 1
            else:
                print(f"  [miss] expected missing: '{skill}' -> {lookup(skill)}")

        # --- fabrication tripwire ---
        trip = _norm(case["fabrication_tripwire"])
        claimed = " ".join(
            b.get("tailored", "") for b in tailored.get("tailored_bullets", [])
        )
        gaps = " ".join(_norm(g) for g in tailored.get("honest_gaps", []))

        if trip in _norm(claimed):
            fabrication_failures += 1
            print(f"  [FABRICATION] '{trip}' claimed in a tailored bullet!")
        elif trip not in gaps:
            print(f"  [warn] '{trip}' not surfaced in honest_gaps")
        else:
            print(f"  [ok] '{trip}' correctly flagged as an honest gap")

    print("\n==================== SUMMARY ====================")
    print(f"Covered recall : {covered_hits}/{covered_total}")
    print(f"Missing recall : {missing_hits}/{missing_total}")
    print(f"Fabrication failures: {fabrication_failures}   (MUST be 0)")
    print("================================================")


if __name__ == "__main__":
    # Usage: python eval.py [gemini|groq]   (default: gemini)
    provider = sys.argv[1] if len(sys.argv) > 1 else "gemini"
    asyncio.run(evaluate(provider))
