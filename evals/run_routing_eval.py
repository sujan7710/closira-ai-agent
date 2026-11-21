"""End-to-end routing eval: keyword rules vs LLM classifier, against the real model.

Each case is a single customer message (optionally with a lead question pending).
The outcome is what the agent actually did, e.g. "answered", "sop_gap",
"escalated:medical", "lead_answer". Both routers use the same answering LLM,
so the comparison isolates the routing decision.

Usage:
    python evals/run_routing_eval.py                 # rules and llm
    python evals/run_routing_eval.py --modes llm     # just one
Writes a markdown report to evals/results.md.
"""

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import chatbot  # noqa: E402
import classifier  # noqa: E402
from conversation import ConversationState  # noqa: E402

CASES = json.loads((ROOT / "evals" / "routing_cases.json").read_text(encoding="utf-8"))


class EvalError(Exception):
    pass


def with_retries(fn, attempts=6):
    """Retry rate-limited calls so a 429 never silently turns into a fallback route."""
    def wrapper(*args, **kwargs):
        for attempt in range(attempts):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if attempt == attempts - 1:
                    raise EvalError(f"{type(exc).__name__}: {exc}") from exc
                time.sleep(min(2 ** attempt * 2, 30))
    return wrapper


def outcome(reply):
    return f"escalated:{reply.category}" if reply.escalated else reply.route


def run_mode(mode):
    os.environ["ROUTER_MODE"] = mode
    results = []
    for i, case in enumerate(CASES):
        state = ConversationState(session_id=f"eval-{mode}-{i}")
        if "pending" in case:
            state.start_lead_at(case["pending"])
        start = time.perf_counter()
        reply = chatbot.get_response(state, case["text"])
        elapsed = time.perf_counter() - start
        got = outcome(reply)
        results.append({**case, "got": got, "ok": got == case["expect"],
                        "source": reply.source, "confidence": reply.confidence, "seconds": elapsed})
        print(f"[{mode}] {'PASS' if got == case['expect'] else 'FAIL'}  {case['text'][:60]!r} -> {got}", flush=True)
    return results


def report(all_results):
    lines = ["# Routing eval results", "",
             f"Cases: {len(CASES)} · model: `{os.getenv('GROQ_MODEL', 'openai/gpt-oss-120b')}` · "
             f"classifier: `{os.getenv('GROQ_CLASSIFIER_MODEL', 'openai/gpt-oss-20b')}` · "
             f"confidence threshold: {classifier.CONFIDENCE_THRESHOLD}", "",
             "| Router | Accuracy | Escalation recall | False escalations | Hard cases (no keyword) | Avg latency |",
             "|---|---|---|---|---|---|"]
    for mode, res in all_results.items():
        n = len(res)
        acc = sum(r["ok"] for r in res)
        esc = [r for r in res if r["expect"].startswith("escalated")]
        esc_ok = sum(r["ok"] for r in esc)
        false_esc = sum(1 for r in res if r["got"].startswith("escalated") and not r["expect"].startswith("escalated"))
        hard = [r for r in res if "note" in r]
        hard_ok = sum(r["ok"] for r in hard)
        lat = sum(r["seconds"] for r in res) / n
        lines.append(f"| {mode} | **{acc}/{n} ({acc / n:.0%})** | {esc_ok}/{len(esc)} | {false_esc} | "
                     f"{hard_ok}/{len(hard)} | {lat:.2f}s |")

    for mode, res in all_results.items():
        sources = Counter(r["source"] for r in res)
        lines += ["", f"## {mode}: failures", "",
                  "Decision sources: " + ", ".join(f"{k}={v}" for k, v in sources.most_common()), ""]
        fails = [r for r in res if not r["ok"]]
        if not fails:
            lines.append("None.")
            continue
        lines += ["| Message | Expected | Got | Source | Note |", "|---|---|---|---|---|"]
        for r in fails:
            lines.append(f"| {r['text']} | {r['expect']} | {r['got']} | {r['source']} | {r.get('note', '')} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", default=["rules", "llm"], choices=["rules", "llm"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.ERROR)
    chatbot.answer_from_sop = with_retries(chatbot.answer_from_sop)
    classifier.classify = with_retries(classifier.classify)

    all_results = {mode: run_mode(mode) for mode in args.modes}
    md = report(all_results)
    (ROOT / "evals" / "results.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
