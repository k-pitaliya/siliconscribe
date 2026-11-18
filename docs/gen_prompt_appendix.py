#!/usr/bin/env python3
"""Write the live LLM prompts into the report/guide appendix folders.

The appendix listings used to be hand-copied and went stale as the prompts changed. Run this after
editing backend/llm_service.py:   python3 docs/gen_prompt_appendix.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
import llm_service  # noqa: E402

PROMPTS = {
    "prompt_intent.txt": llm_service.INTENT_PARSER_PROMPT,
    "prompt_rtl.txt": llm_service.RTL_GENERATOR_PROMPT,
    "prompt_testbench.txt": llm_service.TB_GENERATOR_PROMPT,
    "prompt_fix.txt": llm_service.FIX_PROMPT,
}
# The LaTeX listing font has no glyphs for these; keep the text readable and plain ASCII.
ASCII = {"—": "--", "–": "-", "→": "->", "≥": ">=", "≤": "<=", "‘": "'",
         "’": "'", "“": '"', "”": '"', "…": "...", "×": "x", "≠": "!="}
TARGETS = [HERE / "appendix", HERE / "EC486_Report_CHARUSAT_Template" / "appendix"]


def to_ascii(text: str) -> str:
    for src, dst in ASCII.items():
        text = text.replace(src, dst)
    bad = sorted({c for c in text if ord(c) > 127})
    if bad:
        raise SystemExit(f"non-ASCII characters left in a prompt: {bad}")
    return text


for target in TARGETS:
    target.mkdir(parents=True, exist_ok=True)
    for name, body in PROMPTS.items():
        (target / name).write_text(to_ascii(body).rstrip("\n") + "\n")
        print("wrote", (target / name).relative_to(HERE.parent))
