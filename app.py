from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


APP_DIR = Path(__file__).parent
DB_PATH = APP_DIR / "expenses.db"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                item_name TEXT NOT NULL,
                item_type TEXT NOT NULL CHECK(item_type IN ('liquid','solid','utility','fixed')),
                quantity REAL NOT NULL CHECK(quantity >= 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def migrate_db_if_needed() -> None:
    """Migrate legacy schemas to current schema.

    Handles:
    - Legacy month-based schema using `entry_month` -> converts to `entry_date` (YYYY-MM-01)
    - Legacy CHECK on item_type missing 'fixed' -> recreates table with updated CHECK
    """
    with closing(get_db_connection()) as conn:
        cur = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name='expenses'")
        row = cur.fetchone()
        if not row:
            return  # Table doesn't exist; init_db will create

        table_sql = row[1] or ""
        needs_month_migration = "entry_month" in table_sql and "entry_date" not in table_sql
        needs_fixed_check = ("CHECK" in table_sql and "'fixed'" not in table_sql)

        if not needs_month_migration and not needs_fixed_check:
            return

        # Create new table with current schema
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_date TEXT NOT NULL,
                item_name TEXT NOT NULL,
                item_type TEXT NOT NULL CHECK(item_type IN ('liquid','solid','utility','fixed')),
                quantity REAL NOT NULL CHECK(quantity >= 0),
                unit_price REAL NOT NULL CHECK(unit_price >= 0),
                created_at TEXT NOT NULL
            )
            """
        )

        # Determine copy statement based on old schema
        try:
            if needs_month_migration:
                # Convert entry_month (YYYY-MM) -> entry_date (YYYY-MM-01)
                conn.execute(
                    """
                    INSERT INTO expenses_new (id, entry_date, item_name, item_type, quantity, unit_price, created_at)
                    SELECT id,
                           substr(entry_month || '-01', 1, 10) AS entry_date,
                           item_name,
                           item_type,
                           quantity,
                           unit_price,
                           created_at
                    FROM expenses
                    """
                )
            else:
                # Same columns; just copy data to update CHECK constraint
                conn.execute(
                    """
                    INSERT INTO expenses_new (id, entry_date, item_name, item_type, quantity, unit_price, created_at)
                    SELECT id, entry_date, item_name, item_type, quantity, unit_price, created_at FROM expenses
                    """
                )

            conn.execute("DROP TABLE expenses")
            conn.execute("ALTER TABLE expenses_new RENAME TO expenses")
            conn.commit()
        finally:
            # Clean up in case the new table still exists due to partial migration
            try:
                conn.execute("DROP TABLE IF EXISTS expenses_new")
            except Exception:
                pass


def normalize_date(d: Optional[str]) -> str:
    """Normalize date input to YYYY-MM-DD format."""
    if not d:
        return date.today().isoformat()
    try:
        return datetime.fromisoformat(d).date().isoformat()
    except ValueError:
        # Accept common formats: DD-MM-YYYY, DD/MM/YYYY
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(d, fmt).date().isoformat()
            except ValueError:
                pass
    raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")


def unit_for_type(item_type: str) -> str:
    if item_type == "liquid":
        return "L"
    elif item_type == "solid":
        return "kg"
    elif item_type == "utility":
        return "units"
    else:  # fixed
        return "fixed"


def fetch_expenses_for_date(entry_date: str) -> Tuple[List[sqlite3.Row], float]:
    with closing(get_db_connection()) as conn:
        rows = list(
            conn.execute(
                """
                SELECT id, entry_date, item_name, item_type, quantity, unit_price
                FROM expenses
                WHERE entry_date = ?
                ORDER BY id DESC
                """,
                (entry_date,),
            )
        )
        total = sum((r["quantity"] * r["unit_price"]) for r in rows)
        return rows, total


def fetch_expenses_for_range(start_date: str, end_date: str) -> Tuple[List[sqlite3.Row], float]:
    with closing(get_db_connection()) as conn:
        rows = list(
            conn.execute(
                """
                SELECT id, entry_date, item_name, item_type, quantity, unit_price
                FROM expenses
                WHERE entry_date >= ? AND entry_date <= ?
                ORDER BY entry_date DESC, id DESC
                """,
                (start_date, end_date),
            )
        )
        total = sum((r["quantity"] * r["unit_price"]) for r in rows)
        return rows, total


def month_total_for_date(any_date: str) -> float:
    """Compute total (including fixed) for the entire month of the given date (YYYY-MM-DD)."""
    d = datetime.fromisoformat(any_date).date()
    start = d.replace(day=1)
    # Compute first day of next month
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1, day=1)
    else:
        next_month = start.replace(month=start.month + 1, day=1)
    start_s = start.isoformat()
    end_s = (next_month - date.resolution).isoformat()  # inclusive end of month
    with closing(get_db_connection()) as conn:
        cur = conn.execute(
            """
            SELECT SUM(quantity * unit_price) AS total
            FROM expenses
            WHERE entry_date >= ? AND entry_date <= ?
            """,
            (start_s, end_s),
        )
        row = cur.fetchone()
        total = float(row[0]) if row and row[0] is not None else 0.0
        return round(total, 2)


def month_bounds_and_label(any_date: str) -> Tuple[str, str, str]:
    """Return (start_iso, end_iso, label) for the month containing any_date.

    label is like 'October 2025'.
    """
    d = datetime.fromisoformat(any_date).date()
    start = d.replace(day=1)
    if start.month == 12:
        next_month = start.replace(year=start.year + 1, month=1, day=1)
    else:
        next_month = start.replace(month=start.month + 1, day=1)
    start_s = start.isoformat()
    end_s = (next_month - date.resolution).isoformat()
    label = start.strftime("%B %Y")
    return start_s, end_s, label


app = FastAPI(title="Daily Expense Tracker")

# Static and templates
TEMPLATES_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    migrate_db_if_needed()


@app.get("/", response_class=HTMLResponse)
def index(request: Request, d: Optional[str] = Query(default=None, alias="date")) -> HTMLResponse:
    entry_date = normalize_date(d)
    rows, _ignored_total = fetch_expenses_for_date(entry_date)
    
    # Separate fixed expenses from daily expenses
    fixed_items = []
    daily_items = []
    fixed_total = 0.0
    daily_total = 0.0
    
    for r in rows:
        item = {
            "id": r["id"],
            "entry_date": r["entry_date"],
            "item_name": r["item_name"],
            "item_type": r["item_type"],
            "quantity": r["quantity"],
            "unit_price": r["unit_price"],
            "unit": unit_for_type(r["item_type"]),
            "line_total": round(r["quantity"] * r["unit_price"], 2),
        }
        if r["item_type"] == "fixed":
            fixed_items.append(item)
            fixed_total += item["line_total"]
        else:
            daily_items.append(item)
            daily_total += item["line_total"]
    
    month_total = month_total_for_date(entry_date)
    _ms, _me, month_label = month_bounds_and_label(entry_date)

    grand_total = round(fixed_total + daily_total, 2)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "entry_date": entry_date,
            "fixed_items": fixed_items,
            "daily_items": daily_items,
            "fixed_total": round(fixed_total, 2),
            "daily_total": round(daily_total, 2),
            "total": grand_total,
            "month_total": month_total,
            "month_label": month_label,
        },
    )


@app.get("/download/month")
def download_month(d: Optional[str] = Query(default=None, alias="date")) -> Response:
    """Download CSV for all expenses in the month of the given date."""
    entry_date = normalize_date(d)
    start_s, end_s, month_label = month_bounds_and_label(entry_date)
    with closing(get_db_connection()) as conn:
        rows = list(
            conn.execute(
                """
                SELECT entry_date, item_name, item_type, quantity, unit_price
                FROM expenses
                WHERE entry_date >= ? AND entry_date <= ?
                ORDER BY entry_date ASC, id ASC
                """,
                (start_s, end_s),
            )
        )
    # Build CSV
    import io, csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "item_name", "item_type", "quantity", "unit_price", "line_total"])
    for r in rows:
        q = float(r["quantity"]) if r["quantity"] is not None else 0.0
        up = float(r["unit_price"]) if r["unit_price"] is not None else 0.0
        writer.writerow([r["entry_date"], r["item_name"], r["item_type"], q, up, round(q * up, 2)])
    csv_data = buf.getvalue()
    filename = f"expenses_{month_label.replace(' ', '_')}.csv"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Content-Type": "text/csv; charset=utf-8",
    }
    return Response(content=csv_data, media_type="text/csv", headers=headers)


@app.post("/add")
def add_item(
    item_name: str = Form(...),
    item_type: Optional[str] = Form(None),  # defaults to 'utility' if not provided
    quantity: Optional[float] = Form(None),
    unit_price: float = Form(...),
    entry_date: str = Form(...),
) -> RedirectResponse:
    entry_date = normalize_date(entry_date)
    item_type = (item_type or "utility").lower().strip()
    # For non-liquid submissions where quantity isn't provided, default to 1.0
    if item_type in ("fixed", "utility", "solid") and quantity is None:
        quantity = 1.0
    if quantity is None:
        raise HTTPException(status_code=400, detail="quantity is required")
    if quantity < 0 or unit_price < 0:
        raise HTTPException(status_code=400, detail="quantity and unit_price must be non-negative")

    with closing(get_db_connection()) as conn:
        conn.execute(
            """
            INSERT INTO expenses (entry_date, item_name, item_type, quantity, unit_price, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (entry_date, item_name.strip(), item_type, float(quantity), float(unit_price), datetime.utcnow().isoformat()),
        )
        conn.commit()

    resp = RedirectResponse(url=f"/?date={entry_date}", status_code=303)
    return resp


