"""Tests for the AI tagging module (OpenAI is never called)."""
import pytest

from app import analyzer, config
from app.schemas import ReviewAnalysis, ReviewTags

GOOD_TAGS = dict(sentiment="positive", category="Delivery", urgency="LOW", language="Tamil", summary="s")


class FakeChain:
    """Stands in for a LangChain chain. `outputs` maps review_text -> result (or Exception)."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def batch(self, inputs, config=None, return_exceptions=False):
        self.calls.append({"inputs": inputs, "config": config, "return_exceptions": return_exceptions})
        return [self.outputs[i["review_text"]] for i in inputs]


def use_fake_chains(monkeypatch, tag_outputs, reply_outputs):
    tag_chain, reply_chain = FakeChain(tag_outputs), FakeChain(reply_outputs)
    monkeypatch.setattr(analyzer, "_build_chains", lambda: (tag_chain, reply_chain))
    return tag_chain, reply_chain


def test_empty_list_needs_no_api_key(monkeypatch):
    monkeypatch.setattr(analyzer, "OPENAI_API_KEY", "")
    assert analyzer.analyze_reviews([]) == []


@pytest.mark.parametrize("key", ["", "sk-your-key-here"])
def test_missing_or_placeholder_key_raises(monkeypatch, key):
    monkeypatch.setattr(analyzer, "OPENAI_API_KEY", key)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        analyzer.analyze_reviews([{"review_text": "hi", "rating": 5, "platform": "Google"}])


def test_tags_and_reply_use_their_own_temperatures(monkeypatch):
    monkeypatch.setattr(analyzer, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(analyzer, "TAG_TEMPERATURE", 0.0)
    monkeypatch.setattr(analyzer, "REPLY_TEMPERATURE", 0.4)
    tag_chain, reply_chain = analyzer._build_chains()
    assert tag_chain.first.__class__.__name__ == "ChatPromptTemplate"
    temps = [step.bound.temperature if hasattr(step, "bound") else getattr(step, "temperature", None)
             for step in [tag_chain.steps[1], reply_chain.steps[1]]]
    assert temps == [0.0, 0.4]


def test_inputs_and_tags_flow_into_reply(monkeypatch):
    """Missing rating/platform become 'unknown'; rating 0 is kept; the reply step sees the tags."""
    tag_chain, reply_chain = use_fake_chains(
        monkeypatch,
        tag_outputs={t: ReviewTags(**GOOD_TAGS) for t in "abc"},
        reply_outputs={"a": " Thanks a! ", "b": "Thanks b", "c": "Thanks c"},
    )
    out = analyzer.analyze_reviews(
        [
            {"review_text": "a", "rating": None, "platform": None},
            {"review_text": "b", "rating": 0, "platform": "Swiggy"},
            {"review_text": "c"},
        ],
        max_concurrency=2,
    )
    assert tag_chain.calls[0]["inputs"] == [
        {"review_text": "a", "rating": "unknown", "platform": "unknown"},
        {"review_text": "b", "rating": 0, "platform": "Swiggy"},
        {"review_text": "c", "rating": "unknown", "platform": "unknown"},
    ]
    assert tag_chain.calls[0]["config"] == {"max_concurrency": 2}
    # one bad review must not break the batch, in either step
    assert tag_chain.calls[0]["return_exceptions"] is True
    assert reply_chain.calls[0]["return_exceptions"] is True

    reply_input = reply_chain.calls[0]["inputs"][1]
    assert reply_input == {"review_text": "b", "rating": 0, "platform": "Swiggy",
                           "sentiment": "positive", "urgency": "LOW", "language": "Tamil"}

    assert all(isinstance(r, ReviewAnalysis) for r in out)
    assert out[0].suggested_reply == "Thanks a!"  # whitespace trimmed
    assert out[1].model_dump() == {**GOOD_TAGS, "suggested_reply": "Thanks b"}


def test_failures_in_either_step_stay_per_review(monkeypatch):
    tag_fail, reply_fail = RuntimeError("tag failed"), RuntimeError("reply failed")
    _, reply_chain = use_fake_chains(
        monkeypatch,
        tag_outputs={"ok": ReviewTags(**GOOD_TAGS), "badtag": tag_fail,
                     "badreply": ReviewTags(**GOOD_TAGS), "empty": ReviewTags(**GOOD_TAGS)},
        reply_outputs={"ok": "Thank you", "badreply": reply_fail, "empty": "   "},
    )
    out = analyzer.analyze_reviews([{"review_text": t} for t in ["ok", "badtag", "badreply", "empty"]])

    assert isinstance(out[0], ReviewAnalysis)
    assert out[1] is tag_fail
    assert out[2] is reply_fail
    assert isinstance(out[3], ValueError)
    # no reply is written (or paid for) when tagging failed
    assert [i["review_text"] for i in reply_chain.calls[0]["inputs"]] == ["ok", "badreply", "empty"]


def test_no_reply_call_when_all_tags_fail(monkeypatch):
    _, reply_chain = use_fake_chains(monkeypatch, {"x": RuntimeError("down")}, {})
    out = analyzer.analyze_reviews([{"review_text": "x"}])
    assert isinstance(out[0], RuntimeError)
    assert reply_chain.calls == []


def test_prompts_include_review_details():
    tag_msgs = analyzer.tag_prompt.format_messages(review_text="Semma taste", rating=5, platform="Zomato")
    assert "Tanglish" in tag_msgs[0].content
    assert "Semma taste" in tag_msgs[1].content and "Zomato" in tag_msgs[1].content
    assert "suggested_reply" not in tag_msgs[0].content  # tag step does not write replies

    reply_msgs = analyzer.reply_prompt.format_messages(
        review_text="Semma taste", rating=5, platform="Zomato",
        sentiment="positive", urgency="LOW", language="Tanglish",
    )
    assert "SAME language" in reply_msgs[0].content
    assert "urgency=LOW" in reply_msgs[1].content and "language=Tanglish" in reply_msgs[1].content


def test_ai_output_schema_rejects_unknown_values():
    ReviewTags(**GOOD_TAGS)
    for field, bad in [("urgency", "URGENT"), ("category", "Food"), ("sentiment", "happy")]:
        with pytest.raises(ValueError):
            ReviewTags(**{**GOOD_TAGS, field: bad})


# ---------- temperature settings ----------

@pytest.mark.parametrize("raw, expected", [("", 0.4), ("0", 0.0), (" 0.7 ", 0.7), ("1", 1.0)])
def test_temperature_setting(monkeypatch, raw, expected):
    monkeypatch.setenv("REPLY_TEMPERATURE", raw)
    assert config._temperature("REPLY_TEMPERATURE", 0.4) == expected


@pytest.mark.parametrize("raw", ["hot", "-0.1", "1.5"])
def test_bad_temperature_gives_clear_error(monkeypatch, raw):
    monkeypatch.setenv("TAG_TEMPERATURE", raw)
    with pytest.raises(ValueError, match="TAG_TEMPERATURE"):
        config._temperature("TAG_TEMPERATURE", 0.0)


def test_default_temperatures():
    assert config.TAG_TEMPERATURE == 0.0
    assert config.REPLY_TEMPERATURE == 0.4
