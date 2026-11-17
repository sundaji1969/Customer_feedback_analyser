# 🔎 ReviewLens — AI Customer Feedback Analyzer

ReviewLens reads customer reviews (English, **தமிழ்** and **Tanglish**), tags each one with AI and shows the results on a colourful dashboard. Use it to find the reviews that need action first.

For every review the AI gives:

| Field | Values |
|---|---|
| **Sentiment** | positive · neutral · negative |
| **Category** | Product Quality, Delivery, Customer Service, Pricing, App/Website, Payment/Refund, Staff Behaviour, Cleanliness, Other |
| **Urgency** | 🔴 HIGH (health/safety, fraud, legal threat, abusive staff) · 🟠 MEDIUM (real complaint) · 🟢 LOW (praise, suggestions) |
| **Language** | English · Tamil · Tanglish · Other |
| **Summary** | one sentence in English |
| **Suggested reply** | a polite reply in the **same language and style** as the review |

---

## How it works

```
 CSV file ──► Streamlit dashboard ──► FastAPI backend ──► OpenAI (LangChain)
              (port 8502)             (port 8000)    │
                                                     └──► PostgreSQL (port 5432)
```

- **Frontend:** Streamlit + Plotly (`frontend/app.py`)
- **Backend:** FastAPI + SQLAlchemy (`backend/app/`)
- **AI:** LangChain + OpenAI `gpt-4o-mini` with structured output (`backend/app/analyzer.py`)
- **Database:** PostgreSQL 16

Reviews are tagged 5 at a time and saved every 20, so a failure part-way does not lose finished work. Re-uploading a file only re-tags reviews that are new or whose text changed.

---

## Quick start (Docker — recommended)

**You need:** Docker Desktop and an OpenAI API key.

1. Copy the settings file and fill in your values:
   ```
   copy .env.example .env
   ```
   Set `OPENAI_API_KEY` and change `POSTGRES_PASSWORD`.
2. Start everything:
   ```
   docker compose up -d --build
   ```
   The first build takes about 10 minutes (it installs the Python packages). Later builds are faster.
3. Open the dashboard at **http://localhost:8502**.
4. In the sidebar, upload `data/sample_reviews.csv` and click **Upload & analyze**.

| Command | What it does |
|---|---|
| `docker compose ps` | Show container status |
| `docker compose logs -f backend` | Watch backend logs |
| `docker compose down` | Stop everything (reviews are kept) |
| `docker compose down -v` | Stop and **delete all reviews** |
| `docker compose up -d --build` | Rebuild after code changes |

---

## Run without Docker (for development)

Only the database runs in Docker:

```
docker compose up -d db
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt -r frontend/requirements.txt
```

Then, in two terminals:

```
cd backend   &&  uvicorn app.main:app --reload
cd frontend  &&  streamlit run app.py --server.port 8502
```

Start Streamlit from inside the `frontend` folder, otherwise the colour theme in `frontend/.streamlit/config.toml` is not loaded.

Test the AI on its own: `cd backend && python -m app.analyzer`

---

## CSV format

The file must be **UTF-8** (in Excel: *Save As → CSV UTF-8*) with these columns:

| Column | Example | Notes |
|---|---|---|
| `review_id` | R001 | Unique. Uploading the same ID again updates that review. |
| `date` | 2026-10-01 | `YYYY-MM-DD` is read as year-month-day. Other formats are day-first (01/10/2026 = 1 Oct). Can be empty. |
| `platform` | Google, Zomato, Swiggy | Any text |
| `rating` | 1–5 | Can be empty |
| `review_text` | Biryani semma taste… | Rows with empty text are skipped |

Up to 2,000 rows per upload. Tagging takes roughly 1 second per review.

---

## Dashboard

- **Summary cards:** total reviews, average rating, % positive, % negative, high-urgency count
- **🚨 Action queue:** HIGH then MEDIUM reviews, with a ready-to-copy suggested reply
- **📊 Insights:** sentiment split, topics by sentiment, weekly trend, urgency by platform, languages
- **📋 All reviews:** full table and a CSV download (opens correctly in Excel, including Tamil)
- **Filters:** urgency, sentiment, category, platform, language, date range

Always read and edit suggested replies before posting them.

---

## API

Interactive docs: **http://localhost:8000/docs**

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/reviews/upload` | Upload a CSV, save and tag reviews |
| POST | `/reviews/analyze-pending` | Retry reviews that failed or were never tagged |
| GET | `/reviews` | List reviews (filters: `urgency`, `sentiment`, `category`, `platform`, `language`, `start_date`, `end_date`) |
| GET | `/reviews/export` | Download reviews as CSV (same filters) |
| DELETE | `/reviews?confirm=true` | Delete **all** reviews |

---

## Settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model used for tagging |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `reviewlens` | Database login |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | Database address (local runs) |
| `BACKEND_URL` | `http://localhost:8000` | Where the dashboard finds the API (local runs) |
| `FRONTEND_PORT` | `8502` | Dashboard port on your computer (Docker) |

Never commit `.env`. It is already listed in `.gitignore`.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot reach the backend" | Start the backend first. In Docker: `docker compose ps` and check `reviewlens-backend` is healthy. |
| "OPENAI_API_KEY is missing" | Put your real key in `.env`, then run `docker compose up -d` again. |
| "File is not UTF-8" | In Excel use *Save As → CSV UTF-8*. |
| Some reviews show as not analyzed | Click **Retry un-analyzed reviews** in the sidebar. |
| Port already in use | Change `FRONTEND_PORT` (or `POSTGRES_PORT`) in `.env`. |

---

## Tests

The backend has automated tests. They run offline in about a second: they use a throwaway
SQLite database and a fake AI, so they need **no OpenAI key, cost nothing, and never touch your real data**.

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest
```

They cover CSV upload and clean-up, re-uploads (no repeat AI charges), AI failures and retry,
every filter, CSV export (incl. Tamil text) and the delete safety check.

---

## Project structure

```
Customer-feedback_ai/
├── backend/
│   ├── app/
│   │   ├── main.py        # API endpoints
│   │   ├── analyzer.py    # AI prompt + tagging
│   │   ├── schemas.py     # AI output and API shapes
│   │   ├── models.py      # database table
│   │   ├── database.py    # DB connection
│   │   ├── config.py      # reads .env
│   │   └── init_db.py     # create tables manually
│   ├── tests/             # pytest tests (offline, fake AI)
│   ├── pytest.ini
│   ├── Dockerfile
│   ├── requirements.txt
│   └── requirements-dev.txt   # + pytest
├── frontend/
│   ├── app.py             # Streamlit dashboard
│   ├── .streamlit/config.toml   # colour theme
│   ├── Dockerfile
│   └── requirements.txt
├── data/sample_reviews.csv      # 30 test reviews
├── docker-compose.yml
├── .env.example
└── README.md
```
