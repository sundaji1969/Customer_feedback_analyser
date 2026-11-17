"""AI review tagging with LangChain + OpenAI."""
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from .config import OPENAI_API_KEY, OPENAI_MODEL
from .schemas import ReviewAnalysis

SYSTEM_PROMPT = """You are a customer-experience analyst for a business in Tamil Nadu, India.
You read ONE customer review and tag it.

Reviews may be written in:
- English
- Tamil (Tamil script, e.g. "சாப்பாடு நன்றாக இருந்தது")
- Tanglish (Tamil words typed in English letters, e.g. "food semma taste, but delivery romba late")

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
- suggested_reply: a short, polite, professional reply (2-3 sentences) from the business.
    * Reply in the SAME language and style as the review
      (Tamil script for Tamil, Tanglish for Tanglish, English for English).
    * Thank the customer. If they complain, apologise and offer to help
      (ask them to contact support). Never promise refunds or compensation.
    * Use simple, natural, everyday words - the way a friendly shop owner in Chennai talks.

Example of a GOOD Tanglish reply:
  Review: "Delivery romba late, food cold ah irundhuchu"
  Reply:  "Sorry sir/madam, late delivery and cold food-ku romba sorry. Idhu nadakka koodathu.
           Please unga order details support-ku anuppunga, naanga udane check panrom. Thank you!"
"""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("human", "Star rating: {rating}\nPlatform: {platform}\n\nReview:\n{review_text}"),
    ]
)


def _build_chain():
    if not OPENAI_API_KEY or OPENAI_API_KEY.startswith("sk-your"):
        raise RuntimeError("OPENAI_API_KEY is missing. Put your key in the .env file.")
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, api_key=OPENAI_API_KEY, max_retries=3)
    return prompt | llm.with_structured_output(ReviewAnalysis)


def analyze_reviews(reviews: list[dict], max_concurrency: int = 5) -> list[ReviewAnalysis | Exception]:
    """Tag many reviews in parallel.

    Each item in `reviews` needs: review_text, rating, platform.
    Returns one result per review, in the same order. A failed review gives an Exception.
    """
    if not reviews:
        return []
    chain = _build_chain()
    inputs = [
        {
            "review_text": r["review_text"],
            "rating": r.get("rating") if r.get("rating") is not None else "unknown",
            "platform": r.get("platform") or "unknown",
        }
        for r in reviews
    ]
    return chain.batch(inputs, config={"max_concurrency": max_concurrency}, return_exceptions=True)


if __name__ == "__main__":
    # Quick test:  python -m app.analyzer   (from the backend folder)
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # so Windows can print Tamil text
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
