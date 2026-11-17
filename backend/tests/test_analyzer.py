"""Tests for the AI tagging module (OpenAI is never called)."""
import pytest

from app import analyzer, config
from app.schemas import ReviewAnalysis, ReviewTags

GOOD_TAGS = dict(sentiment="positive", category="Delivery", urgency="LOW", language="English", summary="Customer liked the food.")


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


def test_tags_and_reply_use_their_own_models_and_temperatures(monkeypatch):
    monkeypatch.setattr(analyzer, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(analyzer, "TAG_MODEL", "tag-model-x")
    monkeypatch.setattr(analyzer, "REPLY_MODEL", "reply-model-y")
    monkeypatch.setattr(analyzer, "TAG_TEMPERATURE", 0.0)
    monkeypatch.setattr(analyzer, "REPLY_TEMPERATURE", 0.4)
    tag_chain, reply_chain = analyzer._build_chains()
    tag_llm = tag_chain.bound.steps[1].bound          # retry wrapper -> prompt | llm-with-schema
    reply_llm = reply_chain.steps[1]
    assert (tag_llm.model_name, reply_llm.model_name) == ("tag-model-x", "reply-model-y")
    assert (tag_llm.temperature, reply_llm.temperature) == (0.0, 0.4)
    # every call has a time limit, so one stuck request can't hang an upload
    assert tag_llm.request_timeout == reply_llm.request_timeout == config.AI_TIMEOUT_SECONDS
    assert tag_chain.max_attempt_number == 2          # broken AI output is asked for once more


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
                           "sentiment": "positive", "urgency": "LOW", "language": "English"}

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
    assert "Tanglish review -> reply in Tanglish" in reply_msgs[0].content
    assert "urgency=LOW" in reply_msgs[1].content and "language=Tanglish" in reply_msgs[1].content


@pytest.mark.parametrize("summary, problem", [
    ("", "empty"),
    ("   ", "empty"),
    ("சாப்பாடு நன்றாக இருந்தது", "English"),             # Tamil script
    ("Food was good, சேவை அருமை", "English"),            # mixed
    ("5/5 !!!", "English"),                               # no words
])
def test_summary_must_be_english(summary, problem):
    with pytest.raises(ValueError, match=problem):
        ReviewTags(**{**GOOD_TAGS, "summary": summary})


def test_tanglish_style_english_summary_is_fine():
    t = ReviewTags(**{**GOOD_TAGS, "summary": "  Biryani tasted great but delivery was late.  "})
    assert t.summary == "Biryani tasted great but delivery was late."


def test_reply_must_not_be_empty():
    with pytest.raises(ValueError, match="empty"):
        ReviewAnalysis(**GOOD_TAGS, suggested_reply="  ")
    # Tamil replies are allowed (and expected) - only the summary must be English
    assert ReviewAnalysis(**GOOD_TAGS, suggested_reply="நன்றி!").suggested_reply == "நன்றி!"


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


# ---------- model settings ----------

@pytest.mark.parametrize("env, expected", [
    ({}, ("gpt-4o-mini", "gpt-5.5")),                                     # defaults
    ({"OPENAI_MODEL": "old-model"}, ("old-model", "gpt-5.5")),            # old .env keeps working
    ({"OPENAI_MODEL": "old-model", "TAG_MODEL": "t"}, ("t", "gpt-5.5")),  # TAG_MODEL wins
    ({"TAG_MODEL": " t ", "REPLY_MODEL": " r "}, ("t", "r")),             # spaces trimmed
    ({"TAG_MODEL": "", "REPLY_MODEL": ""}, ("gpt-4o-mini", "gpt-5.5")),  # empty = default (docker-compose)
])
def test_model_settings(monkeypatch, env, expected):
    for name in ("OPENAI_MODEL", "TAG_MODEL", "REPLY_MODEL"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert config._models() == expected


@pytest.mark.parametrize("review_text, ai_language, expected", [
    ("Dosa semma ah irundhuchu", "Tamil", "Tanglish"),      # no Tamil script -> cannot be Tamil
    ("சாப்பாடு அருமை", "Tanglish", "Tamil"),                 # Tamil script -> Tamil
    ("சாப்பாடு super, delivery late", "English", "Tamil"),  # any Tamil script -> Tamil
    ("Dosa semma ah irundhuchu", "Tanglish", "Tanglish"),   # already right
    ("Food was great", "English", "English"),
    ("Khana thanda tha", "Other", "Other"),
])
def test_fix_language_uses_the_script(review_text, ai_language, expected):
    tags = ReviewTags(**{**GOOD_TAGS, "language": ai_language})
    assert analyzer.fix_language(tags, review_text).language == expected


def test_reply_step_gets_the_corrected_language(monkeypatch):
    text = "Delivery romba late"
    _, reply_chain = use_fake_chains(
        monkeypatch,
        tag_outputs={text: ReviewTags(**{**GOOD_TAGS, "language": "Tamil"})},
        reply_outputs={text: "Sorry, naanga check panrom"},
    )
    out = analyzer.analyze_reviews([{"review_text": text}])
    assert reply_chain.calls[0]["inputs"][0]["language"] == "Tanglish"
    assert out[0].language == "Tanglish"
