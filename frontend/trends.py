"""Week-by-week trend numbers for the dashboard (plain pandas, no Streamlit, so it is easy to test)."""
import pandas as pd

SENTIMENTS = ["positive", "neutral", "negative"]


def _week_start(dates: pd.Series) -> pd.Series:
    """Monday of each date's week."""
    return dates.dt.to_period("W-SUN").dt.start_time


def _all_weeks(starts: pd.Series) -> pd.DatetimeIndex:
    """Every Monday from the first to the last week, so empty weeks show as 0, not a gap."""
    return pd.date_range(starts.min(), starts.max(), freq="W-MON", name="week")


def weekly_trends(df: pd.DataFrame) -> pd.DataFrame:
    """One row per week (index = Monday) with:
    reviews, avg_rating, pct_negative, high_urgency.

    `df` needs columns: date, rating, sentiment, urgency. Rows without a date are ignored.
    Weeks with no reviews get reviews=0, high_urgency=0, and empty avg_rating / pct_negative.
    """
    columns = ["reviews", "avg_rating", "pct_negative", "high_urgency"]
    dated = df.dropna(subset=["date"])
    if dated.empty:
        return pd.DataFrame(columns=columns, index=pd.DatetimeIndex([], name="week"))

    dated = dated.assign(week=_week_start(dated["date"]))
    grouped = dated.groupby("week")
    out = pd.DataFrame(
        {
            "reviews": grouped.size(),
            "avg_rating": grouped["rating"].mean(),
            "pct_negative": grouped["sentiment"].apply(lambda s: (s == "negative").mean() * 100),
            "high_urgency": grouped["urgency"].apply(lambda s: int((s == "HIGH").sum())),
        }
    ).reindex(_all_weeks(dated["week"]))
    out[["reviews", "high_urgency"]] = out[["reviews", "high_urgency"]].fillna(0).astype(int)
    return out[columns]


def weekly_sentiment(df: pd.DataFrame) -> pd.DataFrame:
    """Long table (week, sentiment, count) with every week x sentiment present (0 if none)."""
    dated = df.dropna(subset=["date"])
    if dated.empty:
        return pd.DataFrame(columns=["week", "sentiment", "count"])
    dated = dated.assign(week=_week_start(dated["date"]))
    counts = dated.groupby(["week", "sentiment"]).size()
    full = pd.MultiIndex.from_product([_all_weeks(dated["week"]), SENTIMENTS], names=["week", "sentiment"])
    return counts.reindex(full, fill_value=0).reset_index(name="count")


def latest_change(trends: pd.DataFrame) -> dict | None:
    """Compare the latest week with the week before.

    Returns {"week": Monday, column: (latest value, change vs previous week), ...},
    or None if there are fewer than 2 weeks. A change is None when either week has no value.
    """
    if len(trends) < 2:
        return None
    latest, previous = trends.iloc[-1], trends.iloc[-2]
    result = {"week": trends.index[-1]}
    for column in trends.columns:
        now, before = latest[column], previous[column]
        result[column] = (now, None if pd.isna(now) or pd.isna(before) else now - before)
    return result
