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
