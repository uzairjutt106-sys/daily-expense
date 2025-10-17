## Daily Expense Tracker (FastAPI + SQLite)

Track daily expenses with item type (liquid/solid), quantities in liters or kg, and compute totals per day. Includes HTML UI, delete actions, and JSON endpoints. Data is stored in SQLite.

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000/`.

### Features

- Add expense entries with:
  - item name
  - item type: liquid (L) or solid (kg)
  - quantity (float)
  - unit price (float)
  - date (defaults to today on the page)
- List entries and total by selected date
- Delete an entry
- JSON endpoints:
  - `/api/expenses?date=YYYY-MM-DD` – list items and total
  - `/api/total?date=YYYY-MM-DD` – total only

### Notes

- DB file: `expenses.db` in project root; auto-created on first run.
- Date field accepts `YYYY-MM-DD` in the UI; API also allows some common formats.

## Connectivity Checker

Check internet connectivity and verify host reachability via TCP or ping.

### Quick start

```bash
python3 check_connectivity.py --servers servers.txt --method tcp --ports 22,80,443
```

Or use ping:

```bash
python3 check_connectivity.py --servers servers.txt --method ping
```

Exit code is 0 if all checks pass, non-zero otherwise.

### Options

- **--servers, -s**: Path to hosts file (default: `servers.txt`). One host/IP per line.
- **--method, -m**: `tcp` (default) or `ping`.
- **--ports, -p**: Comma/range list for TCP (e.g., `22,80,443` or `20-25,80`).
- **--timeout, -t**: Per-check timeout seconds (default: 3).
- **--retries, -r**: Retries per host/port (default: 1).
- **--concurrency, -c**: Number of concurrent checks (default: 64).
- **--json**: Structured JSON output.
- **--quiet, -q**: Suppress human-readable lines (useful with `--json`).
- **--dns-host**: Hostname to resolve for internet check (default: `example.com`).
- **--https-url**: URL to HEAD for internet check (default: Google 204 endpoint).

### Examples

- TCP on common ports:

```bash
python3 check_connectivity.py -s servers.txt -m tcp -p 22,80,443
```

- TCP scanning a range:

```bash
python3 check_connectivity.py -s servers.txt -m tcp -p 20-25,80
```

- Ping method:

```bash
python3 check_connectivity.py -s servers.txt -m ping
```

- Machine-readable JSON (quiet):

```bash
python3 check_connectivity.py --json -q
```

### Notes

- The `ping` method uses the system `ping` binary; ensure it exists on your system.
- No external Python dependencies are required.
- Place your hosts in `servers.txt` (one per line). Comments start with `#`.




# daily-expense
