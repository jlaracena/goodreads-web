# goodreads-todoist-web

A local web app to visualize and prioritize your Goodreads reading list, with an annual reading plan calculator and automatic Todoist task integration.

Designed to run on a home server (Mac Mini, Raspberry Pi, etc.) and be accessible from any device on your network.

---

## Features

### Book list
Fetches your Goodreads shelves via the API and calculates a **weighted score** for each book, combining average rating and number of ratings. Three views:

| Route | Description |
|---|---|
| `/` | `to-read` shelf sorted by rating score |
| `/per-page/` | `to-read` shelf sorted by page-adjusted score (favors shorter books) |
| `/own-paper/` | `own-paper` shelf (physical books you own) |

The table is sortable by any column. Data loads asynchronously — the page responds instantly and shows a spinner while the API is queried. Results are cached for 30 minutes.

### Annual reading plan (`/plan/`)
A calculator to hit your goal of reading N books per year. Enter:
- Books already read and total goal
- Current book name (optional)
- Total pages and pages already read — or progress percentage

Shows days remaining, days per book, pages/day for the current book, and a deadline calendar for each upcoming book.

### Todoist integration
After calculating your reading plan, you can:
1. Set **Todoist labels** for the daily task (e.g. `time_day`, `reading`)
2. Click **▶ Ejecutar en Todoist ahora** to create or update the task immediately

The companion script `reading_plan_todoist.py` (meant to run as a daily cron at 1am) automatically:
- Advances the page range in the task title each day: `Leer AI Engineering (185+23=208)`
- Adjusts task priority based on your reading pace vs. expected annual goal
- Creates a new task when you start a new book (just set `task_id` to `null` in the state file)

**Priority logic:**

| Books behind goal | Todoist priority |
|---|---|
| ≥ 2 behind | P1 (urgent) |
| 1–2 behind | P2 |
| < 1 behind | P3 |
| On track or ahead | P4 (normal) |

---

## Setup

### Requirements
- Python 3.10+
- Goodreads account with API key ([request here](https://www.goodreads.com/api/keys))
- Todoist account with API token (Settings → Integrations → API token) — *optional, only needed for Todoist integration*

### Installation

```bash
git clone https://github.com/jlaracena/goodreads-todoist-web.git
cd goodreads-web

python3 -m venv venv
venv/bin/pip install -r requirements.txt

cp .env.example .env
# Edit .env with your credentials
```

### Environment variables (`.env`)

```
DJANGO_SECRET_KEY=generate-a-random-key
GOODREADS_API_KEY=your-api-key
GOODREADS_USER_ID=your-goodreads-user-id
TODOIST_TOKEN=your-todoist-api-token
```

The `GOODREADS_USER_ID` is the identifier from your profile URL on Goodreads (e.g. `123456789-john`).

To generate a Django secret key:
```bash
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### Run

```bash
venv/bin/python manage.py runserver 0.0.0.0:8766
```

Then open `http://localhost:8766` (or `http://<server-ip>:8766` from another device on your network).

---

## Todoist integration setup

The reading plan integrates with Todoist via a companion script. To set it up:

1. Create the data directory and state file:

```bash
mkdir -p ~/Code/scripts/data
```

```json
// ~/Code/scripts/data/reading_state.json
{
  "current_book": "Your Book Title",
  "total_pages": 300,
  "pages_per_day": 20,
  "use_percentage": false,
  "books_read_baseline": 0,
  "baseline_date": "2026-01-01",
  "goal": 24,
  "task_id": null,
  "labels": [],
  "libros_project_id": "YOUR_TODOIST_PROJECT_ID",
  "books_read": 0,
  "current_page": 0
}
```

2. Copy the script:

```bash
cp reading_plan_todoist.py ~/Code/scripts/
```

3. Set up a daily cron (runs at 1am):

```bash
crontab -e
```

```
TODOIST_TOKEN=your-todoist-api-token
0 1 * * * /path/to/venv/bin/python3 /path/to/reading_plan_todoist.py >> /tmp/reading_plan.log 2>&1
```

**Note:** The easiest way to configure the reading state is through the web app at `/plan/`. After entering your book details and clicking "Calcular", the state file is updated automatically.

---

## Run on system startup (macOS with launchd)

The repo includes a `com.goodreads-web.plist` example for `launchd`. Edit the paths to match your setup, then:

```bash
cp com.goodreads-web.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.goodreads-web.plist
```

Logs at `/tmp/goodreads-web.log`.

---

## Scoring formula

The score combines average rating and book popularity using an exponential saturation function, so books with many ratings don't unfairly dominate over lesser-known but highly rated books.

```
score          = 0.5 × rating + 1.25 × (1 − e^(−ratings/720000))
score_per_page = score + 1.25 × (1 − e^(−300/(1+pages)))
```

`score_per_page` penalizes very long books — useful for prioritizing quick reads.

---

## Tech stack

- **Django 4.2** — web framework
- **Bootstrap 5** — frontend
- **pandas + numpy** — data processing
- **python-decouple** — environment variable management
- **Goodreads API** (XML) — book data
- **Todoist REST API v1** — task management
