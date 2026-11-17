"""AI review tagging with LangChain + OpenAI.

Two steps per review, each with its own temperature:
1. TAGS  (sentiment, category, urgency, language, summary) - TAG_TEMPERATURE, default 0.
   Low = the same review always gets the same tags, so filters and charts stay stable.
2. REPLY (suggested reply to the customer)                 - REPLY_TEMPERATURE, default 0.4.
   A little higher = replies sound natural and are not copy-paste identical.
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import OPENAI_API_KEY, OPENAI_MODEL, REPLY_TEMPERATURE, TAG_TEMPERATURE
from .schemas import ReviewAnalysis, ReviewTags

LANGUAGES_NOTE = """Reviews may be written in:
- English
- Tamil (Tamil script, e.g. "சாப்பாடு நன்றாக இருந்தது")
- Tanglish (Tamil words typed in English letters, e.g. "food semma taste, but delivery romba late")"""

TAG_SYSTEM_PROMPT = f"""You are a customer-experience analyst for a business in Tamil Nadu, India.
You read ONE customer review and tag it.

{LANGUAGES_NOTE}

Rules:
- sentiment: positive, neutral or negative. Use the text, not just the star rating.
- category: pick the ONE best-matching topic from the allowed list.
- urgency:
    HIGH   = health/safety issue, food poisoning, fraud, money taken without service,
             legal threat, abusive staff, or a very angry customer threatening to leave/post publicly.
    MEDIUM = a real complaint that should be fixed soon (late delivery, wrong item, rude reply).
    LOW    = praise, suggestions, or minor issues.
- language: English, Tamil, Tanglish, or Other.
- summary: ONE short sentence in ENGLISH.
"""

REPLY_SYSTEM_PROMPT = f"""You write replies to customer reviews for a business in Tamil Nadu, India.

{LANGUAGES_NOTE}

Write a short, polite, professional reply (2-3 sentences) from the business.
* Reply in the SAME language and style as the review
  (Tamil script for Tamil, Tanglish for Tanglish, English for English).
* Thank the customer. If they complain, apologise and offer to help
  (ask them to contact support). Never promise refunds or compensation.
* If urgency is HIGH, take it seriously and ask them to contact support right away.
* Use simple, natural, everyday words - the way a friendly shop owner in Chennai talks.
* Output ONLY the reply text: no quotes, no labels, no explanation.

Example of a GOOD Tanglish reply:
  Review: "Delivery romba late, food cold ah irundhuchu"
  Reply:  Sorry sir/madam, late delivery and cold food-ku romba sorry. Idhu nadakka koodathu.
          Please unga order details support-ku anuppunga, naanga udane check panrom. Thank you!
"""

REVIEW_MESSAGE = "Star rating: {rating}\nPlatform: {platform}\n\nReview:\n{review_text}"

tag_prompt = ChatPromptTemplate.from_messages(
    [("system", TAG_SYSTEM_PROMPT), ("human", REVIEW_MESSAGE)]
)
reply_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", REPLY_SYSTEM_PROMPT),
        (
            "human",
            REVIEW_MESSAGE
            + "\n\nTags: sentiment={sentiment}, urgency={urgency}, language={language}",
        ),
    ]
)


def _llm(temperature: float) -> ChatOpenAI:
    return ChatOpenAI(
        model=OPENAI_MODEL, temperature=temperature, api_key=OPENAI_API_KEY, max_retries=3
    )


def _build_chains():
    """Returns (tag_chain, reply_chain)."""
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("sk-your"):
        raise RuntimeError("OPENAI_API_KEY is missing. Put your key in the .env file.")
    tag_chain = tag_prompt | _llm(TAG_TEMPERATURE).with_structured_output(ReviewTags)
    reply_chain = reply_prompt | _llm(REPLY_TEMPERATURE) | StrOutputParser()
    return tag_chain, reply_chain


def analyze_reviews(reviews: list[dict], max_concurrency: int = 5) -> list[ReviewAnalysis | Exception]:
    """Tag many reviews in parallel, then write a reply for each.

    Each item in `reviews` needs: review_text, rating, platform.
    Returns one result per review, in the same order. A failed review gives an Exception.
    """
    if not reviews:
        return []
    tag_chain, reply_chain = _build_chains()
    config = {"max_concurrency": max_concurrency}
    inputs = [
        {
            "review_text": r["review_text"],
            "rating": r.get("rating") if r.get("rating") is not None else "unknown",
            "platform": r.get("platform") or "unknown",
        }
        for r in reviews
    ]

    tags = tag_chain.batch(inputs, config=config, return_exceptions=True)

    # Only write replies for reviews that were tagged successfully
    ok = [i for i, t in enumerate(tags) if not isinstance(t, Exception)]
    replies = reply_chain.batch(
        [
            {
                **inputs[i],
                "sentiment": tags[i].sentiment,
                "urgency": tags[i].urgency,
                "language": tags[i].language,
            }
            for i in ok
        ],
        config=config,
        return_exceptions=True,
    ) if ok else []

    results: list[ReviewAnalysis | Exception] = list(tags)
    for i, reply in zip(ok, replies):
        if isinstance(reply, Exception):
            results[i] = reply
        elif not reply.strip():
            results[i] = ValueError("AI returned an empty reply")
        else:
            results[i] = ReviewAnalysis(**tags[i].model_dump(), suggested_reply=reply.strip())
    return results


if __name__ == "__main__":
    # Quick test:  python -m app.analyzer   (from the backend folder)
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # so Windows can print Tamil text
    print(f"Model {OPENAI_MODEL} | tag temperature {TAG_TEMPERATURE} | reply temperature {REPLY_TEMPERATURE}")
    samples = [
        {"review_text": "Food was cold and the delivery guy was rude. Very disappointed.", "rating": 2, "platform": "Google"},
        {"review_text": "சாப்பாடு மிகவும் சுவையாக இருந்தது! சேவை அருமை.", "rating": 5, "platform": "Zomato"},
        {"review_text": "Biryani semma taste, but after eating my son got vomiting. Romba worry ah iruku!", "rating": 1, "platform": "Swiggy"},
    ]
    for sample, result in zip(samples, analyze_reviews(samples)):
        print("\nREVIEW:", sample["review_text"])
        if isinstance(result, Exception):
            print("  ERROR:", result)
        else:
            for key, value in result.model_dump().items():
                print(f"  {key:16}: {value}")
