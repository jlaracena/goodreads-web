import json
import os
import subprocess
import time
import xml.etree.ElementTree as et
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from decouple import config
from django.http import JsonResponse
from django.shortcuts import redirect, render

READING_STATE_FILE = Path.home() / "Code/scripts/data/reading_state.json"
READING_SCRIPT = Path.home() / "Code/scripts/reading_plan_todoist.py"

GOODREADS_API_KEY = config('GOODREADS_API_KEY')
GOODREADS_USER_ID = config('GOODREADS_USER_ID')

HEADERS = {
    "User-Agent": "PostmanRuntime/7.37.3",
    "Accept": "*/*",
}

_cache: dict = {}
CACHE_TTL = 30 * 60  # 30 minutos

VALID_SHELVES = {"to-read", "own-paper"}


def fetch_shelf_page(shelf, page):
    url = (
        f"https://www.goodreads.com/review/list?v=2"
        f"&key={GOODREADS_API_KEY}&id={GOODREADS_USER_ID}"
        f"&shelf={shelf}&per_page=200&page={page}"
    )
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text


def parse_page(xml_text):
    root = et.fromstring(xml_text)
    reviews = root.find("reviews")
    total = int(reviews.attrib.get("total", 0)) if reviews is not None else 0
    rows = []
    for book in root.findall("./reviews/review/book"):
        rows.append({
            "title": book.find("title").text,
            "num_pages": book.find("num_pages").text,
            "average_rating": book.find("average_rating").text,
            "ratings_count": book.find("ratings_count").text,
            "link": book.find("link").text,
        })
    return rows, total


