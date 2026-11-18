# 🔎 ReviewLens — AI Customer Feedback Analyzer

ReviewLens reads customer reviews (English, **தமிழ்** and **Tanglish**), tags each one with AI and shows the results on a colourful dashboard. Use it to find the reviews that need action first.

**🌐 Live site:** https://service.reviewlens.sundajigenai.tech

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

Each review gets two AI calls: one for the tags at temperature 0 (consistent), then one for the suggested reply at 0.4 (natural wording; it sees the tags, so HIGH-urgency reviews get a more serious reply). Reviews are tagged 5 at a time and saved every 20, so a failure part-way does not lose finished work. Re-uploading a file only re-tags reviews that are new or whose text changed.

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

Up to 2,000 rows per upload. Tested with 220 real reviews: about 85 seconds (roughly 0.4 s per review), no failures.

**Quality checks on every review:** all 6 AI fields are filled; sentiment, category, urgency and language must come from the fixed lists; the summary must be English (never Tamil script) even for Tamil/Tanglish reviews. If the AI breaks a rule it is asked once more; if it still fails, the review is marked failed and can be retried from the sidebar.

**Numbers are never guessed by the AI.** Every count, percentage and average on the dashboard is calculated with pandas from the review table (`frontend/report.py`, `frontend/trends.py`).

**Excel-safe CSV:** exports are UTF-8 with a BOM (Tamil shows correctly) and any cell starting with `=`, `+`, `-` or `@` gets a leading `'` so customer text can never run as an Excel formula.

---

## Dashboard

- **Summary cards:** total reviews, average rating, % positive, % negative, high-urgency count
- **🚨 Action queue:** HIGH then MEDIUM reviews, with a ready-to-copy suggested reply and 👍/👎 to rate it
- **📊 Insights:** sentiment split, topics by sentiment, urgency by platform, languages
- **📈 Trends:** latest week vs the week before (reviews, avg rating, % negative, high urgency, each with ▲/▼ change), plus weekly charts of rating, % negative, sentiment and high-urgency reviews. Weeks run Monday–Sunday; weeks with no reviews show as 0, not skipped.
- **⭐ Reply quality:** staff rate suggested replies 👍/👎 with an optional note. Shows % rated good
  (overall and per language), more replies to rate, and every 👎 reply with its note, so you can
  see what the AI gets wrong and improve the prompt. A rating is cleared when the AI writes a new reply.
- **📋 All reviews:** full table and a CSV download of exactly what is shown (opens correctly in Excel, including Tamil)
- **Filters:** 🔍 search (all words, in the review, English summary, reply or ID — so `cold` also finds
  a Tamil review whose summary says the food was cold), urgency, sentiment, category, platform, language, date range
- **📧 Email alert (optional):** after an upload, one email lists every new HIGH-urgency review with the
  customer's text and the suggested reply. Set `ALERT_EMAIL_TO` and the `SMTP_*` settings to switch it on.
  The dashboard shows whether the email was sent; a mail problem never stops the upload.

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
| POST | `/reviews/rate-reply` | Rate a suggested reply: `{"review_id": "R1", "rating": "good" or "bad" or null, "note": "..."}` |
| DELETE | `/reviews?confirm=true` | Delete **all** reviews |

---

## Deploy to a server (e.g. Hostinger VPS)

Use `docker-compose.prod.yml`, not `docker-compose.yml`. It is made for a public server:

