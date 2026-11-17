"""ReviewLens backend API (FastAPI).

Run locally (from the backend folder):  uvicorn app.main:app --reload
Then open http://localhost:8000/docs to try every endpoint in the browser.
"""
import io
from contextlib import asynccontextmanager
from datetime import date, datetime

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .analyzer import analyze_reviews
from .database import get_db, init_db
from .models import Review
from .schemas import ReviewOut, UploadResult

REQUIRED_COLUMNS = ["review_id", "date", "platform", "rating", "review_text"]
MAX_ROWS_PER_UPLOAD = 2000
ANALYZE_CHUNK = 20  # save progress to the database every 20 reviews


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # create tables on startup if needed
    yield


app = FastAPI(title="ReviewLens API", version="1.0", lifespan=lifespan)


# ---------- helpers ----------

def _clean(value):
    """Turn pandas' empty values (NaN/NaT) into None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _read_csv(raw: bytes) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig", dtype=str)
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not UTF-8. In Excel use 'Save As -> CSV UTF-8'.")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read CSV: {exc}")

    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise HTTPException(400, f"CSV is missing columns: {', '.join(missing)}")
    if len(df) > MAX_ROWS_PER_UPLOAD:
        raise HTTPException(400, f"Too many rows ({len(df)}). Max is {MAX_ROWS_PER_UPLOAD} per upload.")

    df = df[REQUIRED_COLUMNS].copy()
    df["review_id"] = df["review_id"].fillna("").astype(str).str.strip()
    df["review_text"] = df["review_text"].fillna("").astype(str).str.strip()
    df = df[(df["review_id"] != "") & (df["review_text"] != "")]
    df = df.drop_duplicates(subset="review_id", keep="last")

    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").round()
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="mixed", dayfirst=True).dt.date
    return df


def _analyze_pending(db: Session, review_ids: list[str] | None = None) -> tuple[int, int, list[str]]:
    """Run the AI on reviews that have not been analyzed yet."""
    query = select(Review).where(Review.analyzed_at.is_(None))
    if review_ids is not None:
        query = query.where(Review.review_id.in_(review_ids))
    pending = db.scalars(query).all()

    analyzed, failed, errors = 0, 0, []
    for start in range(0, len(pending), ANALYZE_CHUNK):
        chunk = pending[start : start + ANALYZE_CHUNK]
        try:
            results = analyze_reviews(
                [{"review_text": r.review_text, "rating": r.rating, "platform": r.platform} for r in chunk]
            )
        except RuntimeError as exc:  # e.g. missing API key
            raise HTTPException(500, str(exc))

        for review, result in zip(chunk, results):
            if isinstance(result, Exception):
                failed += 1
                if len(errors) < 5:
                    errors.append(f"{review.review_id}: {type(result).__name__}: {result}"[:300])
                continue
            for field, value in result.model_dump().items():
                setattr(review, field, value)
            review.analyzed_at = datetime.now()
            analyzed += 1
        db.commit()
    return analyzed, failed, errors


def _filtered_query(urgency, sentiment, category, platform, language, start_date, end_date):
    query = select(Review)
    if urgency:
        query = query.where(Review.urgency == urgency.upper())
    if sentiment:
        query = query.where(Review.sentiment == sentiment.lower())
    if category:
        query = query.where(Review.category == category)
    if platform:
        query = query.where(Review.platform == platform)
    if language:
        query = query.where(Review.language == language)
    if start_date:
        query = query.where(Review.date >= start_date)
    if end_date:
        query = query.where(Review.date <= end_date)
    return query.order_by(Review.date.desc().nulls_last(), Review.id.desc())


# ---------- endpoints ----------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/reviews/upload", response_model=UploadResult)
def upload_reviews(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a CSV, save the reviews, and tag new/changed ones with AI."""
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(400, "Please upload a .csv file.")
    df = _read_csv(file.file.read())

    ids = df["review_id"].tolist()
    existing = {r.review_id: r for r in db.scalars(select(Review).where(Review.review_id.in_(ids)))}

    new_count, updated_count = 0, 0
    for row in df.to_dict("records"):
        rating = _clean(row["rating"])
        data = {
            "review_id": row["review_id"],
            "date": _clean(row["date"]),
            "platform": _clean(row["platform"]),
            "rating": int(rating) if rating is not None else None,
            "review_text": row["review_text"],
        }
        review = existing.get(data["review_id"])
        if review is None:
            db.add(Review(**data))
            new_count += 1
        else:
            if review.review_text != data["review_text"]:
                review.analyzed_at = None  # text changed -> analyze again
            for key, value in data.items():
                setattr(review, key, value)
            updated_count += 1
    db.commit()

    analyzed, failed, errors = _analyze_pending(db, ids)
    return UploadResult(
        rows_in_file=len(df),
        new_reviews=new_count,
        updated_reviews=updated_count,
        analyzed=analyzed,
        failed=failed,
        errors=errors,
    )


@app.post("/reviews/analyze-pending")
def analyze_pending(db: Session = Depends(get_db)):
    """Retry the AI on any reviews that failed or were never analyzed."""
    analyzed, failed, errors = _analyze_pending(db)
    return {"analyzed": analyzed, "failed": failed, "errors": errors}


@app.get("/reviews", response_model=list[ReviewOut])
def list_reviews(
    urgency: str | None = Query(None, description="HIGH, MEDIUM or LOW"),
    sentiment: str | None = None,
    category: str | None = None,
    platform: str | None = None,
    language: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(5000, le=20000),
    db: Session = Depends(get_db),
):
    query = _filtered_query(urgency, sentiment, category, platform, language, start_date, end_date)
    return db.scalars(query.limit(limit)).all()


@app.get("/reviews/export")
def export_reviews(
    urgency: str | None = None,
    sentiment: str | None = None,
    category: str | None = None,
    platform: str | None = None,
    language: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    """Download reviews + AI tags as CSV (opens correctly in Excel, incl. Tamil)."""
    query = _filtered_query(urgency, sentiment, category, platform, language, start_date, end_date)
    rows = db.scalars(query).all()
    df = pd.DataFrame(
        [ReviewOut.model_validate(r).model_dump() for r in rows],
        columns=list(ReviewOut.model_fields),
    )
    # "utf-8-sig" adds a marker so Excel shows Tamil text correctly
    data = df.to_csv(index=False).encode("utf-8-sig")
    filename = f"reviewlens_export_{date.today().isoformat()}.csv"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/reviews")
def delete_all_reviews(confirm: bool = False, db: Session = Depends(get_db)):
    """Delete ALL reviews (for testing). Call with ?confirm=true."""
    if not confirm:
        raise HTTPException(400, "Add ?confirm=true to really delete everything.")
    result = db.execute(delete(Review))
    db.commit()
    return {"deleted": result.rowcount}