@app.post("/delete/{item_id}")
def delete_item(item_id: int, entry_date: str = Form(...)) -> RedirectResponse:
    with closing(get_db_connection()) as conn:
        conn.execute("DELETE FROM expenses WHERE id = ?", (item_id,))
        conn.commit()
    resp = RedirectResponse(url=f"/?date={normalize_date(entry_date)}", status_code=303)
    return resp


@app.get("/api/expenses")
def api_get_expenses(d: Optional[str] = Query(default=None, alias="date")) -> JSONResponse:
    entry_date = normalize_date(d)
    rows, total = fetch_expenses_for_date(entry_date)
    data = [
        {
            "id": r["id"],
            "date": r["entry_date"],
            "item_name": r["item_name"],
            "item_type": r["item_type"],
            "quantity": r["quantity"],
            "unit": unit_for_type(r["item_type"]),
            "unit_price": r["unit_price"],
            "line_total": round(r["quantity"] * r["unit_price"], 2),
        }
        for r in rows
    ]
    return JSONResponse({"date": entry_date, "items": data, "total": round(total, 2)})


@app.get("/api/total")
def api_get_total(d: Optional[str] = Query(default=None, alias="date")) -> JSONResponse:
    entry_date = normalize_date(d)
    _, total = fetch_expenses_for_date(entry_date)
    return JSONResponse({"date": entry_date, "total": round(total, 2)})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)


