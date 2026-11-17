"""Numbers and files for the dashboard. All counts and percentages are calculated here with
pandas from the review table itself - never by the AI - so they always match the table."""
import pandas as pd


def summary_numbers(view: pd.DataFrame) -> dict:
    """KPI numbers for the reviews currently shown.

    - reviews / avg_rating / high_urgency: over every review shown
    - pct_positive / pct_negative: over the ANALYZED reviews shown (unanalyzed ones have no sentiment)
    """
    analyzed = view[view["analyzed_at"].notna()]
    n = len(analyzed)
    ratings = pd.to_numeric(view["rating"], errors="coerce")
    return {
        "reviews": len(view),
        "analyzed": n,
        "avg_rating": ratings.mean() if ratings.notna().any() else None,
        "pct_positive": (analyzed["sentiment"] == "positive").sum() / n * 100 if n else 0.0,
        "pct_negative": (analyzed["sentiment"] == "negative").sum() / n * 100 if n else 0.0,
        "high_urgency": int((view["urgency"] == "HIGH").sum()),
    }


def reply_quality(with_reply: pd.DataFrame) -> dict:
    """Numbers for the Reply quality tab, over reviews that have a suggested reply.
    % good is over RATED replies only; unrated replies are not counted as good or bad."""
    rated = with_reply[with_reply["reply_rating"].isin(["good", "bad"])]
    good = int((rated["reply_rating"] == "good").sum())
    by_language: pd.DataFrame | None = None
    if not rated.empty:
        by_language = (
            rated.assign(good=rated["reply_rating"] == "good")
            .groupby("language")["good"].agg(["mean", "size"]).reset_index()
            .rename(columns={"mean": "pct_good", "size": "rated"})
        )
        by_language["pct_good"] *= 100
        by_language["label"] = by_language.apply(lambda r: f"{r.pct_good:.0f}% of {r.rated}", axis=1)
    return {
        "replies": len(with_reply),
        "rated": len(rated),
        "bad": len(rated) - good,
        "pct_good": good / len(rated) * 100 if len(rated) else None,
        "by_language": by_language,
    }


SEARCH_COLUMNS =["review_id", "review_text", "summary", "suggested_reply"]


def search(view: pd.DataFrame, text: str) -> pd.DataFrame:
    """Reviews containing ALL the words typed (any order, any case), in the review text,
    the English summary, the reply or the ID. Works for Tamil, Tanglish and English:
    "cold" finds the Tamil review whose English summary says the food was cold."""
    words = text.lower().split()
    if not words:
        return view
    cols = view[SEARCH_COLUMNS].fillna("").astype(str)
    # str.cat always returns a Series (agg(..., axis=1) is typed as DataFrame | Series)
    haystack = cols.iloc[:, 0].str.cat(cols.iloc[:, 1:], sep=" ").str.lower()
    keep = pd.Series(True, index=view.index)
    for word in words:
        keep &= haystack.str.contains(word, regex=False)  # plain text, so "?" or "(" are safe
    return view[keep]


def excel_safe(value):
    """Customer text starting with = + - @ would run as a FORMULA in Excel (and show #NAME?
    or worse). A leading apostrophe makes Excel treat the cell as plain text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def excel_csv(df: pd.DataFrame) -> bytes:
    """CSV that opens correctly in Excel: Tamil text intact, no formulas, Windows line endings."""
    safe = df.astype(object).map(excel_safe)  # every cell; non-text values pass through
    # "utf-8-sig" adds a marker (BOM) so Excel reads the file as UTF-8 and shows Tamil correctly
    return safe.to_csv(index=False, lineterminator="\r\n").encode("utf-8-sig")
