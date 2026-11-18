"""The labelled evaluation set must stay readable by eval_ai.py (no AI call here)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import eval_ai  # noqa: E402

LABELS = {
    "sentiment": {"positive", "neutral", "negative"},
    "urgency": {"HIGH", "MEDIUM", "LOW"},
    "language": {"English", "Tamil", "Tanglish", "Other"},
}


def test_real_eval_file_loads():
    gold = eval_ai.load_gold()
    assert len(gold) >= 40
    assert gold["review_id"].is_unique
    assert {"review_id", "review_text", "rating", "platform", *eval_ai.FIELDS} <= set(gold.columns)
    assert not any(c.startswith("unnamed") for c in gold.columns)
    assert gold["rating"].str.fullmatch(r"[1-5]").all()


def test_eval_labels_are_valid():
    """Each expected answer (or each choice in 'a|b') must be a value the AI can return."""
    gold = eval_ai.load_gold()
    for field, allowed in LABELS.items():
        for rid, value in zip(gold["review_id"], gold[field]):
            assert set(value.split("|")) <= allowed, f"{rid} {field}={value!r}"


def test_excel_style_file(tmp_path):
    """Capitalised headers, other column order, empty extra columns, BOM, blank row."""
    f = tmp_path / "eval.csv"
    f.write_text(
        "﻿Review_ID,Rating,Platform,Review_Text,Sentiment,Category,Urgency,Language,Note,,\n"
        "R1,5,Google, Great food ,positive,Product Quality,LOW,English,,,\n"
        ",,,,,,,,,,\n",
        encoding="utf-8",
    )
    gold = eval_ai.load_gold(f)
    assert len(gold) == 1
    assert gold.loc[0, "review_text"] == "Great food"
    assert gold.loc[0, "rating"] == "5"


def test_missing_column_is_clear(tmp_path):
    f = tmp_path / "eval.csv"
    f.write_text("review_id,review_text\nR1,hi\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="missing columns: rating, platform"):
        eval_ai.load_gold(f)
