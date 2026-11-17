"""Measure AI quality on a hand-labelled set of reviews (data/eval_reviews.csv).

    python eval_ai.py                         # uses TAG_MODEL / REPLY_MODEL from .env
    python eval_ai.py --model gpt-5.4-mini    # try one model for both steps
    python eval_ai.py --reply-model gpt-5.4-mini   # or change just one step
    python eval_ai.py --out results.json      # also save every answer

This calls the real OpenAI API (about 2 calls per review), so it costs a little money.
The labelled file allows more than one right answer, separated by "|".
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd

EVAL_FILE = Path(__file__).resolve().parents[1] / "data" / "eval_reviews.csv"
FIELDS = ["sentiment", "category", "urgency", "language"]
TAMIL = re.compile(r"[஀-௿]")
REFUND_PROMISE = re.compile(
    r"\b(we will|we'll|will be)\s+(refund|compensat|give you a refund)|\bfull refund\b|\bfree (meal|order)\b",
    re.I,
)


def reply_problems(row, reply: str, example_replies: list[str]) -> list[str]:
    problems = []
    langs = row["language"].split("|")
    has_tamil = bool(TAMIL.search(reply))
    if "Tamil" in langs and not has_tamil:
        problems.append("Tamil review, reply not in Tamil script")
    if "Tamil" not in langs and has_tamil:
        problems.append("reply uses Tamil script for a non-Tamil review")
    for ex in example_replies:
        # Sharing one required phrase ("send your order ID...") is fine; mostly the same text is not.
        if difflib.SequenceMatcher(None, reply.lower(), ex.lower()).ratio() > 0.75:
            problems.append("reply copies the prompt example")
    if REFUND_PROMISE.search(reply):
        problems.append("promises refund/compensation")
    sentences = len([s for s in re.split(r"[.!?]+", reply) if s.strip()])
    if sentences > 5:
        problems.append(f"too long ({sentences} sentences)")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="use this model for both tags and replies")
    parser.add_argument("--tag-model", help="model for tags (default: TAG_MODEL from .env)")
    parser.add_argument("--reply-model", help="model for replies (default: REPLY_MODEL from .env)")
    parser.add_argument("--out", help="save every answer to this JSON file")
    args = parser.parse_args()
    if args.tag_model or args.model:
        os.environ["TAG_MODEL"] = args.tag_model or args.model
    if args.reply_model or args.model:
        os.environ["REPLY_MODEL"] = args.reply_model or args.model
    sys.stdout.reconfigure(encoding="utf-8")

    from app import analyzer  # imported after the model settings are set

    gold = pd.read_csv(EVAL_FILE, dtype=str, keep_default_na=False)
    reviews = [
        {"review_text": r.review_text, "rating": int(r.rating) if r.rating else None, "platform": r.platform}
        for r in gold.itertuples()
    ]
    examples = getattr(analyzer, "EXAMPLE_REPLIES", None) or [
        # the single example in the original prompt
        "Sorry sir/madam, late delivery and cold food-ku romba sorry. Idhu nadakka koodathu. "
        "Please unga order details support-ku anuppunga, naanga udane check panrom. Thank you!"
    ]

    start = time.time()
    results = analyzer.analyze_reviews(reviews)
    seconds = time.time() - start

    correct = {f: 0 for f in FIELDS}
    failed, wrong, flagged, saved = 0, [], [], []
    for (_, row), result in zip(gold.iterrows(), results):
        if isinstance(result, Exception):
            failed += 1
            wrong.append(f"{row.review_id}: FAILED {result}")
            saved.append({"review_id": row.review_id, "error": str(result)})
            continue
        answer = result.model_dump()
        saved.append({"review_id": row.review_id, "review_text": row.review_text, **answer})
        for f in FIELDS:
            if answer[f] in row[f].split("|"):
                correct[f] += 1
            else:
                wrong.append(f"{row.review_id} {f}: got {answer[f]!r}, expected {row[f]!r}  | {row.review_text[:60]}")
        for p in reply_problems(row, answer["suggested_reply"], examples):
            flagged.append(f"{row.review_id}: {p}")

    n = len(gold)
    print(f"\nTags: {analyzer.TAG_MODEL}   Replies: {analyzer.REPLY_MODEL}   reviews: {n}   failed: {failed}   time: {seconds:.0f}s")
    for f in FIELDS:
        print(f"  {f:10} {correct[f]:>3}/{n}  {correct[f] / n:6.1%}")
    total = sum(correct.values())
    print(f"  {'ALL TAGS':10} {total:>3}/{n * len(FIELDS)}  {total / (n * len(FIELDS)):6.1%}")
    print(f"  reply rule problems: {len(flagged)}")
    if wrong:
        print("\nWrong tags:")
        print("\n".join("  " + w for w in wrong))
    if flagged:
        print("\nReply problems:")
        print("\n".join("  " + f for f in flagged))
    if args.out:
        Path(args.out).write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nSaved answers to {args.out}")


if __name__ == "__main__":
    main()