- Only the dashboard is open to the internet. The database and API have no public ports.
- The dashboard asks for a password (`DASHBOARD_PASSWORD`).
  It can be changed in the dashboard (sidebar → **🔑 Change password**), and a forgotten one is
  reset with a 6-digit code emailed to `RESET_EMAIL_TO` (see [Dashboard password](#dashboard-password)).
- Docker refuses to start if a required secret is missing.

Set these environment variables on the server (in Hostinger's Docker Manager, or in a `.env` file next to the compose file):

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | yes | Your OpenAI key |
| `POSTGRES_PASSWORD` | yes | Long random password, **letters and numbers only** |
| `DASHBOARD_PASSWORD` | yes | First password people type to open the dashboard |
| `RESET_EMAIL_TO` | no | Gets the "Forgot password?" code (default: `ALERT_EMAIL_TO`). Needs the SMTP settings. |
| `FRONTEND_PORT` | no | Port on the server, default `8502` |

```bash
git clone <this repo> && cd Customer-feedback_ai
docker compose -f docker-compose.prod.yml up -d --build
```

Then open `http://<server-ip>:8502` (allow that port in the VPS firewall).
The server database starts empty: upload your CSV from the dashboard.

**HTTPS on a server that already runs Traefik** (e.g. Hostinger's n8n template, which owns ports 80/443):
use the add-on `deploy/docker-compose.traefik.yml`. The dashboard is then served at
`https://<your domain>` with a free certificate, and port 8502 is closed. Add to the server's `.env`:

```bash
SITE_ADDRESS=reviews.example.com     # DNS A record must point at the server
TRAEFIK_NETWORK=n8n_default          # find it with: docker network ls
TRAEFIK_CERTRESOLVER=mytlschallenge
```

```bash
docker compose -p reviewlens -f docker-compose.prod.yml -f deploy/docker-compose.traefik.yml up -d --build
```

Update later with `git pull` and the same command (the database is kept).

### Dashboard password

- **First password:** `DASHBOARD_PASSWORD` in the server's `.env`.
- **Change it:** log in, then sidebar → **🔑 Change password**. From then on the new password is stored
  (hashed, never in plain text) in the database, and `DASHBOARD_PASSWORD` no longer works.
- **Forgot it:** on the login page open **Forgot password?** → **Email me a reset code**. A 6-digit code goes to
  `RESET_EMAIL_TO` (or `ALERT_EMAIL_TO`) using the SMTP settings. It works for 15 minutes; 5 wrong codes cancel it.
- **Too many wrong passwords:** after 10 in a row, logins are blocked for 5 minutes.
- **Lost the password and the email:** on the server run
  `docker exec reviewlens-db-1 psql -U reviewlens -c "DELETE FROM dashboard_auth;"` —
  `DASHBOARD_PASSWORD` from `.env` works again.
- People already logged in stay logged in after a change until they log out or close the tab.

---

## Settings (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | Required |
| `TAG_MODEL` | `gpt-4o-mini` | OpenAI model for tags (sentiment, category, urgency, language, summary). A small model scores as well as big ones here. The old `OPENAI_MODEL` setting still works for this. |
| `REPLY_MODEL` | `gpt-5.5` | OpenAI model for suggested replies. A stronger model writes better Tamil/Tanglish and more specific replies. |
| `TAG_TEMPERATURE` | `0` | Randomness for tags (sentiment, category, urgency, language, summary). Keep at 0 so the same review always gets the same tags. |
| `REPLY_TEMPERATURE` | `0.4` | Randomness for the suggested reply. 0.3–0.5 sounds natural; above 0.7 replies can drift off-script. |
| `AI_CONCURRENCY` | `8` | Reviews sent to OpenAI at the same time. Lower it if you hit OpenAI rate limits. |
| `AI_TIMEOUT_SECONDS` | `60` | Max time for one AI call, so a stuck call can't hang an upload. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `reviewlens` | Database login |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | Database address (local runs) |
| `BACKEND_URL` | `http://localhost:8000` | Where the dashboard finds the API (local runs) |
| `FRONTEND_PORT` | `8502` | Dashboard port on your computer (Docker) |
| `DASHBOARD_PASSWORD` | — (off) | If set, the dashboard asks for a password; this is the first one (it can be changed in the dashboard). Required in `docker-compose.prod.yml`. |
| `RESET_EMAIL_TO` | `ALERT_EMAIL_TO` | Gets the "Forgot password?" reset code. |
| `ALERT_EMAIL_TO` | — (off) | Who gets the high-urgency email. Several: `a@x.com, b@y.com` |
| `SMTP_HOST` / `SMTP_PORT` | — / `587` | Mail server. Gmail: `smtp.gmail.com`, `587`. Port `465` uses SSL. |
| `SMTP_USER` / `SMTP_PASSWORD` | — | Mail login. For Gmail use an **App Password**, not your normal password. |
| `ALERT_EMAIL_FROM` | `SMTP_USER` | Sender address |
| `DASHBOARD_URL` | — | Link to the dashboard, included in the email |

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

Both parts have automated tests. They run offline in a few seconds: a throwaway SQLite database,
a fake AI and a fake backend, so they need **no OpenAI key, cost nothing, and never touch your real data**.

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest

cd ../frontend
pip install -r requirements-dev.txt
python -m pytest
```

- **Backend:** CSV upload and clean-up, re-uploads (no repeat AI charges), AI failures and retry,
  tag/reply temperatures, every filter, CSV export (incl. Tamil text), the delete safety check,
  reply ratings, upgrading an existing database, and alert emails (fake mail server, failures).
- **Dashboard:** weekly trend maths (empty weeks, missing ratings/dates, week-over-week change) and
  the whole dashboard rendered against a fake backend: every tab, filters, search, 👍/👎 buttons,
  empty database, backend down.

**AI quality check (uses your OpenAI key, costs a few cents):** `data/eval_reviews.csv` holds 41
hand-labelled reviews (English, Tamil, Tanglish, sarcasm, wrong star ratings, health and fraud cases).
Run it after changing a prompt or model to see whether things got better or worse:

```bash
cd backend
python eval_ai.py                        # model from .env
python eval_ai.py --reply-model gpt-5.4-mini   # try another reply model (or --tag-model, --model for both)
python eval_ai.py --out answers.json     # also save every tag and reply to read through
```

It scores each tag against the labels and checks every reply: right language and script, not
copied from the prompt's examples, no refund promises, not too long. Read some replies yourself too.

**Automatic:** GitHub runs both test suites, and checks that the Docker images build, on every push and pull request (`.github/workflows/tests.yml`). See the repo's **Actions** tab.

**Dependency updates:** Dependabot (`.github/dependabot.yml`) opens pull requests every Monday when a Python package, GitHub Action or the Docker base image has a new version. Small updates come grouped in one PR per folder. CI tests each PR: merge it when the checks are green.

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
│   ├── trends.py          # weekly trend numbers
│   ├── report.py          # KPI numbers + Excel-safe CSV
│   ├── tests/             # pytest tests (fake backend)
│   ├── .streamlit/config.toml   # colour theme
│   ├── Dockerfile
│   └── requirements.txt
├── data/sample_reviews.csv      # 30 test reviews
├── docker-compose.yml        # for your PC
├── docker-compose.prod.yml   # for a public server
├── .env.example
└── README.md
```
