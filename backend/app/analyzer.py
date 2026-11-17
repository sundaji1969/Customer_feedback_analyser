"""AI review tagging with LangChain + OpenAI.

Two steps per review, each with its own model and temperature:
1. TAGS  (sentiment, category, urgency, language, summary) - TAG_MODEL, TAG_TEMPERATURE (default 0).
   Low = the same review always gets the same tags, so filters and charts stay stable.
2. REPLY (suggested reply to the customer)                 - REPLY_MODEL, REPLY_TEMPERATURE (default 0.4).
   A little higher = replies sound natural and are not copy-paste identical.
"""
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import (
    AI_CONCURRENCY,
    AI_TIMEOUT_SECONDS,
    OPENAI_API_KEY,
    REPLY_MODEL,
    REPLY_TEMPERATURE,
    TAG_MODEL,
    TAG_TEMPERATURE,
)
from .schemas import TAMIL_SCRIPT, ReviewAnalysis, ReviewTags

LANGUAGES_NOTE = """Reviews may be written in:
- English
- Tamil    = written in Tamil SCRIPT, e.g. "சாப்பாடு நன்றாக இருந்தது"
- Tanglish = Tamil words typed in English (Latin) letters, often mixed with English words,
             e.g. "food semma taste, but delivery romba late". No Tamil script.
- Other    = any other language, e.g. Hindi typed in English letters ("khana thanda tha")"""

TAG_SYSTEM_PROMPT = f"""You are a customer-experience analyst for a business in Tamil Nadu, India.
You read ONE customer review and tag it.

{LANGUAGES_NOTE}

Rules:
- sentiment: positive, neutral or negative. Judge the TEXT. The star rating can be wrong
  (customers mis-tap) and the text can be sarcastic ("Amazing service, waited only 2 hours").
  For mixed reviews, go with the customer's main point.
- category: the ONE topic the customer cares most about:
    Product Quality = taste, freshness, portion, the product itself, or something found in it (hair, glass)
    Delivery        = late, cold on arrival, wrong or missing items, packing, the delivery person
    Customer Service= phone/chat support, how a complaint was handled
    Staff Behaviour = behaviour of staff at the shop
    Cleanliness     = hygiene of the premises (tables, toilets, pests)
    Pricing         = prices, value for money
    App/Website     = app or website problems, wrong information online
    Payment/Refund  = charges, failed payments, refunds
    Other           = ambience, parking, location, or no clear topic
- urgency:
    HIGH   = health or safety (illness after eating, allergy, glass or pests, harassment),
             fraud or an unauthorised charge, money taken without service,
             a legal/police/consumer-court/food-safety threat, or abusive staff.
    MEDIUM = a real complaint that should be fixed soon (late delivery, wrong item, rude staff,
             dirty premises, angry customer saying they will not come back).
    LOW    = praise, suggestions, or minor issues.
- language: English, Tamil, Tanglish, or Other (see above). Tanglish is NEVER Tamil:
  only call it Tamil when the review contains Tamil script.
- summary: ONE short sentence in ENGLISH, written in Latin letters, even when the review is
  in Tamil or Tanglish. Translate the meaning; never copy Tamil words or Tamil script.
"""

# Shown to the AI to set the tone. They cover different situations on purpose, and the
# eval script (eval_ai.py) checks that real replies never copy them.
EXAMPLE_REPLIES = [
    "Thank you! Really happy you enjoyed the ghee roast, and we'll pass your kind words on to the kitchen team. See you again soon!",
    "சட்னி இல்லாமல் பார்சல் வந்ததற்கு மன்னிக்கவும். உங்கள் ஆர்டர் எண்ணை support-க்கு அனுப்புங்கள், நாங்கள் சரிபார்க்கிறோம். நன்றி!",
    "Romba sorry, neenga ippo nalla irukeengala? Idha naanga romba serious ah edukkurom. Unga order ID-um phone number-um support-ku udane anuppunga, engaloda team ungala contact pannuvanga.",
]