def build_df(rows):
    df = pd.DataFrame(rows, columns=["title", "num_pages", "average_rating", "ratings_count", "link"])
    for col in ["num_pages", "average_rating", "ratings_count"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df[col] = df[col].fillna(df[col].mean())

    df["score"] = (
        (5 * df["average_rating"] / 10)
        + 2.5 * (1 - np.exp(-df["ratings_count"] / 720000))
    )
    df["score_per_page"] = (
        0.5 * df["average_rating"]
        + 1.25 * (1 - np.exp(-df["ratings_count"] / 720000))
        + 1.25 * (1 - np.exp(-(300 / (1 + df["num_pages"]))))
    )
    df["score_pct"] = (df["score"] / df["score"].max() * 100).round(0).astype(int)

    return df.drop_duplicates(subset=["title"])


def get_shelf(shelf):
    if shelf in _cache:
        ts, data = _cache[shelf]
        if time.time() - ts < CACHE_TTL:
            return data

    first_rows, total = parse_page(fetch_shelf_page(shelf, 1))
    rows = first_rows

    for page in range(2, ceil(total / 200) + 1):
        try:
            new_rows, _ = parse_page(fetch_shelf_page(shelf, page))
            rows.extend(new_rows)
        except Exception:
            break

    result = build_df(rows)
    _cache[shelf] = (time.time(), result)
    return result


# ── Vistas de página (responden instantáneo) ──────────────────────────────────

def lista(request):
    return render(request, "books/lista.html", {
        "active_tab": "rating",
        "api_url": "/api/shelf/to-read/?sort=score",
    })


def lista_per_page(request):
    return render(request, "books/lista.html", {
        "active_tab": "per_page",
        "api_url": "/api/shelf/to-read/?sort=score_per_page",
    })


def lista_own_paper(request):
    return render(request, "books/lista.html", {
        "active_tab": "own_paper",
        "api_url": "/api/shelf/own-paper/?sort=score_per_page",
    })


# ── Endpoint JSON (carga los datos en background) ─────────────────────────────

def api_shelf(request, shelf):
    if shelf not in VALID_SHELVES:
        return JsonResponse({"error": "shelf no válido"}, status=400)

    sort = request.GET.get("sort", "score")
    if sort not in ("score", "score_per_page"):
        sort = "score"

    df = get_shelf(shelf).sort_values(sort, ascending=False)

    books = df[["title", "num_pages", "average_rating", "ratings_count", "score", "score_per_page", "score_pct", "link"]].copy()
    books["num_pages"] = books["num_pages"].round(0).astype(int)
    books["average_rating"] = books["average_rating"].round(2)
    books["ratings_count"] = books["ratings_count"].round(0).astype(int)
    books["score"] = books["score"].round(3)
    books["score_per_page"] = books["score_per_page"].round(3)

    return JsonResponse({"books": books.to_dict("records")})


# ── Plan de lectura ───────────────────────────────────────────────────────────

def plan(request):
    today = datetime.now()
    end_date = datetime(today.year, 12, 31, 23, 59)

    params = request.POST if request.method == "POST" else request.GET
    books_read = int(params.get("books_read", 2))
    goal = int(params.get("goal", 24))

    books_remaining = goal - books_read
    days_remaining = (end_date - today).days
    days_per_book = days_remaining / books_remaining if books_remaining > 0 else 0

    # Ritmo esperado: cuántos libros deberías haber leído hasta hoy
    start_of_year = datetime(today.year, 1, 1)
    total_days = (end_date - start_of_year).days
    days_elapsed = (today - start_of_year).days
    expected_books = round(goal * days_elapsed / total_days, 1)
    books_diff = round(books_read - expected_books, 1)
    if books_diff >= 1:
        pace_status = "ahead"
    elif books_diff <= -1:
        pace_status = "behind"
    else:
        pace_status = "on_track"

    schedule = []
    date = today
    for i in range(books_remaining):
        date += timedelta(days=days_per_book)
        schedule.append({
            "book_num": books_read + i + 1,
            "deadline": date.strftime("%d-%m-%Y"),
        })

    current_book  = params.get("current_book", "").strip()
    current_pages = int(params.get("current_pages", 0))
    pages_read    = int(params.get("pages_read", 0))
    progress_pct  = float(params.get("progress_pct", 0))

    pages_per_day = pct_per_day = run_msg = None
    if days_per_book > 0:
        state = _load_reading_state()
        if current_pages > 0:
            pages_remaining = current_pages - pages_read
            pages_per_day = round(pages_remaining / days_per_book, 1)
            pct_per_day   = round(pages_remaining / current_pages / days_per_book * 100, 1)
            state.update({"total_pages": current_pages, "pages_per_day": pages_per_day,
                          "use_percentage": False, "goal": goal})
        elif 0 < progress_pct < 100:
            pct_per_day = round((100 - progress_pct) / days_per_book, 1)
            state.update({"total_pages": 0, "pages_per_day": pct_per_day,
                          "use_percentage": True, "goal": goal})
        if current_book:
            state["current_book"] = current_book
            state["task_id"] = None
        if pages_per_day or pct_per_day:
            _save_reading_state(state)

    # Ejecutar script si viene acción POST
    if request.method == "POST" and request.POST.get("action") == "run":
        try:
            env = os.environ.copy()
            env["TODOIST_TOKEN"] = config("TODOIST_TOKEN")
            result = subprocess.run(
                ["/opt/homebrew/bin/python3", str(READING_SCRIPT)],
                capture_output=True, text=True, timeout=30, env=env
            )
            run_msg = ("success", result.stdout.strip()) if result.returncode == 0 \
                      else ("danger", result.stderr.strip())
        except Exception as e:
            run_msg = ("danger", str(e))

    reading_state = _load_reading_state()

    return render(request, "books/plan.html", {
        "active_tab": "plan",
        "books_read": books_read,
        "goal": goal,
        "expected_books": expected_books,
        "books_diff": abs(books_diff),
        "pace_status": pace_status,
        "books_remaining": books_remaining,
        "days_remaining": days_remaining,
        "days_per_book": round(days_per_book, 1),
        "schedule": schedule,
        "current_book": current_book or reading_state.get("current_book", ""),
        "current_pages": current_pages,
        "pages_read": pages_read,
        "progress_pct": progress_pct,
        "pages_per_day": pages_per_day,
        "pct_per_day": pct_per_day,
        "reading_state": reading_state,
        "run_msg": run_msg,
    })


# ── Libro actual ──────────────────────────────────────────────────────────────

def _load_reading_state():
    if READING_STATE_FILE.exists():
        return json.loads(READING_STATE_FILE.read_text())
    return {}

def _save_reading_state(state):
    READING_STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def libro(request):
    msg = None

    if request.method == "POST":
        action = request.POST.get("action")
        state = _load_reading_state()

        if action == "save":
            state["current_book"] = request.POST.get("current_book", "").strip()
            state["task_id"] = None  # nueva tarea en Todoist
            _save_reading_state(state)
            msg = ("success", "Libro guardado. Se creará una tarea nueva en Todoist al ejecutar el script.")

        elif action == "run":
            try:
                env = os.environ.copy()
                env["TODOIST_TOKEN"] = config("TODOIST_TOKEN")
                result = subprocess.run(
                    ["/opt/homebrew/bin/python3", str(READING_SCRIPT)],
                    capture_output=True, text=True, timeout=30, env=env
                )
                if result.returncode == 0:
                    msg = ("success", result.stdout.strip() or "Script ejecutado correctamente.")
                else:
                    msg = ("danger", result.stderr.strip() or "Error al ejecutar el script.")
            except subprocess.TimeoutExpired:
                msg = ("danger", "Timeout: el script tardó más de 30 segundos.")
            except Exception as e:
                msg = ("danger", f"Error: {e}")

        return redirect("libro") if msg is None else render(request, "books/libro.html", {
            "active_tab": "libro",
            "state": _load_reading_state(),
            "msg": msg,
        })

    state = _load_reading_state()

    # Calcular progreso estimado del libro actual
    book_progress = None
    if state.get("total_pages") and state.get("pages_per_day"):
        total = state["total_pages"]
        ppd   = state["pages_per_day"]
        today = datetime.now()
        end   = datetime(today.year, 12, 31, 23, 59)
        books_remaining = state.get("goal", 24) - state.get("books_read_baseline", 0)
        days_remaining  = (end - today).days
        dpb = days_remaining / books_remaining if books_remaining > 0 else 0
        book_progress = {
            "days_for_book": round(dpb, 1),
            "total_sessions": ceil(total / ppd) if ppd > 0 else 0,
        }

    return render(request, "books/libro.html", {
        "active_tab": "libro",
        "state": state,
        "book_progress": book_progress,
        "msg": msg,
    })
