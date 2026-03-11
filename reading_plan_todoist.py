"""
reading_plan_todoist.py
Corre cada mañana. Avanza las páginas de la tarea de lectura diaria
en Todoist y ajusta la prioridad según el ritmo anual.

Para empezar un libro nuevo:
  1. Editar ~/Code/scripts/data/reading_state.json con los datos del libro
  2. Poner task_id en null para que el script cree la tarea desde cero
"""

import json
import os
import re
from datetime import datetime, timedelta
from math import ceil

import requests

TODOIST_TOKEN = os.environ["TODOIST_TOKEN"]
STATE_FILE = os.path.expanduser("~/Code/scripts/data/reading_state.json")

HEADERS = {
    "Authorization": f"Bearer {TODOIST_TOKEN}",
    "Content-Type": "application/json",
}


# ── Estado ────────────────────────────────────────────────────────────────────

def load_state():
    with open(STATE_FILE) as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Todoist API ───────────────────────────────────────────────────────────────


def get_task(task_id):
    r = requests.get(
        f"https://api.todoist.com/api/v1/tasks/{task_id}",
        headers=HEADERS, timeout=15
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def create_task(title, project_id, due_date, priority, labels=None):
    payload = {
        "content": title,
        "project_id": project_id,
        "due_date": due_date,
        "priority": priority,
    }
    if labels:
        payload["labels"] = labels
    r = requests.post(
        "https://api.todoist.com/api/v1/tasks",
        headers=HEADERS, json=payload, timeout=15
    )
    r.raise_for_status()
    return r.json()


def update_task(task_id, title, due_date, priority, labels=None):
    payload = {
        "content": title,
        "due_date": due_date,
        "priority": priority,
    }
    if labels:
        payload["labels"] = labels
    r = requests.post(
        f"https://api.todoist.com/api/v1/tasks/{task_id}",
        headers=HEADERS, json=payload, timeout=15
    )
    r.raise_for_status()
    return r.json()


# ── Lógica de ritmo ───────────────────────────────────────────────────────────

def calculate_priority(books_read, goal, today):
    start = datetime(today.year, 1, 1)
    end = datetime(today.year, 12, 31, 23, 59)
    days_elapsed = (today - start).days
    total_days = (end - start).days
    expected = goal * days_elapsed / total_days
    diff = books_read - expected  # positivo = adelantado, negativo = atrasado

    if diff <= -2:
        return 4  # Todoist P1 (urgente)
    elif diff <= -1:
        return 3  # P2
    elif diff < 0:
        return 2  # P3
    else:
        return 1  # P4 (normal)


def days_per_book(books_read, goal, today):
    end = datetime(today.year, 12, 31, 23, 59)
    books_remaining = goal - books_read
    days_remaining = (end - today).days
    if books_remaining <= 0:
        return 0
    return days_remaining / books_remaining


# ── Parseo del título ─────────────────────────────────────────────────────────

PAGES_PATTERN = re.compile(r"\((\d+(?:\.\d+)?)\+(\d+(?:\.\d+)?)=\d+(?:\.\d+)?\)")
PCT_PATTERN   = re.compile(r"\((\d+(?:\.\d+)?)%\+(\d+(?:\.\d+)?)%=\d+(?:\.\d+)?%\)")

def parse_task_title(title, use_percentage):
    pattern = PCT_PATTERN if use_percentage else PAGES_PATTERN
    m = pattern.search(title)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2))


def build_title(book, current, per_day, use_percentage):
    next_val = current + per_day
    if use_percentage:
        return f"Leer {book} ({current:.1f}%+{per_day:.1f}%={next_val:.1f}%)"
    else:
        c = int(current)
        p = int(per_day)
        n = int(next_val)
        return f"Leer {book} ({c}+{p}={n})"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    state = load_state()
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    book          = state["current_book"]
    total         = state["total_pages"]
    per_day       = state["pages_per_day"]
    use_pct       = state["use_percentage"]
    baseline      = state.get("books_read_baseline", 2)
    goal          = state["goal"]
    project_id    = state["libros_project_id"]
    task_id       = state.get("task_id")
    labels        = state.get("labels", [])

    # 1. Leer libros leídos desde el estado (se actualiza desde la web)
    books_read = state.get("books_read", baseline)

    # 2. Prioridad según ritmo y ajuste de páginas
    priority = calculate_priority(books_read, goal, today)
    dpb = days_per_book(books_read, goal, today)
    pace_boost = {4: 1.15, 3: 1.10, 2: 1.05}.get(priority, 1.0)
    per_day = round(per_day * pace_boost, 1)

    # 3. Buscar tarea existente
    task = get_task(task_id) if task_id else None

    if task:
        # Parsear posición actual desde el título de ayer
        current, _ = parse_task_title(task["content"], use_pct)
        if current is None:
            # Título no parseable, usar total como referencia
            current = 0
        # La posición de hoy es el "next" de ayer: current + per_day
        new_current = current + per_day
        # Ajustar per_day si nos acercamos al final
        if not use_pct and total > 0 and new_current + per_day > total:
            per_day = max(1, total - new_current)
        elif use_pct and new_current + per_day > 100:
            per_day = max(0.1, 100 - new_current)

        new_title = build_title(book, new_current, per_day, use_pct)
        update_task(task_id, new_title, today_str, priority, labels)
        boost_pct = int((pace_boost - 1) * 100)
        boost_str = f" (+{boost_pct}% ritmo)" if boost_pct else ""
        print(f"[OK] Tarea actualizada: {new_title} | P{5 - priority}{boost_str} | {books_read}/{goal} libros")
    else:
        # Crear tarea desde cero (inicio de libro nuevo)
        if per_day == 0 and dpb > 0:
            # Calcular páginas/día automáticamente si no está configurado
            per_day = round(total / dpb, 1) if total > 0 else round(100 / dpb, 1)
            state["pages_per_day"] = per_day
        current_page = state.get("current_page", 0)
        new_title = build_title(book, current_page, per_day, use_pct)
        new_task = create_task(new_title, project_id, today_str, priority, labels)
        task_id = new_task["id"]
        state["task_id"] = task_id
        save_state(state)
        boost_pct = int((pace_boost - 1) * 100)
        boost_str = f" (+{boost_pct}% ritmo)" if boost_pct else ""
        print(f"[OK] Tarea creada: {new_title} | P{5 - priority}{boost_str} | {books_read}/{goal} libros")


if __name__ == "__main__":
    main()
