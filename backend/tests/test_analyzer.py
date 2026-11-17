"""Tests for the AI tagging module (OpenAI is never called)."""
import pytest

from app import analyzer
from app.schemas import ReviewAnalysis


def test_empty_list_needs_no_api_key(monkeypatch):
    monkeypatch.setattr(analyzer, "OPENAI_API_KEY", "")
    assert analyzer.analyze_reviews([]) == []


@pytest.mark.parametrize("key", ["", "sk-your-key-here"])
def test_missing_or_placeholder_key_raises(monkeypatch, key):
    monkeypatch.setattr(analyzer, "OPENAI_API_KEY", key)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        analyzer.analyze_reviews([{"review_text": "hi", "rating": 5, "platform": "Google"}])


def test_inputs_sent_to_ai_fill_unknowns(monkeypatch):
    """Missing rating/platform become 'unknown'; rating 0 is kept."""
    seen = {}

    class FakeChain:
        def batch(self, inputs, config=None, return_exceptions=False):
            seen["inputs"], seen["config"], seen["return_exceptions"] = inputs, config, return_exceptions
            return ["ok"] * len(inputs)

    monkeypatch.setattr(analyzer, "_build_chain", lambda: FakeChain())
    out = analyzer.analyze_reviews(
        [
            {"review_text": "a", "rating": None, "platform": None},
            {"review_text": "b", "rating": 0, "platform": "Swiggy"},
            {"review_text": "c"},
        ],
        max_concurrency=2,
    )
    assert out == ["ok", "ok", "ok"]
    assert seen["inputs"] == [
        {"review_text": "a", "rating": "unknown", "platform": "unknown"},
        {"review_text": "b", "rating": 0, "platform": "Swiggy"},
        {"review_text": "c", "rating": "unknown", "platform": "unknown"},
    ]
    assert seen["config"] == {"max_concurrency": 2}
    assert seen["return_exceptions"] is True  # one bad review must not break the batch


def test_prompt_includes_review_details():
    messages = analyzer.prompt.format_messages(review_text="Semma taste", rating=5, platform="Zomato")
    assert "Tanglish" in messages[0].content
    assert "Semma taste" in messages[1].content
    assert "Zomato" in messages[1].content


def test_ai_output_schema_rejects_unknown_values():
    good = dict(sentiment="positive", category="Delivery", urgency="LOW", language="Tamil",
                summary="s", suggested_reply="r")
    ReviewAnalysis(**good)
    for field, bad in [("urgency", "URGENT"), ("category", "Food"), ("sentiment", "happy")]:
        with pytest.raises(ValueError):
            ReviewAnalysis(**{**good, field: bad})
