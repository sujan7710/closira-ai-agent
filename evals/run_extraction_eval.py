"""Lead extraction eval: raw answers (rules mode) vs LLM extraction, against the real model.

Each case starts a conversation with one lead field pending, sends one message
through the full agent, and compares the lead fields that end up stored
(after validation) with the expected ones. A case passes only if every expected
field is right AND nothing else was filled in.

Usage:
    python evals/run_extraction_eval.py
Writes evals/extraction_results.md.
"""

import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import chatbot  # noqa: E402
import classifier  # noqa: E402
import extractor  # noqa: E402
from business import get_business  # noqa: E402
from conversation import ConversationState  # noqa: E402
from run_routing_eval import with_retries  # noqa: E402

CASES = json.loads((ROOT / "evals" / "extraction_cases.json").read_text(encoding="utf-8"))
FILLER = "(given earlier)"


def matches(expected, got):
    if got is None:
        return False
    if isinstance(expected, dict):
        return expected["contains"].lower() in got.lower()
    return expected.lower() == got.lower()


def run_mode(mode):
    os.environ["ROUTER_MODE"] = mode
    results = []
    for i, case in enumerate(CASES):
        state = ConversationState(f"x-{mode}-{i}", business=get_business(case["business"]))
        state.start_lead_at(case["pending"], filler=FILLER)
        reply = chatbot.get_response(state, case["text"])
        got = {k: v for k, v in state.lead.items() if v != FILLER}
        expected = case["expect"]
        ok = set(got) == set(expected) and all(matches(expected[k], got[k]) for k in expected)
        results.append({**case, "got": got, "ok": ok, "route": reply.route})
        print(f"[{mode}] {'PASS' if ok else 'FAIL'}  {case['text'][:55]!r} -> {got}", flush=True)
    return results


def fmt(v):
    return v["contains"] + "…" if isinstance(v, dict) else v


def main():
    logging.basicConfig(level=logging.ERROR)
    chatbot.answer_from_sop = with_retries(chatbot.answer_from_sop)
    classifier.classify = with_retries(classifier.classify)
    extractor.extract = with_retries(extractor.extract)

    all_results = {mode: run_mode(mode) for mode in ("rules", "llm")}

    lines = ["# Lead extraction eval", "",
             f"Cases: {len(CASES)} (both businesses). A case passes only if every expected field is stored "
             "correctly after validation and no other field is filled.", "",
             "| Mode | Cases correct | Multi-field cases | Correctly left empty |", "|---|---|---|---|"]
    for mode, res in all_results.items():
        n, ok = len(res), sum(r["ok"] for r in res)
        multi = [r for r in res if len(r["expect"]) > 1]
        empty = [r for r in res if not r["expect"]]
        lines.append(f"| {mode} | **{ok}/{n} ({ok / n:.0%})** | {sum(r['ok'] for r in multi)}/{len(multi)} | "
                     f"{sum(r['ok'] for r in empty)}/{len(empty)} |")
    for mode, res in all_results.items():
        lines += ["", f"## {mode}: failures", ""]
        fails = [r for r in res if not r["ok"]]
        if not fails:
            lines.append("None.")
            continue
        lines += ["| Message | Expected | Stored |", "|---|---|---|"]
        for r in fails:
            exp = ", ".join(f"{k}={fmt(v)}" for k, v in r["expect"].items()) or "(nothing)"
            got = ", ".join(f"{k}={v}" for k, v in r["got"].items()) or "(nothing)"
            lines.append(f"| {r['text']} | {exp} | {got} |")

    md = "\n".join(lines) + "\n"
    (ROOT / "evals" / "extraction_results.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
