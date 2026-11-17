"""ReviewLens dashboard (Streamlit).

Run locally (from the frontend folder):  streamlit run app.py
The backend must be running first (see backend/app/main.py).
"""
import hmac
import os
from datetime import date
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import load_dotenv

from report import excel_csv, reply_quality, search, summary_numbers
from trends import latest_change, weekly_sentiment, weekly_trends

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

SENTIMENT_COLORS = {"positive": "#10b981", "neutral": "#94a3b8", "negative": "#f43f5e"}
URGENCY_COLORS = {"HIGH": "#f43f5e", "MEDIUM": "#f59e0b", "LOW": "#10b981"}
URGENCY_ORDER = ["HIGH", "MEDIUM", "LOW"]
PALETTE = ["#7c3aed", "#06b6d4", "#f59e0b", "#ec4899", "#10b981", "#3b82f6", "#f97316", "#8b5cf6", "#14b8a6"]

st.set_page_config(page_title="ReviewLens", page_icon="🔎", layout="wide")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input { font-family: 'Plus Jakarta Sans', sans-serif !important; }
.block-container { padding-top: 1.5rem; max-width: 1400px; }

/* Sidebar: deep gradient */
section[data-testid="stSidebar"] { background: linear-gradient(180deg, #1e1b4b 0%, #4c1d95 55%, #831843 100%); }
section[data-testid="stSidebar"] * { color: #f5f3ff !important; }
/* Widgets with a light background (inputs, date range, uploaded file, messages) need dark text */
section[data-testid="stSidebar"] [data-baseweb="select"] *,
section[data-testid="stSidebar"] [data-baseweb="input"] *,
section[data-testid="stSidebar"] [data-baseweb="base-input"] *,
section[data-testid="stSidebar"] [data-testid="stDateInput"] [data-baseweb] *,
section[data-testid="stSidebar"] [data-testid="stAlert"] *,
section[data-testid="stSidebar"] input {
  color: #1f2937 !important; -webkit-text-fill-color: #1f2937 !important; }
section[data-testid="stSidebar"] input::placeholder { color: #6b7280 !important; -webkit-text-fill-color: #6b7280 !important; }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] { background: rgba(255,255,255,.08); border: 1px dashed rgba(255,255,255,.4); }
section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * { color: #f5f3ff !important; }
/* Buttons */
.stButton > button, .stDownloadButton > button {
  background: linear-gradient(90deg, #7c3aed, #ec4899); color: #fff !important; border: 0;
  border-radius: 12px; font-weight: 700; padding: .55rem 1.1rem; box-shadow: 0 6px 18px rgba(124,58,237,.35);
  transition: transform .15s ease, box-shadow .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(236,72,153,.4); }

/* Hero */
.hero { background: linear-gradient(120deg, #7c3aed 0%, #3b82f6 40%, #06b6d4 70%, #10b981 100%);
  border-radius: 22px; padding: 28px 32px; color: #fff; margin-bottom: 22px; box-shadow: 0 12px 34px rgba(59,130,246,.30); }
.hero h1 { color: #fff; font-size: 2.1rem; font-weight: 800; margin: 0; padding: 0; }
.hero p { margin: 6px 0 0; opacity: .92; font-size: 1rem; }

/* KPI cards */
.kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 16px; margin-bottom: 18px; }
@media (max-width: 1000px) { .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.kpi { border-radius: 18px; padding: 18px 20px; color: #fff; box-shadow: 0 8px 22px rgba(0,0,0,.10); }
.kpi .label { font-size: .82rem; text-transform: uppercase; letter-spacing: .06em; opacity: .9; font-weight: 600; }
.kpi .value { font-size: 2rem; font-weight: 800; line-height: 1.2; margin-top: 4px; }
.k1 { background: linear-gradient(135deg, #6366f1, #8b5cf6); }
.k2 { background: linear-gradient(135deg, #f59e0b, #f97316); }
.k3 { background: linear-gradient(135deg, #10b981, #14b8a6); }
.k4 { background: linear-gradient(135deg, #f43f5e, #ec4899); }
.k5 { background: linear-gradient(135deg, #dc2626, #9333ea); }

/* Tabs as pills */
.stTabs [data-baseweb="tab-list"] { gap: 8px; background: #fff; padding: 6px; border-radius: 14px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.stTabs [data-baseweb="tab"] { border-radius: 10px; padding: 8px 18px; font-weight: 600; }
.stTabs [aria-selected="true"] { background: linear-gradient(90deg, #7c3aed, #3b82f6); color: #fff !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none; }

/* Cards for charts and queue items */
[data-testid="stPlotlyChart"], [data-testid="stExpander"] { background: #fff; border-radius: 16px; box-shadow: 0 4px 16px rgba(0,0,0,.06); }
[data-testid="stPlotlyChart"] { padding: 8px; }
[data-testid="stExpander"] { border: 0 !important; margin-bottom: 10px; }
.urg-HIGH [data-testid="stExpander"] { border-left: 6px solid #f43f5e !important; }
.chip { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: .78rem; font-weight: 700; margin-right: 6px; color: #fff; }
</style>
""",
    unsafe_allow_html=True,
)


def style_fig(fig):
    """Shared modern look for every chart."""
    fig.update_layout(
        template="plotly_white",
        font=dict(family="Plus Jakarta Sans, sans-serif", size=13),
        title=dict(font=dict(size=17, color="#1f2937")),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(orientation="h", y=-0.15, title=None),
        colorway=PALETTE,
    )
    return fig


# ---------- password (only when DASHBOARD_PASSWORD is set, e.g. on a public server) ----------

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

if DASHBOARD_PASSWORD and not st.session_state.get("logged_in"):
    st.markdown('<div class="hero"><h1>🔎 ReviewLens</h1><p>Please log in to continue.</p></div>',
                unsafe_allow_html=True)
    with st.form("login"):
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Log in"):
            if hmac.compare_digest(password.encode(), DASHBOARD_PASSWORD.encode()):
                st.session_state["logged_in"] = True
                st.rerun()
            st.error("Wrong password.")
    st.stop()


# ---------- backend calls ----------

def backend_ok() -> bool:
    try:
        return requests.get(f"{BACKEND_URL}/health", timeout=3).ok
    except requests.RequestException:
        return False


MAX_REVIEWS = 20000  # the API's upper limit; the dashboard warns if there are more


@st.cache_data(ttl=60, show_spinner=False)
def load_reviews() -> pd.DataFrame:
    resp = requests.get(f"{BACKEND_URL}/reviews", params={"limit": MAX_REVIEWS}, timeout=60)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    for column in ("reply_rating", "reply_note"):
        if column not in df:
            df[column] = None
    return df


def show_error(resp: requests.Response):
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    st.sidebar.error(f"Error {resp.status_code}: {detail}")


def show_alert(message: str | None):
    """Result of the high-urgency email (only when one was due)."""
    if not message:
        return
    if "FAILED" in message:
        st.sidebar.warning(f"📧 {message}")
    else:
        st.sidebar.info(f"📧 {message}")


def save_rating(review_id: str, rating: str | None, note_key: str | None = None):
    """Button callback: store a 👍/👎 for one suggested reply."""
    note = st.session_state.get(note_key, "") if note_key else None
    try:
        resp = requests.post(f"{BACKEND_URL}/reviews/rate-reply",
                             json={"review_id": review_id, "rating": rating, "note": note}, timeout=15)
    except requests.RequestException as exc:
        st.toast(f"Could not save rating: {exc}", icon="⚠️")
        return
    if not resp.ok:
        st.toast(f"Could not save rating (error {resp.status_code}).", icon="⚠️")
        return
    load_reviews.clear()
    st.toast({"good": "Marked as a good reply 👍", "bad": "Marked as a bad reply 👎"}.get(rating, "Rating cleared"))


def rating_widget(r, where: str):
    """👍/👎 buttons and an optional note for one suggested reply."""
    if not r["suggested_reply"]:
        return
    key = f"{where}-{r['review_id']}"
    current = r["reply_rating"] if isinstance(r["reply_rating"], str) else None
    if current:
        note = f" — “{r['reply_note']}”" if isinstance(r["reply_note"], str) and r["reply_note"] else ""
        st.caption(f"Rated: {'👍 good' if current == 'good' else '👎 bad'}{note}")
    good, bad, note_col, clear = st.columns([1, 1, 4, 1], vertical_alignment="bottom")
    good.button("👍 Good", key=f"good-{key}", on_click=save_rating, args=(r["review_id"], "good"),
                disabled=current == "good")
    note_col.text_input("What should change? (optional, saved with 👎)", key=f"note-{key}",
                        placeholder="e.g. too formal, wrong language, missed the refund")
    bad.button("👎 Bad", key=f"bad-{key}", on_click=save_rating, args=(r["review_id"], "bad", f"note-{key}"))
    if current:
        clear.button("Clear", key=f"clear-{key}", on_click=save_rating, args=(r["review_id"], None))


# ---------- sidebar: upload ----------

st.sidebar.title("🔎 ReviewLens")
if DASHBOARD_PASSWORD and st.sidebar.button("Log out"):
    st.session_state["logged_in"] = False
    st.rerun()

if not backend_ok():
    st.error(f"Cannot reach the backend at {BACKEND_URL}. Start it with `uvicorn app.main:app --reload`.")
    st.stop()

st.sidebar.subheader("1. Upload reviews")
uploaded = st.sidebar.file_uploader(
    "CSV with columns: review_id, date, platform, rating, review_text", type="csv"
)
if uploaded is not None and st.sidebar.button("Upload & analyze", type="primary"):
    with st.spinner("Saving and tagging reviews with AI... (about 1 second per review)"):
        try:
            resp = requests.post(
                f"{BACKEND_URL}/reviews/upload",
                files={"file": (uploaded.name, uploaded.getvalue(), "text/csv")},
                timeout=1800,
            )
        except requests.RequestException as exc:
            st.sidebar.error(f"Upload failed: {exc}")
            resp = None
    if resp is not None:
        if resp.ok:
            r = resp.json()
            st.sidebar.success(
                f"{r['rows_in_file']} rows: {r['new_reviews']} new, {r['updated_reviews']} updated, "
                f"{r['analyzed']} analyzed, {r['failed']} failed."
            )
            for err in r.get("errors", []):
                st.sidebar.warning(err)
            show_alert(r.get("alert"))
            load_reviews.clear()
        else:
            show_error(resp)

if st.sidebar.button("Retry un-analyzed reviews"):
    with st.spinner("Analyzing..."):
        resp = requests.post(f"{BACKEND_URL}/reviews/analyze-pending", timeout=1800)
    if resp.ok:
        r = resp.json()
        st.sidebar.success(f"{r['analyzed']} analyzed, {r['failed']} failed.")
        show_alert(r.get("alert"))
        load_reviews.clear()
    else:
        show_error(resp)

# ---------- load data ----------

try:
    df = load_reviews()
except requests.RequestException as exc:
    st.error(f"Could not load reviews: {exc}")
    st.stop()

if len(df) >= MAX_REVIEWS:
    st.warning(f"Showing the newest {MAX_REVIEWS:,} reviews only. Older reviews are not counted below.")

if df.empty:
    st.title("ReviewLens")
    st.info("No reviews yet. Upload a CSV from the sidebar (try `data/sample_reviews.csv`).")
    st.stop()

# ---------- sidebar: filters ----------

st.sidebar.subheader("2. Filters")
f_search = st.sidebar.text_input(
    "🔍 Search", placeholder="e.g. biryani, refund, R012",
    help="Finds reviews containing all these words in the review, the English summary, the reply or the ID.",
)


def multi(label: str, column: str, order: list[str] | None = None) -> list[str]:
    options = sorted(df[column].dropna().unique().tolist())
    if order:
        options = [o for o in order if o in options] + [o for o in options if o not in order]
    return st.sidebar.multiselect(label, options, placeholder="All")


f_urgency = multi("Urgency", "urgency", URGENCY_ORDER)
f_sentiment = multi("Sentiment", "sentiment", ["negative", "neutral", "positive"])
f_category = multi("Category", "category")
f_platform = multi("Platform", "platform")
f_language = multi("Language", "language")

dates = df["date"].dropna()
f_dates = None
if not dates.empty:
    min_d, max_d = dates.min().date(), dates.max().date()
    f_dates = st.sidebar.date_input("Date range", (min_d, max_d), min_value=min_d, max_value=max_d)

view = df.copy()
for column, chosen in [
    ("urgency", f_urgency), ("sentiment", f_sentiment), ("category", f_category),
    ("platform", f_platform), ("language", f_language),
]:
    if chosen:
        view = view[view[column].isin(chosen)]
if isinstance(f_dates, tuple) and len(f_dates) == 2:
    start, end = (pd.Timestamp(d) for d in f_dates)
    view = view[view["date"].isna() | view["date"].between(start, end)]
view = search(view, f_search)

# ---------- KPIs ----------

st.markdown(
    f"""<div class="hero"><h1>🔎 ReviewLens</h1>
    <p>AI-tagged customer reviews in English, தமிழ் &amp; Tanglish · showing <b>{len(view)}</b> of {len(df)} reviews</p></div>""",
    unsafe_allow_html=True,
)

analyzed = view[view["analyzed_at"].notna()]
nums = summary_numbers(view)  # calculated with pandas from the table below, never by the AI
avg = "–" if nums["avg_rating"] is None else f"{nums['avg_rating']:.1f}★"
cards = [("k1", "📝 Reviews", nums["reviews"]), ("k2", "⭐ Avg rating", avg),
         ("k3", "😊 Positive", f"{nums['pct_positive']:.0f}%"), ("k4", "😞 Negative", f"{nums['pct_negative']:.0f}%"),
         ("k5", "🚨 High urgency", nums["high_urgency"])]
st.markdown(
    '<div class="kpis">'
    + "".join(f'<div class="kpi {c}"><div class="label">{l}</div><div class="value">{v}</div></div>' for c, l, v in cards)
    + "</div>",
    unsafe_allow_html=True,
)

not_done = len(view) - len(analyzed)
if not_done:
    st.warning(f"{not_done} review(s) are not analyzed yet. Use **Retry un-analyzed reviews** in the sidebar.")

# ---------- tabs ----------

tab_urgent, tab_charts, tab_trends, tab_quality, tab_all = st.tabs(
    ["🚨 Action queue", "📊 Insights", "📈 Trends", "⭐ Reply quality", "📋 All reviews"]
)

with tab_urgent:
    queue = view[view["urgency"].isin(["HIGH", "MEDIUM"])].copy()
    queue["_order"] = queue["urgency"].map({"HIGH": 0, "MEDIUM": 1})
    queue = queue.sort_values(["_order", "date"], ascending=[True, False])
    if queue.empty:
        st.success("Nothing urgent. 🎉")
    for _, r in queue.iterrows():
        icon = "🔴" if r["urgency"] == "HIGH" else "🟠"
        when = r["date"].strftime("%d %b %Y") if pd.notna(r["date"]) else "no date"
        stars = f"{int(r['rating'])}★" if pd.notna(r["rating"]) else ""
        with st.expander(f"{icon} {r['urgency']} · {r['category']} · {r['platform']} · {stars} · {when} — {r['summary']}"):
            st.markdown(
                f'<span class="chip" style="background:{URGENCY_COLORS[r["urgency"]]}">{r["urgency"]}</span>'
                f'<span class="chip" style="background:{SENTIMENT_COLORS.get(r["sentiment"], "#94a3b8")}">{r["sentiment"]}</span>'
                f'<span class="chip" style="background:#7c3aed">{r["category"]}</span>'
                f'<span class="chip" style="background:#06b6d4">{r["language"]}</span>',
                unsafe_allow_html=True,
            )
            st.markdown("**Customer wrote:**")
            st.write(r["review_text"])
            st.markdown(f"**Suggested reply** ({r['language']}) — copy and edit before posting:")
            st.code(r["suggested_reply"] or "", language=None, wrap_lines=True)
            rating_widget(r, "queue")

with tab_charts:
    if analyzed.empty:
        st.info("No analyzed reviews in this selection.")
    else:
        left, right = st.columns(2)
        with left:
            counts = analyzed["sentiment"].value_counts().reset_index()
            fig = px.pie(counts, names="sentiment", values="count", hole=0.5, title="Sentiment",
                         color="sentiment", color_discrete_map=SENTIMENT_COLORS)
            st.plotly_chart(style_fig(fig), width="stretch")
        with right:
            cat = analyzed.groupby(["category", "sentiment"]).size().reset_index(name="count")
            order = analyzed["category"].value_counts().index.tolist()
            fig = px.bar(cat, y="category", x="count", color="sentiment", orientation="h",
                         title="Topics by sentiment", color_discrete_map=SENTIMENT_COLORS,
                         category_orders={"category": order})
            st.plotly_chart(style_fig(fig), width="stretch")

        left, right = st.columns(2)
        with left:
            plat = analyzed.groupby(["platform", "urgency"]).size().reset_index(name="count")
            fig = px.bar(plat, x="platform", y="count", color="urgency", title="Urgency by platform",
                         color_discrete_map=URGENCY_COLORS, category_orders={"urgency": URGENCY_ORDER})
            st.plotly_chart(style_fig(fig), width="stretch")
        with right:
            lang = analyzed["language"].value_counts().reset_index()
            fig = px.bar(lang, x="language", y="count", title="Review language", color="language",
                         color_discrete_sequence=PALETTE)
            st.plotly_chart(style_fig(fig), width="stretch")

with tab_trends:
    trends = weekly_trends(analyzed)
    if len(trends) < 2:
        st.info("Trends need analyzed reviews with dates from at least 2 different weeks.")
    else:
        change = latest_change(trends)
        week = change["week"]
        st.markdown(
            f"**Latest week** (week of {week:%d %b %Y}) compared with the week before. "
            "Weeks are Monday to Sunday; reviews without a date are left out."
        )

        def fmt(value, pattern):
            return "–" if pd.isna(value) else pattern.format(value)

        def delta(diff, pattern):
            return None if diff is None else pattern.format(diff)

        c1, c2, c3, c4 = st.columns(4)
        n, d = change["reviews"]
        c1.metric("📝 Reviews", fmt(n, "{:.0f}"), delta(d, "{:+.0f}"), delta_color="off", border=True)
        n, d = change["avg_rating"]
        c2.metric("⭐ Avg rating", fmt(n, "{:.1f}★"), delta(d, "{:+.1f}★"), border=True)
        n, d = change["pct_negative"]
        c3.metric("😞 Negative", fmt(n, "{:.0f}%"), delta(d, "{:+.0f} pts"), delta_color="inverse", border=True)
        n, d = change["high_urgency"]
        c4.metric("🚨 High urgency", fmt(n, "{:.0f}"), delta(d, "{:+.0f}"), delta_color="inverse", border=True)

        weekly = trends.reset_index()
        left, right = st.columns(2)
        with left:
            fig = px.line(weekly, x="week", y="avg_rating", markers=True, title="Average rating per week",
                          labels={"week": "Week", "avg_rating": "Avg rating"}, range_y=[0.5, 5.5])
            fig.update_traces(line_color="#f59e0b", connectgaps=False)
            st.plotly_chart(style_fig(fig), width="stretch")
        with right:
            fig = px.line(weekly, x="week", y="pct_negative", markers=True, title="% negative reviews per week",
                          labels={"week": "Week", "pct_negative": "% negative"}, range_y=[-5, 105])
            fig.update_traces(line_color=SENTIMENT_COLORS["negative"], connectgaps=False)
            st.plotly_chart(style_fig(fig), width="stretch")

        left, right = st.columns(2)
        with left:
            fig = px.bar(weekly_sentiment(analyzed), x="week", y="count", color="sentiment",
                         title="Reviews per week by sentiment", color_discrete_map=SENTIMENT_COLORS,
                         category_orders={"sentiment": ["negative", "neutral", "positive"]},
                         labels={"week": "Week", "count": "Reviews"})
            st.plotly_chart(style_fig(fig), width="stretch")
        with right:
            fig = px.bar(weekly, x="week", y="high_urgency", title="High-urgency reviews per week",
                         labels={"week": "Week", "high_urgency": "High urgency"})
            fig.update_traces(marker_color=URGENCY_COLORS["HIGH"])
            st.plotly_chart(style_fig(fig), width="stretch")

with tab_quality:
    with_reply = view[view["suggested_reply"].notna()]
    q = reply_quality(with_reply)
    st.markdown("Staff rate the AI's suggested replies with 👍 / 👎. "
                "Use the 👎 notes to see what the AI gets wrong, then improve the prompt.")
    c1, c2, c3 = st.columns(3)
    c1.metric("📝 Replies rated", f"{q['rated']} of {q['replies']}", border=True)
    c2.metric("👍 Rated good", "–" if q["pct_good"] is None else f"{q['pct_good']:.0f}%", border=True)
    c3.metric("👎 Rated bad", q["bad"], border=True)

    if q["by_language"] is not None:
        fig = px.bar(q["by_language"], x="language", y="pct_good", text="label",
                     title="% of rated replies that are good, by language",
                     labels={"language": "Language", "pct_good": "% good"}, range_y=[0, 105])
        fig.update_traces(marker_color=SENTIMENT_COLORS["positive"], textposition="outside")
        st.plotly_chart(style_fig(fig), width="stretch")

    unrated = with_reply[with_reply["reply_rating"].isna()].sort_values("date", ascending=False)
    st.subheader(f"Rate more replies ({len(unrated)} not rated yet)")
    if unrated.empty:
        st.success("Every reply in this selection is rated. 🎉")
    for _, r in unrated.head(10).iterrows():
        with st.expander(f"{r['language']} · {r['sentiment']} · {r['urgency']} — {r['summary']}"):
            st.markdown("**Customer wrote:**")
            st.write(r["review_text"])
            st.markdown("**Suggested reply:**")
            st.code(r["suggested_reply"], language=None, wrap_lines=True)
            rating_widget(r, "rate")
    if len(unrated) > 10:
        st.caption("Showing 10. Rate these and the next ones appear, or use the filters to focus on one language.")

    bad = with_reply[with_reply["reply_rating"] == "bad"]
    st.subheader(f"Replies marked 👎 ({len(bad)})")
    if bad.empty:
        st.info("No replies marked bad in this selection.")
    else:
        st.dataframe(bad[["review_id", "language", "urgency", "review_text", "suggested_reply", "reply_note"]],
                     width="stretch", hide_index=True,
                     column_config={"reply_note": "Staff note"})

with tab_all:
    columns = ["review_id", "date", "platform", "rating", "sentiment", "urgency", "category",
               "language", "summary", "review_text", "suggested_reply", "reply_rating", "reply_note"]
    st.dataframe(
        view[columns],
        width="stretch",
        hide_index=True,
        column_config={"date": st.column_config.DateColumn(format="DD MMM YYYY")},
    )
    export = view.drop(columns=["analyzed_at"]).copy()
    export["date"] = export["date"].dt.date
    st.download_button(
        "⬇️ Download filtered reviews (CSV)",
        data=excel_csv(export),  # Tamil shows correctly, customer text can't run as a formula
        file_name=f"reviewlens_export_{date.today().isoformat()}.csv",
        mime="text/csv",
    )