REPLY_SYSTEM_PROMPT = f"""You write replies to customer reviews for a business in Tamil Nadu, India.
The reply is posted publicly under the review.

{LANGUAGES_NOTE}

Write a short reply (2-3 sentences) from the business, like a friendly, caring shop owner in
Chennai: warm, simple, everyday words. Not like a call centre.

Language:
* Tamil review    -> reply in Tamil SCRIPT (never Tanglish).
* Tanglish review -> reply in Tanglish, in English letters ONLY (no Tamil script). Speak as
  "naanga"/"engal" (we) and call the customer "neenga"/"unga". Keep it grammatical and natural.
* English review  -> reply in English.
* Other language  -> reply in simple English.

Content:
* Mention the customer's actual point in their terms (the cold pizza, the glass in the curry,
  Ramesh anna, the parking) - never a reply that would fit any review.
* Praise: thank them for the specific thing they liked. Suggestion: say it has been noted.
* Complaint: say sorry for that specific problem and say what happens next.
* If urgency is HIGH: show concern for the person first (for illness or safety, ask how they are),
  say the team will look into it today, and ask them to send their order ID and phone number
  to support so the team can contact them. For an unauthorised charge, also suggest informing
  their bank.
* If the complaint is that support did not answer, do not just send them back to support:
  apologise for that and ask them to share their phone number so the team calls them.
* Never admit fault or blame for health, safety or legal matters (no "our mistake",
  "our fault") - say it is being checked. Never promise refunds, compensation, free items,
  or that it "will never happen again".
* Avoid stock phrases: "We sincerely apologize for the inconvenience", "Your feedback is
  important to us", "Thank you for bringing this to our attention", "top priority".
* Output ONLY the reply text: no quotes, no labels, no explanation.

Examples of the TONE (different situations; never reuse their sentences):
  English, praise:      {EXAMPLE_REPLIES[0]}
  Tamil, missing item:  {EXAMPLE_REPLIES[1]}
  Tanglish, fell ill:   {EXAMPLE_REPLIES[2]}
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


def _llm(model: str, temperature: float) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=OPENAI_API_KEY,
        max_retries=3,  # network errors / rate limits are retried by the OpenAI client
        timeout=AI_TIMEOUT_SECONDS,  # one stuck call can never hang a whole upload
    )


def _build_chains():
    """Returns (tag_chain, reply_chain)."""
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("sk-your"):
        raise RuntimeError("OPENAI_API_KEY is missing. Put your key in the .env file.")
    # If the AI breaks a rule (e.g. a Tamil summary, an empty field), ask once more.
    tag_chain = (tag_prompt | _llm(TAG_MODEL, TAG_TEMPERATURE).with_structured_output(ReviewTags)).with_retry(
        stop_after_attempt=2, retry_if_exception_type=(ValueError,)
    )
    reply_chain = reply_prompt | _llm(REPLY_MODEL, REPLY_TEMPERATURE) | StrOutputParser()
    return tag_chain, reply_chain


def fix_language(tags: ReviewTags, review_text: str) -> ReviewTags:
    """Tamil vs Tanglish is decided by the script, which code can check exactly.

    The AI sometimes calls Tanglish "Tamil", and the reply would then come back in Tamil
    script, which a customer who typed in English letters may not be able to read.
    """
    if TAMIL_SCRIPT.search(review_text):
        language = "Tamil"
    elif tags.language == "Tamil":
        language = "Tanglish"
    else:
        return tags
    return tags.model_copy(update={"language": language})


def analyze_reviews(reviews: list[dict], max_concurrency: int = AI_CONCURRENCY) -> list[ReviewAnalysis | Exception]:
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
    tags = [
        t if isinstance(t, Exception) else fix_language(t, inp["review_text"])
        for t, inp in zip(tags, inputs)
    ]

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
        else:
            try:
                results[i] = ReviewAnalysis(**tags[i].model_dump(), suggested_reply=reply)
            except ValueError as exc:  # e.g. empty reply
                results[i] = exc
    return results


if __name__ == "__main__":
    # Quick test:  python -m app.analyzer   (from the backend folder)
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # so Windows can print Tamil text
    print(f"Tags: {TAG_MODEL} (temperature {TAG_TEMPERATURE}) | Replies: {REPLY_MODEL} (temperature {REPLY_TEMPERATURE})")
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
