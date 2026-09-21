# Bring Your Own Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let visitors upload CSV and Excel files and ask questions about them, each upload walled off in its own Postgres schema and deleted after 24 hours.

**Architecture:** `src/ingest.py` turns uploads into typed in-memory tables without touching the database. `src/datasets.py` loads them into a fresh `ds_<id>` schema with a login role that can read only that schema, and is the only code that uses the owner connection. `/ask` runs generated SQL as that role. A daily Vercel cron removes expired uploads.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 + psycopg2 on Neon Postgres, openpyxl, vanilla JS/HTML, pytest.

**Spec:** `docs/superpowers/specs/2026-09-21-bring-your-own-data-design.md`

## Global Constraints

- Work on branch `feat/bring-your-own-data`; never commit to `main`. Open one PR at the end.
- Commit messages: imperative mood ("Add X"). **No `Co-Authored-By` trailer and no Claude/Anthropic attribution anywhere.**
- Run Python through the project virtualenv: `source .venv/Scripts/activate` (Windows Git Bash) or `source .venv/bin/activate` (macOS/Linux). Install with `uv pip install -r requirements-dev.txt`.
- Pin every dependency with `==`. Runtime dependencies go in `requirements.txt`, test-only ones in `requirements-dev.txt`.
- Upload limits: 4 MB total (`4 * 1024 * 1024` bytes), 20 tables, 100 columns per table, 200,000 rows total, 50 MB uncompressed per `.xlsx`.
- Datasets live 24 hours. At most 200 live datasets.
- Result limits: at most 500 rows returned per query; at most 50 rows sent to Gemini for the explanation.
- Column types are exactly: `BIGINT`, `NUMERIC`, `BOOLEAN`, `DATE`, `TIMESTAMP`, `TEXT`.
- Never print, log or commit a connection string or password. `.env` is gitignored; keep it that way.
- Match the surrounding code style: plain functions, docstrings on public functions, comments explain *why*.

## File Structure

| File | Status | Responsibility |
| --- | --- | --- |
| `pytest.ini` | create | Put the repo root on `sys.path`; collect only `tests/` |
| `tests/conftest.py` | create | Load `.env`; dummy settings so `src.db`/`src.ai` import in tests |
| `tests/test_api.py` | modify | Live-server tests become opt-in via `LIVE_API_URL` |
| `src/sql_validator.py` | modify | Match forbidden keywords as whole words |
| `src/ingest.py` | create | Files → `Table` objects: names, types, limits |
| `src/db.py` | modify | `bind` parameter; cap results at 500 rows |
| `src/schema_loader.py` | modify | `bind` parameter |
| `src/ai.py` | modify | Explanation prompt knows it may see a sample |
| `src/datasets.py` | create | Dataset lifecycle; only user of the owner connection |
| `app.py` | modify | `/datasets` endpoints, `/cron/cleanup`, dataset-aware `/ask` |
| `vercel.json` | modify | Daily cron |
| `public/datasets.js` | create | Recent uploads in `localStorage`, shared by both pages |
| `public/index.html` | modify | Upload panel and table preview |
| `public/results.html` | modify | Dataset badge, `dataset_id` on questions, truncation note |
| `README.md` | modify | New endpoints, env vars, test setup |
| `tests/test_validator.py` | modify | Keyword-in-column-name cases |
| `tests/test_ingest.py` | create | Unit tests, no database |
| `tests/test_db.py` | create | Result cap, against SQLite |
| `tests/test_schema_loader.py` | create | Schema text, against SQLite |
| `tests/test_datasets.py` | create | Integration tests against real Postgres, incl. isolation |
| `tests/test_app.py` | create | Endpoint tests with FastAPI's `TestClient` |

---

### Task 1: Test harness and whole-word validator

Uploaded data routinely has columns like `created_at`, `updated_at` and `is_deleted`. The validator matches forbidden keywords as substrings, so it rejects every question touching those columns. Verified on the current code: `SELECT created_at FROM orders` → `Forbidden SQL operation: create`. Writes are now stopped by read-only database roles, so the validator can match whole words only.

**Files:**
- Create: `pytest.ini`, `tests/conftest.py`
- Modify: `src/sql_validator.py`, `tests/test_validator.py`, `tests/test_api.py`

**Interfaces:**
- Produces: `validate_sql(sql) -> (bool, str)` — unchanged signature. `tests/conftest.py` guarantees `GEMINI_API_KEY` and `DATABASE_URL_READONLY` exist during tests.

- [ ] **Step 1: Create the branch**

```bash
git checkout main && git pull && git checkout -b feat/bring-your-own-data
```

- [ ] **Step 2: Add pytest configuration**

Create `pytest.ini`:

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Create `tests/conftest.py`:

```python
"""
Shared test setup.

src/db.py and src/ai.py read their settings when imported and refuse to
start without them. Unit tests never reach the real database or Gemini
through those modules -- the endpoint tests replace the functions that
would -- so placeholder values are enough to let them import.
"""

import os

from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("DATABASE_URL_READONLY", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
```

- [ ] **Step 3: Make the live-server tests opt-in**

`tests/test_api.py` calls a running server and real Gemini, so a plain `pytest` fails with connection errors. Replace its first line, `import requests`, with:

```python
import os

import pytest
import requests

# These tests call a running server and make real Gemini calls, so they only
# run when pointed at one: LIVE_API_URL=http://127.0.0.1:8000 pytest tests/test_api.py
BASE = os.getenv("LIVE_API_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="set LIVE_API_URL to run live API tests")
```

Then replace every `"http://127.0.0.1:8000` in the file with `BASE + "`. For example `requests.get("http://127.0.0.1:8000/health")` becomes `requests.get(BASE + "/health")`. There are four occurrences.

- [ ] **Step 4: Write the failing validator tests**

Append to `tests/test_validator.py`:

```python
# Keywords inside column names are not statements
def test_allow_columns_containing_keywords():
    for sql in [
        "SELECT created_at FROM orders",
        "SELECT id FROM tickets WHERE updated_at > now()",
        "SELECT dropoff_location FROM rides",
        "SELECT count(*) FROM users WHERE is_deleted = false",
    ]:
        valid, message = validate_sql(sql)
        assert valid is True, (sql, message)


# A data-modifying CTE still starts with WITH, so it must be caught by keyword
def test_block_data_modifying_cte():
    valid, message = validate_sql(
        "WITH gone AS (DELETE FROM customers RETURNING *) SELECT * FROM gone"
    )
    assert valid is False
    assert "delete" in message
```

- [ ] **Step 5: Run the tests and watch the new one fail**

Run: `python -m pytest tests/test_validator.py -v`
Expected: `test_allow_columns_containing_keywords` FAILS with `Forbidden SQL operation: create`. All other tests pass (11 passed, 1 failed).

- [ ] **Step 6: Match whole words**

In `src/sql_validator.py`, add at the very top of the file:

```python
import re

# Whole words only: a column such as created_at or is_deleted is not a
# statement. The read-only database role is what actually prevents writes;
# this check exists to fail fast with a clear message.
FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|truncate|create)\b")

```

Then replace this block:

```python
    forbidden = [
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "truncate",
        "create"
    ]

    for word in forbidden:
        if word in sql:
            return False, f"Forbidden SQL operation: {word}"
```

with:

```python
    match = FORBIDDEN.search(sql)

    if match:
        return False, f"Forbidden SQL operation: {match.group(1)}"
```

- [ ] **Step 7: Run the whole suite**

Run: `python -m pytest -v`
Expected: 12 passed in `test_validator.py`; the 4 tests in `test_api.py` SKIPPED ("set LIVE_API_URL…"). No errors.

- [ ] **Step 8: Commit**

```bash
git add pytest.ini tests/conftest.py tests/test_api.py tests/test_validator.py src/sql_validator.py
git commit -m "Match forbidden SQL keywords as whole words" -m "Uploaded data commonly has columns like created_at and is_deleted, which the substring check rejected. Writes are stopped by read-only database roles, so the validator only needs to catch the statements themselves. Also adds pytest.ini and a conftest so a bare pytest run works, and makes the live-server tests opt-in via LIVE_API_URL."
```

---

### Task 2: Ingest — names and types

**Files:**
- Create: `src/ingest.py`, `tests/test_ingest.py`

**Interfaces:**
- Produces, in `src/ingest.py`:
  - `class IngestError(ValueError)` with attribute `status: int` (400 by default, 413 for size)
  - `@dataclass Column(name: str, type: str)`
  - `@dataclass Table(name: str, columns: list[Column], rows: list[tuple])` — row values are Python values of the column's type, or `None`
  - `clean_name(raw, prefix: str, fallback: str) -> str`
  - `dedupe(names: list[str]) -> list[str]`
  - `infer_type(values: list) -> tuple[str, Callable]` — `values` are non-empty cells; returns the Postgres type and a converter for one cell
  - Constants `MAX_UPLOAD_BYTES`, `MAX_TABLES`, `MAX_COLUMNS`, `MAX_TOTAL_ROWS`, `MAX_XLSX_UNCOMPRESSED_BYTES`, `MAX_IDENTIFIER`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ingest.py`:

```python
from datetime import date, datetime
from decimal import Decimal

import pytest

from src.ingest import clean_name, dedupe, infer_type


def test_clean_name_lowercases_and_joins_words():
    assert clean_name("Order Date", "c", "column_1") == "order_date"


def test_clean_name_collapses_symbols():
    assert clean_name("  Sales (USD) %  ", "c", "column_1") == "sales_usd"


def test_clean_name_prefixes_leading_digit():
    assert clean_name("2024 sales", "t", "table_1") == "t_2024_sales"


def test_clean_name_uses_fallback_when_nothing_is_left():
    assert clean_name("", "c", "column_3") == "column_3"
    assert clean_name(None, "c", "column_3") == "column_3"
    assert clean_name("日付", "c", "column_2") == "column_2"


def test_clean_name_suffixes_reserved_words():
    assert clean_name("Order", "c", "column_1") == "order_"
    assert clean_name("select", "c", "column_1") == "select_"


def test_clean_name_truncates_to_postgres_limit():
    assert len(clean_name("a" * 100, "c", "column_1")) == 63


def test_dedupe_suffixes_repeats():
    assert dedupe(["a", "a", "a_2", "b"]) == ["a", "a_2", "a_2_2", "b"]


@pytest.mark.parametrize("values, expected", [
    (["1", "-2", "30"], "BIGINT"),
    ([1, 2, 3.0], "BIGINT"),
    (["1", "2.5"], "NUMERIC"),
    (["0.5", "-1e3"], "NUMERIC"),
    (["99999999999999999999"], "NUMERIC"),
    (["true", "FALSE"], "BOOLEAN"),
    ([True, False], "BOOLEAN"),
    (["2025-01-31", "2024-02-29"], "DATE"),
    ([datetime(2025, 1, 1), datetime(2025, 3, 4)], "DATE"),
    (["2025-01-31 10:00", "2025-01-31T10:00:05"], "TIMESTAMP"),
    ([datetime(2025, 1, 1, 9, 30)], "TIMESTAMP"),
    (["03/04/2025"], "TEXT"),
    (["1,234"], "TEXT"),
    (["007", "12"], "TEXT"),
    (["2025-02-30"], "TEXT"),
    (["1", "yes"], "TEXT"),
    ([], "TEXT"),
])
def test_infer_type(values, expected):
    assert infer_type(values)[0] == expected


def test_converters_return_python_values():
    assert infer_type(["1"])[1]("42") == 42
    assert infer_type(["1", "2.5"])[1]("2.5") == Decimal("2.5")
    assert infer_type(["true"])[1]("TRUE") is True
    assert infer_type(["2025-01-31"])[1]("2025-01-31") == date(2025, 1, 31)
    assert infer_type([datetime(2025, 1, 1)])[1](datetime(2025, 1, 1)) == date(2025, 1, 1)
    assert infer_type(["x"])[1](5) == "5"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'src.ingest'`.

- [ ] **Step 3: Implement names and types**

Create `src/ingest.py`:

```python
"""
Turn uploaded CSV and Excel files into tables ready to load into Postgres.

Nothing in this module touches the database. parse_files() takes the raw
uploads and returns Table objects with cleaned names, one Postgres type per
column, and rows already converted to Python values of those types.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

MAX_UPLOAD_BYTES = 4 * 1024 * 1024
MAX_TABLES = 20
MAX_COLUMNS = 100
MAX_TOTAL_ROWS = 200_000
MAX_XLSX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_IDENTIFIER = 63

# Postgres reserved key words. A column called "order" or "user" would need
# quoting in every query the model writes, so such names get a trailing _.
RESERVED = frozenset("""
    all analyse analyze and any array as asc asymmetric authorization binary
    both case cast check collate collation column concurrently constraint
    create cross current_catalog current_date current_role current_schema
    current_time current_timestamp current_user default deferrable desc
    distinct do else end except false fetch for foreign freeze from full grant
    group having ilike in initially inner intersect into is isnull join lateral
    leading left like limit localtime localtimestamp natural not notnull null
    offset on only or order outer overlaps placing primary references
    returning right select session_user similar some symmetric system_user
    table tablesample then to trailing true union unique user using variadic
    verbose when where window with
""".split())

INTEGER = re.compile(r"^[+-]?(0|[1-9]\d*)$")
NUMBER = re.compile(r"^[+-]?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?$")


class IngestError(ValueError):
    """A problem with the uploaded files, worded to be shown to the user."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass
class Column:
    name: str
    type: str


@dataclass
class Table:
    name: str
    columns: list
    rows: list = field(default_factory=list)


def clean_name(raw, prefix, fallback):
    """Make a safe, unquoted Postgres identifier out of a header or file name."""
    name = re.sub(r"[^a-z0-9]+", "_", str(raw if raw is not None else "").lower()).strip("_")

    if not name:
        name = fallback

    if name[0].isdigit():
        name = f"{prefix}_{name}"

    name = name[:MAX_IDENTIFIER].rstrip("_") or fallback

    if name in RESERVED:
        name += "_"

    return name


def dedupe(names):
    """Suffix repeated names with _2, _3, ... keeping every name unique."""
    seen = set()
    unique = []

    for name in names:
        candidate, number = name, 1

        while candidate in seen:
            number += 1
            suffix = f"_{number}"
            candidate = name[:MAX_IDENTIFIER - len(suffix)] + suffix

        seen.add(candidate)
        unique.append(candidate)

    return unique


# Each converter turns one non-empty cell into a Python value of its type, or
# raises ValueError. CSV cells arrive as strings; Excel cells arrive already
# typed (int, float, bool, datetime), so both forms are accepted.

def _to_bigint(value):
    if isinstance(value, bool):
        raise ValueError

    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and INTEGER.match(value.strip()):
        number = int(value.strip())
    else:
        raise ValueError

    if not -2**63 <= number < 2**63:
        raise ValueError

    return number


def _to_numeric(value):
    if isinstance(value, bool):
        raise ValueError

    if isinstance(value, int):
        return Decimal(value)

    if isinstance(value, float) and value == value and abs(value) != float("inf"):
        return Decimal(repr(value))

    if isinstance(value, str) and NUMBER.match(value.strip()):
        return Decimal(value.strip())

    raise ValueError


def _to_boolean(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"

    raise ValueError


def _to_date(value):
    # datetime is a subclass of date, so it has to be checked first. Excel
    # stores plain dates as midnight datetimes.
    if isinstance(value, datetime):
        if value.time() == time(0):
            return value.date()
        raise ValueError

    if isinstance(value, date):
        return value

    if isinstance(value, str) and ISO_DATE.match(value.strip()):
        return date.fromisoformat(value.strip())

    raise ValueError


def _to_timestamp(value):
    if isinstance(value, datetime):
        return value

    if isinstance(value, str) and ISO_TIMESTAMP.match(value.strip()):
        return datetime.fromisoformat(value.strip())

    raise ValueError


def _to_text(value):
    return value if isinstance(value, str) else str(value)


# Tried in order; the first type every value converts to wins. Only ISO dates
# count as dates: 03/04/2025 is ambiguous between day and month order, so it
# stays text rather than being silently misread.
CONVERTERS = [
    ("BIGINT", _to_bigint),
    ("NUMERIC", _to_numeric),
    ("BOOLEAN", _to_boolean),
    ("DATE", _to_date),
    ("TIMESTAMP", _to_timestamp),
]


def infer_type(values):
    """Pick a column type from its non-empty values; return (type, converter)."""
    if values:
        for type_name, convert in CONVERTERS:
            try:
                for value in values:
                    convert(value)
            except ValueError:
                continue

            return type_name, convert

    return "TEXT", _to_text
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: all PASS (25 tests).

- [ ] **Step 5: Commit**

```bash
git add src/ingest.py tests/test_ingest.py
git commit -m "Add column naming and type detection for uploads"
```

---

### Task 3: Ingest — reading CSV and Excel files

**Files:**
- Modify: `src/ingest.py`, `tests/test_ingest.py`, `requirements.txt`

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: `parse_files(files: list[tuple[str, bytes]]) -> list[Table]` — `files` is `(filename, content)` pairs. Raises `IngestError` (status 413 when over 4 MB, 400 otherwise) with a message naming the file or the limit. Returned table names are cleaned and unique across the whole upload.

- [ ] **Step 1: Add the dependency**

Append to `requirements.txt`:

```
openpyxl==3.1.5
```

Run: `uv pip install -r requirements-dev.txt`
Expected: installs `openpyxl-3.1.5` (and `et-xmlfile`).

- [ ] **Step 2: Write the failing tests**

Add these imports at the top of `tests/test_ingest.py`, below the existing ones:

```python
import io
import zipfile

import openpyxl

import src.ingest as ingest
from src.ingest import IngestError, parse_files
```

Append to `tests/test_ingest.py`:

```python
def xlsx(sheets):
    """Build an .xlsx in memory from {sheet title: [rows]}."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)

    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def columns(table):
    return [(c.name, c.type) for c in table.columns]


def test_csv_becomes_a_typed_table():
    [table] = parse_files([("Sales Report.csv", b"Order ID,Amount,Order Date\n1,10.5,2025-01-01\n2,20,2025-01-02\n")])
    assert table.name == "sales_report"
    assert columns(table) == [("order_id", "BIGINT"), ("amount", "NUMERIC"), ("order_date", "DATE")]
    assert table.rows == [
        (1, Decimal("10.5"), date(2025, 1, 1)),
        (2, Decimal("20"), date(2025, 1, 2)),
    ]


def test_csv_semicolons_and_byte_order_mark():
    [table] = parse_files([("x.csv", "﻿a;b\n1;x\n".encode("utf-8"))])
    assert columns(table) == [("a", "BIGINT"), ("b", "TEXT")]


def test_csv_latin1_fallback():
    [table] = parse_files([("x.csv", "name\ncafé\n".encode("latin-1"))])
    assert table.rows == [("café",)]


def test_blank_cells_are_null_and_blank_rows_skipped():
    [table] = parse_files([("x.csv", b"a,b\n1,\n\n,\n2,x\n")])
    assert table.rows == [(1, None), (2, "x")]


def test_blank_and_duplicate_headers():
    [table] = parse_files([("x.csv", b"name,,name\nx,1,y\n")])
    assert [c.name for c in table.columns] == ["name", "column_2", "name_2"]


def test_values_past_the_header_get_their_own_column():
    [table] = parse_files([("x.csv", b"a\n1,2\n")])
    assert [c.name for c in table.columns] == ["a", "column_2"]


def test_workbook_sheets_are_named_after_file_and_sheet():
    tables = parse_files([("Shop.xlsx", xlsx({
        "Orders": [["id", "total"], [1, 9.5]],
        "Customers": [["id", "name"], [1, "Ann"]],
    }))])
    assert [t.name for t in tables] == ["shop_orders", "shop_customers"]


def test_single_sheet_named_after_file_and_empty_sheets_ignored():
    tables = parse_files([("Shop.xlsx", xlsx({"Data": [["id"], [1]], "Empty": []}))])
    assert [t.name for t in tables] == ["shop"]


def test_workbook_cells_keep_their_types():
    [table] = parse_files([("x.xlsx", xlsx({"S": [["sold_on", "ok", "n"], [datetime(2025, 1, 1), True, 3]]}))])
    assert columns(table) == [("sold_on", "DATE"), ("ok", "BOOLEAN"), ("n", "BIGINT")]


def test_same_table_name_from_two_files_is_deduplicated():
    tables = parse_files([("data.csv", b"a\n1\n"), ("Data.csv", b"a\n2\n")])
    assert [t.name for t in tables] == ["data", "data_2"]


def test_no_files():
    with pytest.raises(IngestError):
        parse_files([])


def test_unsupported_extension_names_the_file():
    with pytest.raises(IngestError, match="notes.txt") as error:
        parse_files([("notes.txt", b"hello")])
    assert error.value.status == 400


def test_empty_file():
    with pytest.raises(IngestError, match="empty"):
        parse_files([("e.csv", b"")])


def test_header_only():
    with pytest.raises(IngestError, match="no data rows"):
        parse_files([("h.csv", b"a,b\n")])


def test_over_four_megabytes_is_413():
    big = b"a\n" + b"1\n" * (2 * 1024 * 1024)
    with pytest.raises(IngestError) as error:
        parse_files([("big.csv", big)])
    assert error.value.status == 413


def test_too_many_tables():
    with pytest.raises(IngestError, match="20"):
        parse_files([(f"t{i}.csv", b"a\n1\n") for i in range(21)])


def test_too_many_columns():
    header = ",".join(f"c{i}" for i in range(101)).encode()
    with pytest.raises(IngestError, match="100"):
        parse_files([("wide.csv", header + b"\n" + b",".join([b"1"] * 101) + b"\n")])


def test_too_many_rows(monkeypatch):
    monkeypatch.setattr(ingest, "MAX_TOTAL_ROWS", 3)
    with pytest.raises(IngestError, match="rows"):
        parse_files([("x.csv", b"a\n1\n2\n3\n4\n")])


def test_not_really_a_workbook():
    with pytest.raises(IngestError, match="valid .xlsx"):
        parse_files([("bad.xlsx", b"not a zip file")])


def test_zip_bomb_is_rejected_before_parsing():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (60 * 1024 * 1024))
    with pytest.raises(IngestError, match="50 MB"):
        parse_files([("bomb.xlsx", buffer.getvalue())])
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: collection error, `ImportError: cannot import name 'IngestError'… 'parse_files'` — specifically `parse_files` is missing.

- [ ] **Step 4: Implement file reading**

In `src/ingest.py`, replace the import block at the top with:

```python
import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal

import openpyxl
```

Append to `src/ingest.py`:

```python
def _is_empty(cell):
    return cell is None or (isinstance(cell, str) and not cell.strip())


def _too_many_rows():
    return IngestError(f"The upload has more than {MAX_TOTAL_ROWS:,} rows in total, which is over the limit.")


def _used_width(rows):
    """Index of the last non-empty cell in any row, plus one."""
    width = 0

    for row in rows:
        for index in range(len(row) - 1, -1, -1):
            if not _is_empty(row[index]):
                width = max(width, index + 1)
                break

    return width


def build_table(name, header, body, label, max_rows):
    """Turn a header row and data rows into a typed Table."""
    width = _used_width([header, *body])

    if width > MAX_COLUMNS:
        raise IngestError(f"{label}: has {width} columns; the limit is {MAX_COLUMNS}.")

    rows = []

    for raw in body:
        cells = [None if _is_empty(cell) else cell for cell in raw]

        if all(cell is None for cell in cells):
            continue

        rows.append((cells + [None] * width)[:width])

        if len(rows) > max_rows:
            raise _too_many_rows()

    if not rows:
        raise IngestError(f"{label}: has a header but no data rows.")

    header = (list(header) + [None] * width)[:width]
    names = dedupe([clean_name(cell, "c", f"column_{index + 1}") for index, cell in enumerate(header)])

    table_columns, converted = [], []

    for index, column_name in enumerate(names):
        values = [row[index] for row in rows]
        type_name, convert = infer_type([value for value in values if value is not None])
        table_columns.append(Column(column_name, type_name))
        converted.append([None if value is None else convert(value) for value in values])

    return Table(name, table_columns, [tuple(column[i] for column in converted) for i in range(len(rows))])


def _decode(data):
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def read_csv(stem, data, filename, max_rows):
    text = _decode(data)

    try:
        delimiter = csv.Sniffer().sniff(text[:64 * 1024], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","

    rows = []

    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            if all(_is_empty(cell) for cell in row):
                continue

            rows.append(row)

            if len(rows) > max_rows + 1:
                raise _too_many_rows()
    except csv.Error as error:
        raise IngestError(f"{filename}: could not be read as CSV ({error}).")

    if not rows:
        raise IngestError(f"{filename}: the file is empty.")

    return [build_table(stem, rows[0], rows[1:], filename, max_rows)]


def read_xlsx(stem, data, filename, max_rows):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise IngestError(f"{filename}: is not a valid .xlsx file.")

    # An .xlsx is a zip archive. Checking the expanded size first stops a
    # small upload that inflates to gigabytes (a zip bomb).
    if sum(info.file_size for info in archive.infolist()) > MAX_XLSX_UNCOMPRESSED_BYTES:
        raise IngestError(f"{filename}: expands to more than 50 MB, which is over the limit.")

    try:
        # data_only=True reads each formula's last saved value; formulas are
        # never evaluated.
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise IngestError(f"{filename}: is not a valid .xlsx file.")

    sheets = []

    try:
        for sheet in workbook.worksheets:
            rows = []

            for row in sheet.iter_rows(values_only=True):
                if all(_is_empty(cell) for cell in row):
                    continue

                rows.append(row)

                if len(rows) > max_rows + 1:
                    raise _too_many_rows()

            if rows:
                sheets.append((sheet.title, rows))
    finally:
        workbook.close()

    if not sheets:
        raise IngestError(f"{filename}: every sheet is empty.")

    tables = []

    for title, rows in sheets:
        name = stem if len(sheets) == 1 else f"{stem}_{title}"
        table = build_table(name, rows[0], rows[1:], f"{filename} (sheet {title})", max_rows)
        max_rows -= len(table.rows)
        tables.append(table)

    return tables


def parse_files(files):
    """Parse (filename, bytes) uploads into Tables with unique, clean names."""
    if not files:
        raise IngestError("No files were uploaded.")

    if sum(len(data) for _, data in files) > MAX_UPLOAD_BYTES:
        raise IngestError("Uploads are limited to 4 MB in total.", status=413)

    tables = []
    remaining = MAX_TOTAL_ROWS

    for filename, data in files:
        stem, _, extension = filename.rpartition(".")
        extension = extension.lower() if stem else ""

        if extension == "csv":
            parsed = read_csv(stem, data, filename, remaining)
        elif extension == "xlsx":
            parsed = read_xlsx(stem, data, filename, remaining)
        else:
            raise IngestError(f"{filename}: only .csv and .xlsx files are supported.")

        remaining -= sum(len(table.rows) for table in parsed)
        tables.extend(parsed)

    if len(tables) > MAX_TABLES:
        raise IngestError(f"The upload makes {len(tables)} tables; the limit is {MAX_TABLES}.")

    names = dedupe([clean_name(table.name, "t", f"table_{index + 1}") for index, table in enumerate(tables)])

    for table, name in zip(tables, names):
        table.name = name

    return tables
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ingest.py -v`
Expected: all PASS (45 tests).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/ingest.py tests/test_ingest.py
git commit -m "Read uploaded CSV and Excel files into typed tables" -m "Adds openpyxl==3.1.5. Enforces the upload limits from the spec, including a zip-bomb check on .xlsx before parsing."
```

---

### Task 4: Result limits and a `bind` parameter

Caps every query at 500 rows and sends at most 50 to Gemini. This also fixes the sample store, where a broad question currently returns every row and pastes them all into the explanation prompt. `stream_results` was checked against the pooled Neon endpoint: a one-million-row query returns after fetching 501 rows.

**Files:**
- Modify: `src/db.py`, `src/schema_loader.py`, `src/ai.py`, `app.py`, `requirements-dev.txt`
- Create: `tests/test_db.py`, `tests/test_schema_loader.py`, `tests/test_app.py`

**Interfaces:**
- Produces:
  - `src.db.MAX_RESULT_ROWS = 500`
  - `execute_query(sql, params=None, bind=None) -> dict` — adds key `truncated: bool`. `bind=None` means the sample engine.
  - `get_database_schema(bind=None) -> str` — output format unchanged.
  - `explain_results(question, results, total_rows=None, truncated=False) -> str`
  - `app.EXPLAIN_ROWS = 50`; `/ask` responses gain `truncated`.

- [ ] **Step 1: Add the test dependency**

Append to `requirements-dev.txt`:

```
httpx==0.28.1
```

Run: `uv pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests**

Create `tests/test_db.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.db import MAX_RESULT_ROWS, execute_query

THOUSAND_ROWS = (
    "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 1000) "
    "SELECT i FROM n"
)


def sqlite():
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


def test_large_results_are_capped():
    result = execute_query(THOUSAND_ROWS, bind=sqlite())
    assert result["success"] is True
    assert result["row_count"] == MAX_RESULT_ROWS == 500
    assert result["truncated"] is True


def test_small_results_are_complete():
    result = execute_query("SELECT 1 AS a UNION ALL SELECT 2", bind=sqlite())
    assert result["rows"] == [{"a": 1}, {"a": 2}]
    assert result["columns"] == ["a"]
    assert result["truncated"] is False


def test_errors_are_reported_and_not_truncated():
    result = execute_query("SELECT * FROM missing_table", bind=sqlite())
    assert result["success"] is False
    assert result["truncated"] is False
    assert "missing_table" in result["error"]
```

Create `tests/test_schema_loader.py`:

```python
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.schema_loader import get_database_schema


def test_schema_lists_tables_columns_and_foreign_keys():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id))"
        ))

    schema = get_database_schema(bind=engine)

    assert "customers\n" in schema
    assert "- name TEXT" in schema
    assert "- FOREIGN KEY: customer_id REFERENCES customers(id)" in schema
```

Create `tests/test_app.py`:

```python
from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def fake_pipeline(monkeypatch, rows, truncated=False):
    """Replace Gemini and the database; record what each step received."""
    calls = {}

    def fake_schema(bind=None):
        calls["schema_bind"] = bind
        return "schema"

    def fake_execute(sql, bind=None):
        calls["query_bind"] = bind
        return {"success": True, "columns": ["n"], "rows": rows, "row_count": len(rows),
                "truncated": truncated, "error": None}

    def fake_explain(question, results, total_rows=None, truncated=False):
        calls["explained"] = results
        calls["total_rows"] = total_rows
        calls["truncated"] = truncated
        return "explanation"

    monkeypatch.setattr(app_module, "get_database_schema", fake_schema)
    monkeypatch.setattr(app_module, "generate_sql", lambda schema, question: "SELECT 1")
    monkeypatch.setattr(app_module, "execute_query", fake_execute)
    monkeypatch.setattr(app_module, "explain_results", fake_explain)
    return calls


def test_ask_sends_at_most_fifty_rows_to_the_explanation(monkeypatch):
    calls = fake_pipeline(monkeypatch, [{"n": i} for i in range(500)], truncated=True)

    response = client.post("/ask", json={"question": "every number please"})

    assert response.status_code == 200
    body = response.json()
    assert body["row_count"] == 500
    assert len(body["rows"]) == 500
    assert body["truncated"] is True
    assert len(calls["explained"]) == 50
    assert calls["total_rows"] == 500
    assert calls["truncated"] is True
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_db.py tests/test_schema_loader.py tests/test_app.py -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_RESULT_ROWS'`; `get_database_schema() got an unexpected keyword argument 'bind'`; and `KeyError: 'truncated'` or a failing assertion in `test_app.py`.

- [ ] **Step 4: Cap results in `src/db.py`**

Below `engine = create_engine(DATABASE_URL)` add:

```python

# Upper bound on rows returned by one question. Rows are streamed from a
# server-side cursor, so a query matching millions of rows stops after
# MAX_RESULT_ROWS + 1 instead of transferring them all.
MAX_RESULT_ROWS = 500
```

Replace the whole `execute_query` function with:

```python
def execute_query(sql: str, params: dict = None, bind=None) -> dict:
    """
    Executes a validated, read-only SQL query.

    bind is the engine to run on; None means the sample store. At most
    MAX_RESULT_ROWS rows come back, and truncated says whether more matched.

    Returns a dict:
        {
            "success": bool,
            "columns": list[str],
            "rows": list[dict],
            "row_count": int,
            "truncated": bool,
            "error": str | None
        }
    """
    try:
        with (bind or engine).connect() as connection:
            if connection.dialect.name == "postgresql":
                # Limit each query to 5 seconds
                connection.execute(text("SET LOCAL statement_timeout = '5000'"))

            result = connection.execution_options(stream_results=True).execute(text(sql), params or {})
            columns = list(result.keys())
            fetched = result.fetchmany(MAX_RESULT_ROWS + 1)
            rows = [dict(row._mapping) for row in fetched[:MAX_RESULT_ROWS]]

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(fetched) > MAX_RESULT_ROWS,
                "error": None,
            }

    except SQLAlchemyError as e:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "error": str(e.__cause__ or e),
        }

    except Exception as e:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "truncated": False,
            "error": str(e),
        }
```

- [ ] **Step 5: Add `bind` to `src/schema_loader.py`**

Replace:

```python
def get_database_schema():
    inspector = inspect(engine)
```

with:

```python
def get_database_schema(bind=None):
    """Describe the tables visible to bind (default: the sample store) for the model."""
    inspector = inspect(bind or engine)
```

- [ ] **Step 6: Tell the explanation prompt when it sees a sample**

In `src/ai.py`, replace the `explain_results` signature and the start of its prompt:

```python
def explain_results(question, results):
    prompt = f"""
You are an AI data analyst.

User question:
{question}

SQL query results:
{results}
```

with:

```python
def explain_results(question, results, total_rows=None, truncated=False):
    scope = ""

    if total_rows is not None and (truncated or total_rows > len(results)):
        matched = f"more than {total_rows}" if truncated else str(total_rows)
        scope = (
            f"\nThese are the first {len(results)} of {matched} result rows. "
            "If the answer depends on rows you cannot see, say it is based on a sample.\n"
        )

    prompt = f"""
You are an AI data analyst.

User question:
{question}

SQL query results:
{results}
{scope}
```

The rest of the prompt and function is unchanged.

- [ ] **Step 7: Send 50 rows to the explanation from `app.py`**

Below the `allowed_origins`/`add_middleware` block and above `class QuestionRequest`, add:

```python
# Only this many rows go into the explanation prompt; the browser still gets
# every returned row for the table and chart.
EXPLAIN_ROWS = 50

```

In `ask_question`, replace:

```python
    explanation = explain_results(
        request.question,
        result["rows"]
    )
```

with:

```python
    explanation = explain_results(
        request.question,
        result["rows"][:EXPLAIN_ROWS],
        total_rows=result["row_count"],
        truncated=result["truncated"],
    )
```

and in the returned dict, below `"row_count": result["row_count"],` add:

```python
        "truncated": result["truncated"],
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `python -m pytest -v`
Expected: all PASS; `test_api.py` still SKIPPED.

- [ ] **Step 9: Commit**

```bash
git add requirements-dev.txt src/db.py src/schema_loader.py src/ai.py app.py tests/test_db.py tests/test_schema_loader.py tests/test_app.py
git commit -m "Cap query results at 500 rows and send 50 to Gemini" -m "Rows are streamed from a server-side cursor so large results stop early. Previously a broad question returned every row and pasted all of them into the explanation prompt. execute_query and get_database_schema gain a bind parameter for running against an uploaded dataset."
```

---

### Task 5: Dataset lifecycle — `src/datasets.py`

**Prerequisite — a test database.** These tests need an owner connection string in `.env` as `TEST_DATABASE_URL`. Prefer a Neon branch: Neon console → your project → Branches → Create branch (`dev`, from `main`) → copy its **owner** connection string. The tests are also safe against the production database — they only create and drop their own `ds_…` schemas and roles, one probe table (`public.databridge_isolation_probe`), and expired metadata rows — but a branch keeps test runs out of live data. Never paste the string into chat or a commit; put it in `.env` only.

**Files:**
- Create: `src/datasets.py`, `tests/test_datasets.py`

**Interfaces:**
- Consumes: `Table`, `Column` from `src.ingest` (Task 2).
- Produces, in `src/datasets.py`:
  - Constants `TTL = timedelta(hours=24)`, `MAX_LIVE_DATASETS = 200`, `META_SCHEMA = "databridge_meta"`
  - `class CapacityError(RuntimeError)`
  - `@dataclass Dataset(id, schema_name, role_name, role_password, tables: list[dict], created_at, expires_at)` with `.public() -> dict` returning `{"id", "tables", "expires_at"}` (ISO string)
  - `create(tables: list[Table]) -> Dataset` — raises `CapacityError`
  - `get(dataset_id: str) -> Dataset | None` — `None` if malformed, unknown or expired
  - `engine_for(dataset: Dataset) -> Engine` — logs in as the dataset's role. **Note:** takes a `Dataset`, not an id, so callers don't look it up twice. Its host comes from the owner connection (`DATABASE_URL`), which in Vercel is Neon's pooled endpoint — same host as `DATABASE_URL_READONLY`.
  - `cleanup() -> int` — number of datasets removed
  - Module state tests may reset: `_owner`, `_meta_ready`, `_engines`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_datasets.py`:

```python
"""
Integration tests for src/datasets.py. They need a real Postgres, named by
TEST_DATABASE_URL (an owner connection string), and are skipped without one.
"""

import os
from datetime import date
from decimal import Decimal

import pytest
from psycopg2 import errors
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from src import datasets
from src.ingest import Column, Table

TEST_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="set TEST_DATABASE_URL to run database tests")

PROBE = "public.databridge_isolation_probe"


def sales_table():
    return Table(
        "sales",
        [Column("id", "BIGINT"), Column("amount", "NUMERIC"), Column("sold_on", "DATE")],
        [(1, Decimal("10.50"), date(2025, 1, 1)), (2, Decimal("20"), None)],
    )


def expire(owner, dataset):
    with owner.begin() as connection:
        connection.execute(
            text(f"UPDATE {datasets.META_SCHEMA}.datasets SET expires_at = now() - interval '1 minute' WHERE id = :id"),
            {"id": dataset.id},
        )


def counts(owner):
    with owner.connect() as connection:
        return (
            connection.execute(text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'ds\\_%'")).scalar(),
            connection.execute(text("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'ds\\_%'")).scalar(),
            connection.execute(text(f"SELECT count(*) FROM {datasets.META_SCHEMA}.datasets")).scalar(),
        )


@pytest.fixture
def owner(monkeypatch):
    engine = create_engine(TEST_URL)
    monkeypatch.setattr(datasets, "_owner", engine)
    monkeypatch.setattr(datasets, "_meta_ready", False)
    datasets._engines.clear()
    datasets.cleanup()
    yield engine
    engine.dispose()


@pytest.fixture
def make(owner):
    created = []

    def _make(*tables):
        dataset = datasets.create(list(tables))
        created.append(dataset)
        return dataset

    yield _make

    for dataset in created:
        expire(owner, dataset)
    datasets.cleanup()


@pytest.fixture
def probe(owner):
    with owner.begin() as connection:
        connection.execute(text(f"CREATE TABLE IF NOT EXISTS {PROBE} (secret TEXT)"))
    yield
    with owner.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {PROBE}"))


def test_create_loads_tables_and_returns_metadata(make):
    dataset = make(sales_table())

    assert len(dataset.id) == 24
    assert dataset.tables == [{
        "name": "sales",
        "columns": [
            {"name": "id", "type": "BIGINT"},
            {"name": "amount", "type": "NUMERIC"},
            {"name": "sold_on", "type": "DATE"},
        ],
        "row_count": 2,
    }]

    with datasets.engine_for(dataset).connect() as connection:
        rows = connection.execute(text("SELECT id, amount, sold_on FROM sales ORDER BY id")).all()

    assert [tuple(row) for row in rows] == [(1, Decimal("10.50"), date(2025, 1, 1)), (2, Decimal("20"), None)]


def test_public_view_hides_credentials(make):
    public = make(sales_table()).public()
    assert set(public) == {"id", "tables", "expires_at"}


def test_get_finds_live_datasets_only(make):
    dataset = make(sales_table())
    assert datasets.get(dataset.id).schema_name == dataset.schema_name
    assert datasets.get("0" * 24) is None
    assert datasets.get("not-an-id") is None
    assert datasets.get("") is None


def test_dataset_role_settings(make):
    dataset = make(sales_table())

    with datasets.engine_for(dataset).connect() as connection:
        row = connection.execute(text(
            "SELECT current_user, current_setting('search_path'), "
            "current_setting('default_transaction_read_only'), current_setting('statement_timeout')"
        )).one()

    assert tuple(row) == (dataset.role_name, dataset.schema_name, "on", "5s")


def test_failed_create_leaves_nothing_behind(owner):
    before = counts(owner)
    broken = Table("broken", [Column("n", "BIGINT")], [("not a number",)])

    with pytest.raises(Exception):
        datasets.create([broken])

    assert counts(owner) == before


@pytest.mark.parametrize("label, sql_for", [
    ("another dataset", lambda other: f"SELECT * FROM {other.schema_name}.sales"),
    ("the public schema", lambda other: f"SELECT * FROM {PROBE}"),
    ("the metadata table", lambda other: f"SELECT * FROM {datasets.META_SCHEMA}.datasets"),
    ("insert", lambda other: "INSERT INTO sales (id) VALUES (99)"),
    ("update", lambda other: "UPDATE sales SET amount = 0"),
    ("delete", lambda other: "DELETE FROM sales"),
    ("drop", lambda other: "DROP TABLE sales"),
    ("create in own schema", lambda other: "CREATE TABLE sneaky (id int)"),
    ("create in public", lambda other: "CREATE TABLE public.sneaky (id int)"),
])
def test_dataset_role_is_isolated(make, probe, label, sql_for):
    mine, other = make(sales_table()), make(sales_table())

    with datasets.engine_for(mine).connect() as connection:
        with pytest.raises(DBAPIError) as error:
            connection.execute(text(sql_for(other)))

    # A permission or read-only error specifically -- not, say, a typo that
    # would make this test pass for the wrong reason.
    assert isinstance(error.value.orig, (errors.InsufficientPrivilege, errors.ReadOnlySqlTransaction)), label


def test_expired_dataset_is_unreachable_then_removed(make, owner):
    dataset = make(sales_table())
    expire(owner, dataset)

    assert datasets.get(dataset.id) is None
    assert datasets.cleanup() >= 1

    with owner.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM pg_namespace WHERE nspname = :s"), {"s": dataset.schema_name}).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM pg_roles WHERE rolname = :r"), {"r": dataset.role_name}).scalar() == 0
        assert connection.execute(
            text(f"SELECT count(*) FROM {datasets.META_SCHEMA}.datasets WHERE id = :id"), {"id": dataset.id}
        ).scalar() == 0


def test_capacity_limit(make, monkeypatch):
    monkeypatch.setattr(datasets, "MAX_LIVE_DATASETS", 0)

    with pytest.raises(datasets.CapacityError):
        make(sales_table())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_datasets.py -v`
Expected: collection error, `ImportError: cannot import name 'datasets' from 'src'`. (If instead every test is SKIPPED, `TEST_DATABASE_URL` is not set — fix the prerequisite first.)

- [ ] **Step 3: Implement `src/datasets.py`**

```python
"""
Uploaded datasets: create, look up, connect to, and clean up.

Each dataset is a Postgres schema holding the uploaded tables, plus a login
role that can read only that schema, in read-only transactions. The owner
connection (DATABASE_URL) is used only in this module, to build and remove
those objects. Generated SQL always runs as the dataset's own role.
"""

import csv
import io
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

TTL = timedelta(hours=24)
MAX_LIVE_DATASETS = 200
META_SCHEMA = "databridge_meta"

DATASET_ID = re.compile(r"^[0-9a-f]{24}$")
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
COLUMN_TYPES = {"BIGINT", "NUMERIC", "BOOLEAN", "DATE", "TIMESTAMP", "TEXT"}

log = logging.getLogger(__name__)

_owner = None
_meta_ready = False
_engines = {}


class CapacityError(RuntimeError):
    """Too many live datasets; the caller should try again later."""


@dataclass
class Dataset:
    id: str
    schema_name: str
    role_name: str
    role_password: str
    tables: list
    created_at: datetime
    expires_at: datetime

    def public(self):
        """The fields that are safe to send to a browser."""
        return {"id": self.id, "tables": self.tables, "expires_at": self.expires_at.isoformat()}


def owner_engine():
    global _owner

    if _owner is None:
        url = os.getenv("DATABASE_URL")

        if not url:
            raise RuntimeError("DATABASE_URL (the owner role) is not set; uploads need it.")

        # NullPool: serverless instances are short-lived, and Neon's pooler
        # already pools connections on the server side.
        _owner = create_engine(url, poolclass=NullPool)

    return _owner


def _ensure_meta():
    """Create the metadata schema on first use. Committed on its own, so a
    failed upload can never roll it back."""
    global _meta_ready

    if _meta_ready:
        return

    with owner_engine().begin() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {META_SCHEMA}"))
        connection.execute(text(f"REVOKE ALL ON SCHEMA {META_SCHEMA} FROM PUBLIC"))
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {META_SCHEMA}.datasets (
                id            TEXT PRIMARY KEY,
                schema_name   TEXT NOT NULL,
                role_name     TEXT NOT NULL,
                role_password TEXT NOT NULL,
                tables        JSONB NOT NULL,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                expires_at    TIMESTAMPTZ NOT NULL
            )
        """))

    _meta_ready = True


def _run(work):
    """Run work(cursor) in one transaction on the owner connection.

    Uses the raw psycopg2 connection because COPY and parameterised
    CREATE ROLE are not available through SQLAlchemy's text().
    """
    raw = owner_engine().raw_connection()

    try:
        cursor = raw.cursor()
        result = work(cursor)
        raw.commit()
        return result
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _check_identifier(name):
    # Names come from src/ingest.py's clean_name, which already guarantees
    # this. Checked again because they are interpolated into SQL.
    if not IDENTIFIER.match(name):
        raise ValueError(f"Unsafe identifier: {name!r}")


def _as_csv(rows):
    """Rows as CSV for COPY. None becomes an empty field, which COPY reads as
    NULL; ingest never produces empty strings, so the two cannot be confused."""
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    buffer.seek(0)
    return buffer


def create(tables):
    """Load tables into a new schema with its own read-only role."""
    for table in tables:
        _check_identifier(table.name)

        for column in table.columns:
            _check_identifier(column.name)

            if column.type not in COLUMN_TYPES:
                raise ValueError(f"Unexpected column type: {column.type!r}")

    _ensure_meta()
    cleanup()

    dataset_id = secrets.token_hex(12)
    schema = f"ds_{dataset_id}"
    role = f"ds_{dataset_id}_ro"
    password = secrets.token_urlsafe(24)
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + TTL

    summary = [
        {
            "name": table.name,
            "columns": [{"name": column.name, "type": column.type} for column in table.columns],
            "row_count": len(table.rows),
        }
        for table in tables
    ]

    def work(cursor):
        cursor.execute(f"SELECT count(*) FROM {META_SCHEMA}.datasets WHERE expires_at > now()")

        if cursor.fetchone()[0] >= MAX_LIVE_DATASETS:
            raise CapacityError("DataBridge is holding as many uploads as it can right now. Try again later.")

        cursor.execute(f"CREATE SCHEMA {schema}")
        cursor.execute(
            f"CREATE ROLE {role} LOGIN PASSWORD %s NOSUPERUSER NOCREATEDB NOCREATEROLE",
            (password,),
        )

        for table in tables:
            qualified = f"{schema}.{table.name}"
            definition = ", ".join(f"{column.name} {column.type}" for column in table.columns)
            names = ", ".join(column.name for column in table.columns)

            cursor.execute(f"CREATE TABLE {qualified} ({definition})")
            cursor.copy_expert(f"COPY {qualified} ({names}) FROM STDIN WITH (FORMAT csv)", _as_csv(table.rows))

        cursor.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
        cursor.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {role}")
        cursor.execute(f"ALTER ROLE {role} SET default_transaction_read_only = on")
        cursor.execute(f"ALTER ROLE {role} SET statement_timeout = '5s'")
        # Lets the model write "sales" instead of "ds_<id>.sales".
        cursor.execute(f"ALTER ROLE {role} SET search_path = {schema}")
        cursor.execute(
            f"INSERT INTO {META_SCHEMA}.datasets "
            "(id, schema_name, role_name, role_password, tables, created_at, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (dataset_id, schema, role, password, json.dumps(summary), created_at, expires_at),
        )

    _run(work)
    return Dataset(dataset_id, schema, role, password, summary, created_at, expires_at)


def get(dataset_id):
    """The dataset with this id, or None if the id is malformed, unknown or expired."""
    if not dataset_id or not DATASET_ID.match(dataset_id):
        return None

    _ensure_meta()

    with owner_engine().connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, schema_name, role_name, role_password, tables, created_at, expires_at "
                f"FROM {META_SCHEMA}.datasets WHERE id = :id AND expires_at > now()"
            ),
            {"id": dataset_id},
        ).one_or_none()

    return Dataset(*row) if row else None


def engine_for(dataset):
    """An engine that logs in as the dataset's own read-only role."""
    engine = _engines.get(dataset.id)

    if engine is None:
        url = owner_engine().url.set(username=dataset.role_name, password=dataset.role_password)
        engine = _engines[dataset.id] = create_engine(url, poolclass=NullPool)

    return engine


def _drop(cursor, dataset_id, schema, role):
    _check_identifier(schema)
    _check_identifier(role)
    cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    cursor.execute(f"DROP ROLE IF EXISTS {role}")
    cursor.execute(f"DELETE FROM {META_SCHEMA}.datasets WHERE id = %s", (dataset_id,))


def cleanup():
    """Remove every expired dataset. Returns how many were removed."""
    _ensure_meta()

    with owner_engine().connect() as connection:
        expired = connection.execute(
            text(f"SELECT id, schema_name, role_name FROM {META_SCHEMA}.datasets WHERE expires_at <= now()")
        ).all()

    removed = 0

    for dataset_id, schema, role in expired:
        try:
            _run(lambda cursor: _drop(cursor, dataset_id, schema, role))
        except Exception:
            # Expired datasets are already unreachable through get(), so a
            # failure here only delays reclaiming storage until the next run.
            log.exception("Could not remove dataset %s; will retry on the next cleanup", dataset_id)
            continue

        _engines.pop(dataset_id, None)
        removed += 1

    return removed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_datasets.py -v`
Expected: all PASS (16 tests). Each creates real schemas on Neon, so expect roughly 30–60 seconds.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -v`
Expected: all PASS; `test_api.py` SKIPPED.

- [ ] **Step 6: Commit**

```bash
git add src/datasets.py tests/test_datasets.py
git commit -m "Add dataset lifecycle with a read-only role per upload" -m "Each upload gets its own schema and a login role that can read only that schema. Tests verify against a real Postgres that a role cannot read other datasets, the sample store or the metadata table, and cannot write."
```

---

### Task 6: API endpoints and the cleanup cron

**Files:**
- Modify: `app.py`, `vercel.json`, `requirements.txt`, `tests/test_app.py`

**Interfaces:**
- Consumes: `parse_files`, `IngestError`, `MAX_UPLOAD_BYTES` (Task 3); `datasets.create/get/engine_for/cleanup`, `datasets.CapacityError`, `datasets.Dataset` (Task 5); `execute_query(..., bind=)`, `get_database_schema(bind=)` (Task 4).
- Produces: `POST /datasets` (201), `GET /datasets/{dataset_id}`, `GET /cron/cleanup`, and `POST /ask` accepting `dataset_id`. `app.py` must call `datasets.<fn>` through the module (`from src import datasets`) so tests can replace them.

- [ ] **Step 1: Add the dependency**

FastAPI needs `python-multipart` to accept file uploads, and refuses to define an upload endpoint without it. Append to `requirements.txt`:

```
python-multipart==0.0.32
```

Run: `uv pip install -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests**

Add to the imports at the top of `tests/test_app.py`:

```python
from datetime import datetime, timezone

from src import datasets
```

Append to `tests/test_app.py`:

```python
FAKE = datasets.Dataset(
    id="a" * 24,
    schema_name="ds_" + "a" * 24,
    role_name="ds_" + "a" * 24 + "_ro",
    role_password="not-a-real-password",
    tables=[{"name": "sales", "columns": [{"name": "n", "type": "BIGINT"}], "row_count": 1}],
    created_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
    expires_at=datetime(2026, 9, 22, tzinfo=timezone.utc),
)


def test_upload_creates_a_dataset(monkeypatch):
    received = {}

    def fake_create(tables):
        received["tables"] = tables
        return FAKE

    monkeypatch.setattr(datasets, "create", fake_create)

    response = client.post("/datasets", files=[("files", ("sales.csv", b"n\n1\n", "text/csv"))])

    assert response.status_code == 201
    assert response.json() == FAKE.public()
    assert "role_password" not in response.text
    assert [table.name for table in received["tables"]] == ["sales"]


def test_upload_rejects_unsupported_files(monkeypatch):
    monkeypatch.setattr(datasets, "create", lambda tables: FAKE)
    response = client.post("/datasets", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert response.status_code == 400
    assert "notes.txt" in response.json()["detail"]


def test_upload_over_four_megabytes_is_413(monkeypatch):
    monkeypatch.setattr(datasets, "create", lambda tables: FAKE)
    big = b"a\n" + b"1\n" * (2 * 1024 * 1024)
    response = client.post("/datasets", files=[("files", ("big.csv", big, "text/csv"))])
    assert response.status_code == 413


def test_upload_at_capacity_is_503(monkeypatch):
    def full(tables):
        raise datasets.CapacityError("busy")

    monkeypatch.setattr(datasets, "create", full)
    response = client.post("/datasets", files=[("files", ("sales.csv", b"n\n1\n", "text/csv"))])
    assert response.status_code == 503


def test_get_dataset(monkeypatch):
    monkeypatch.setattr(datasets, "get", lambda dataset_id: FAKE if dataset_id == FAKE.id else None)
    assert client.get(f"/datasets/{FAKE.id}").json() == FAKE.public()
    assert client.get("/datasets/" + "b" * 24).status_code == 404


def test_ask_about_an_expired_dataset_is_404(monkeypatch):
    fake_pipeline(monkeypatch, [])
    monkeypatch.setattr(datasets, "get", lambda dataset_id: None)
    response = client.post("/ask", json={"question": "how many rows?", "dataset_id": "c" * 24})
    assert response.status_code == 404


def test_ask_about_a_dataset_runs_as_its_role(monkeypatch):
    calls = fake_pipeline(monkeypatch, [{"n": 1}])
    dataset_engine = object()
    monkeypatch.setattr(datasets, "get", lambda dataset_id: FAKE)
    monkeypatch.setattr(datasets, "engine_for", lambda dataset: dataset_engine)

    response = client.post("/ask", json={"question": "how many rows?", "dataset_id": FAKE.id})

    assert response.status_code == 200
    assert calls["schema_bind"] is dataset_engine
    assert calls["query_bind"] is dataset_engine


def test_ask_without_a_dataset_uses_the_sample_store(monkeypatch):
    calls = fake_pipeline(monkeypatch, [{"n": 1}])
    response = client.post("/ask", json={"question": "how many rows?"})
    assert response.status_code == 200
    assert calls["schema_bind"] is None
    assert calls["query_bind"] is None


def test_cleanup_requires_the_cron_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    monkeypatch.setattr(datasets, "cleanup", lambda: 3)

    assert client.get("/cron/cleanup").status_code == 401
    assert client.get("/cron/cleanup", headers={"Authorization": "Bearer wrong"}).status_code == 401

    response = client.get("/cron/cleanup", headers={"Authorization": "Bearer s3cret"})
    assert response.status_code == 200
    assert response.json() == {"removed": 3}


def test_cleanup_is_closed_without_a_configured_secret(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setattr(datasets, "cleanup", lambda: 0)
    assert client.get("/cron/cleanup", headers={"Authorization": "Bearer "}).status_code == 401
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m pytest tests/test_app.py -v`
Expected: the new tests FAIL with `404 Not Found` for `/datasets` and `/cron/cleanup`, and the dataset `/ask` tests fail on the bind assertions. `test_ask_sends_at_most_fifty_rows_to_the_explanation` still passes.

- [ ] **Step 4: Add the endpoints to `app.py`**

Replace the import block at the top of `app.py`:

```python
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.ai import generate_sql, explain_results
from src.sql_validator import validate_sql
from src.db import execute_query
from src.schema_loader import get_database_schema
```

with:

```python
import os
import secrets

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src import datasets
from src.ai import generate_sql, explain_results
from src.ingest import MAX_UPLOAD_BYTES, IngestError, parse_files
from src.sql_validator import validate_sql
from src.db import execute_query
from src.schema_loader import get_database_schema
```

Below `EXPLAIN_ROWS = 50` add:

```python
EXPIRED = (
    "This upload has expired or does not exist. "
    "Uploads are deleted after 24 hours; upload your files again."
)
```

Replace:

```python
class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
```

with:

```python
class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    # Absent means the built-in sample store.
    dataset_id: str | None = Field(default=None, max_length=64)
```

In `ask_question`, replace:

```python
    schema = get_database_schema()
```

with:

```python
    bind = None

    if request.dataset_id:
        dataset = datasets.get(request.dataset_id)

        if dataset is None:
            raise HTTPException(status_code=404, detail=EXPIRED)

        # Generated SQL for an upload runs as that upload's own read-only role.
        bind = datasets.engine_for(dataset)

    schema = get_database_schema(bind=bind)
```

and replace:

```python
    result = execute_query(sql)
```

with:

```python
    result = execute_query(sql, bind=bind)
```

Append to the end of `app.py`:

```python


@app.post("/datasets", status_code=201)
def upload_dataset(files: list[UploadFile] = File(...)):
    uploads, total = [], 0

    for upload in files:
        # Read at most one byte past the remaining budget, so an oversized
        # upload is rejected without being read into memory in full.
        data = upload.file.read(MAX_UPLOAD_BYTES - total + 1)
        total += len(data)

        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploads are limited to 4 MB in total.")

        uploads.append((upload.filename or "upload", data))

    try:
        tables = parse_files(uploads)
    except IngestError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    try:
        dataset = datasets.create(tables)
    except datasets.CapacityError as error:
        raise HTTPException(status_code=503, detail=str(error))

    return dataset.public()


@app.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    dataset = datasets.get(dataset_id)

    if dataset is None:
        raise HTTPException(status_code=404, detail=EXPIRED)

    return dataset.public()


@app.get("/cron/cleanup")
def cron_cleanup(authorization: str | None = Header(default=None)):
    # Vercel Cron sends "Authorization: Bearer <CRON_SECRET>". With no secret
    # configured the endpoint stays closed rather than open.
    secret = os.getenv("CRON_SECRET")

    if not secret or not secrets.compare_digest(authorization or "", f"Bearer {secret}"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    return {"removed": datasets.cleanup()}
```

- [ ] **Step 5: Schedule the cron**

Replace `vercel.json` with:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "app.py": {
      "maxDuration": 60
    }
  },
  "crons": [
    {
      "path": "/cron/cleanup",
      "schedule": "0 3 * * *"
    }
  ]
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest -v`
Expected: all PASS; `test_api.py` SKIPPED; `test_datasets.py` passes or is SKIPPED depending on `TEST_DATABASE_URL`.

- [ ] **Step 7: Check the upload endpoint against the real database**

This writes a real 24-hour dataset to whatever `DATABASE_URL` in `.env` points at, which is harmless: it expires and gets cleaned up.

Run in one terminal: `uvicorn app:app --port 8000`

In another:

```bash
printf 'region,units\nnorth,12\nsouth,7\n' > /tmp/regions.csv
curl -s -F "files=@/tmp/regions.csv" http://127.0.0.1:8000/datasets
```

Expected: `201` JSON with a 24-character `id`, one table `regions` with columns `region TEXT` and `units BIGINT`, `row_count` 2, and an `expires_at` 24 hours out. It must **not** contain `role_password`. Then `curl -s http://127.0.0.1:8000/datasets/<that id>` returns the same JSON. Stop uvicorn.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt app.py vercel.json tests/test_app.py
git commit -m "Add upload, dataset and cleanup endpoints" -m "POST /datasets parses and loads uploads; /ask accepts a dataset_id and runs generated SQL as that dataset's role; GET /cron/cleanup removes expired uploads and requires Vercel's CRON_SECRET. Adds python-multipart==0.0.32, which FastAPI needs for file uploads."
```

---

### Task 7: Upload panel on the home page

**Files:**
- Create: `public/datasets.js`
- Modify: `public/index.html`

**Interfaces:**
- Consumes: `POST /datasets`, response `{id, tables: [{name, columns: [{name, type}], row_count}], expires_at}`.
- Produces, as globals in `public/datasets.js` (loaded before each page's own script): `recentDatasets() -> [{id, expires_at, tables, label}]` (unexpired only), `rememberDataset(dataset, label)`, `forgetDataset(id)`, `expiresIn(isoString) -> "expires in 23h"`.

- [ ] **Step 1: Create the shared helper**

Create `public/datasets.js`:

```js
/* Recent uploads, remembered in this browser. Shared by index.html and
   results.html. The server is the source of truth: an entry here is only a
   shortcut, and a dataset that has expired on the server returns 404. */
const DATASETS_KEY = "dataBridgeDatasets";

function recentDatasets() {
  let list = [];
  try { list = JSON.parse(localStorage.getItem(DATASETS_KEY) || "[]"); } catch {}
  if (!Array.isArray(list)) return [];
  return list.filter((d) => d && d.id && Date.parse(d.expires_at) > Date.now());
}

function rememberDataset(dataset, label) {
  const entry = { id: dataset.id, expires_at: dataset.expires_at, tables: dataset.tables.length, label };
  const list = [entry, ...recentDatasets().filter((d) => d.id !== dataset.id)].slice(0, 5);
  try { localStorage.setItem(DATASETS_KEY, JSON.stringify(list)); } catch {}
}

function forgetDataset(id) {
  try { localStorage.setItem(DATASETS_KEY, JSON.stringify(recentDatasets().filter((d) => d.id !== id))); } catch {}
}

function expiresIn(iso) {
  const ms = Date.parse(iso) - Date.now();
  if (!(ms > 0)) return "expired";
  const hours = Math.floor(ms / 3600000);
  return hours >= 1 ? `expires in ${hours}h` : `expires in ${Math.max(1, Math.round(ms / 60000))}m`;
}
```

- [ ] **Step 2: Add the styles**

In `public/index.html`, insert immediately before the single `</style>` tag:

```css
/* ---------- Use your own data ---------- */
.byod {
  width: 100%; max-width: 760px; margin-top: 40px; padding: 26px 28px;
  text-align: left; border: 1px solid var(--border); border-radius: var(--radius-lg);
  background: var(--surface);
}
.byod h3 { margin: 0; font-size: 18px; font-weight: 600; color: var(--text); }
.byod-head p { margin: 6px 0 0; font-size: 14px; line-height: 1.5; color: var(--muted); }
.drop {
  margin-top: 18px; display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 26px 16px; border: 1.5px dashed var(--border-strong); border-radius: var(--radius-md);
  cursor: pointer; transition: border-color .2s var(--ease), background .2s var(--ease);
}
.drop:hover, .drop.over { border-color: var(--steel); background: var(--surface-hover); }
.drop-main { font-size: 15px; color: var(--text); }
.drop-sub { font-size: 12.5px; color: var(--dim); }
.file-list { list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 6px; }
.file-list li { display: flex; justify-content: space-between; gap: 12px; font: 13.5px var(--mono); color: var(--muted); }
.file-list li span:first-child { overflow-wrap: anywhere; }
.file-list .size { flex: none; color: var(--dim); }
.byod-msg { margin: 12px 0 0; min-height: 1em; font-size: 13.5px; color: var(--muted); }
.byod-msg.err { color: var(--danger); }
/* Own button style: .btn hides its label on small screens. */
.byod-btn {
  margin-top: 14px; display: inline-flex; align-items: center; gap: 8px;
  padding: 11px 18px; border: 0; border-radius: var(--radius-pill);
  background: var(--text); color: var(--bg); font: 600 14px var(--font);
  cursor: pointer; text-decoration: none; transition: transform .2s var(--ease);
}
.byod-btn:hover { transform: translateY(-1px); }
.byod-btn:disabled { opacity: .6; cursor: progress; transform: none; }
.preview { margin-top: 18px; display: grid; gap: 12px; }
.tcard { padding: 14px 16px; border: 1px solid var(--border); border-radius: var(--radius-md); }
.tcard-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; }
.tname { font: 14px var(--mono); color: var(--text); overflow-wrap: anywhere; }
.tcount { flex: none; font-size: 12.5px; color: var(--dim); }
.tcols { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.col {
  display: inline-flex; gap: 6px; padding: 3px 9px; border: 1px solid var(--border);
  border-radius: var(--radius-pill); font: 12.5px var(--mono); color: var(--muted);
}
.ctype { color: var(--steel); }
.preview .byod-btn { justify-self: start; margin-top: 4px; }
.recent-ds { margin-top: 16px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.recent-ds .try { margin: 0 4px 0 0; }
.recent-ds .chip { text-decoration: none; }
.file-list[hidden], .preview[hidden], .recent-ds[hidden], .byod-btn[hidden] { display: none; }
@media (max-width: 640px) { .byod { padding: 20px 16px; } }
```

- [ ] **Step 3: Add the markup**

In `public/index.html`, insert immediately before `<div class="features rise" style="--i:6" id="features">`:

```html
    <section class="byod rise" style="--i:6" id="byod" aria-labelledby="byodTitle">
      <div class="byod-head">
        <h3 id="byodTitle">Use your own data</h3>
        <p>Upload CSV or Excel files, up to 4 MB in total. Each file or sheet becomes a table you can ask about. Uploads are deleted after 24 hours.</p>
      </div>
      <label class="drop" id="drop">
        <input type="file" id="fileInput" accept=".csv,.xlsx" multiple hidden />
        <span class="drop-main">Drop files here or <u>browse</u></span>
        <span class="drop-sub">.csv and .xlsx · several files at once</span>
      </label>
      <ul class="file-list" id="fileList" hidden></ul>
      <p class="byod-msg" id="byodMsg" role="status"></p>
      <button type="button" class="byod-btn" id="uploadBtn" hidden>Upload</button>
      <div class="preview" id="preview" hidden></div>
      <div class="recent-ds" id="recentDatasets" hidden></div>
    </section>

```

Then renumber the two elements after it so the entrance animation stays in order: change `<div class="features rise" style="--i:6" id="features">` to `style="--i:7"`, and `<button class="scroll rise" style="--i:7" id="scrollBtn" type="button">` to `style="--i:8"`.

Replace the fourth feature card's text:

```html
        <h4>Built for Real Data</h4>
        <p>Works with your PostgreSQL database</p>
```

with:

```html
        <h4>Bring Your Own Data</h4>
        <p>Upload CSV or Excel and ask away</p>
```

Immediately before the page's `<script>` tag (the one whose first comment is `CONFIG — change these if your FastAPI setup differs`), add:

```html
<script src="datasets.js"></script>
```

- [ ] **Step 4: Add the behaviour**

In `public/index.html`, insert immediately before the closing `</script>` of the main script (directly after the `form.addEventListener("submit", ...)` block):

```js

/* =========================================================
   5. Use your own data: pick files -> upload -> preview
   ========================================================= */
const MAX_UPLOAD = 4 * 1024 * 1024;
const fileInput = $("#fileInput"), drop = $("#drop"), fileList = $("#fileList"),
      uploadBtn = $("#uploadBtn"), byodMsg = $("#byodMsg"), preview = $("#preview");
let chosen = [];

const size = (n) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;

function setMessage(text, isError) {
  byodMsg.textContent = text;
  byodMsg.className = "byod-msg" + (isError ? " err" : "");
}

function choose(files) {
  const all = [...files];
  chosen = all.filter((f) => /\.(csv|xlsx)$/i.test(f.name));
  const skipped = all.length - chosen.length;
  const total = chosen.reduce((sum, f) => sum + f.size, 0);

  fileList.replaceChildren(...chosen.map((f) => {
    const li = el("li");
    li.append(el("span", null, f.name), el("span", "size", size(f.size)));
    return li;
  }));
  fileList.hidden = !chosen.length;
  preview.hidden = true;
  uploadBtn.hidden = true;

  if (!chosen.length) return setMessage(skipped ? "Only .csv and .xlsx files are supported." : "", skipped > 0);
  if (total > MAX_UPLOAD) return setMessage(`These files add up to ${size(total)}; the limit is 4 MB.`, true);

  uploadBtn.hidden = false;
  setMessage(skipped ? `${skipped} file(s) skipped: only .csv and .xlsx are supported.` : `${size(total)} in total.`, false);
}

fileInput.addEventListener("change", () => choose(fileInput.files));
["dragenter", "dragover"].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((type) => drop.addEventListener(type, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => choose(e.dataTransfer.files));

function showPreview(dataset) {
  preview.replaceChildren();
  dataset.tables.forEach((t) => {
    const card = el("div", "tcard"), head = el("div", "tcard-head"), cols = el("div", "tcols");
    head.append(el("span", "tname", t.name), el("span", "tcount", `${t.row_count.toLocaleString()} rows`));
    t.columns.forEach((c) => {
      const chip = el("span", "col");
      chip.append(el("span", null, c.name), el("span", "ctype", c.type.toLowerCase()));
      cols.append(chip);
    });
    card.append(head, cols);
    preview.append(card);
  });
  const go = el("a", "byod-btn", "Ask about this data");
  go.href = "results.html?ds=" + encodeURIComponent(dataset.id);
  preview.append(go);
  preview.hidden = false;
}

uploadBtn.addEventListener("click", async () => {
  const body = new FormData();
  chosen.forEach((f) => body.append("files", f));
  uploadBtn.disabled = true;
  setMessage("Uploading and reading your files…", false);

  try {
    const res = await fetch(API_BASE + "/datasets", { method: "POST", body });
    let data = {};
    try { data = await res.json(); } catch {}
    if (!res.ok) return setMessage(typeof data.detail === "string" ? data.detail : `Upload failed (${res.status}).`, true);

    rememberDataset(data, chosen.map((f) => f.name).join(", "));
    showPreview(data);
    renderRecentDatasets();
    uploadBtn.hidden = true;
    fileList.hidden = true;
    setMessage("Here's what we found. Check the column types, then ask away.", false);
  } catch {
    setMessage("Couldn't reach the API.", true);
  } finally {
    uploadBtn.disabled = false;
  }
});

function renderRecentDatasets() {
  const box = $("#recentDatasets"), items = recentDatasets();
  box.replaceChildren();
  box.hidden = !items.length;
  if (!items.length) return;
  box.append(el("span", "try", "Your recent uploads:"));
  items.forEach((d) => {
    const link = el("a", "chip", `${d.label} · ${expiresIn(d.expires_at)}`);
    link.href = "results.html?ds=" + encodeURIComponent(d.id);
    box.append(link);
  });
}
renderRecentDatasets();
```

- [ ] **Step 5: Check it in a browser**

Run the API (`uvicorn app:app --port 8000`) and serve the pages (`python -m http.server 5500 --directory public`), then open `http://127.0.0.1:5500/`. On port 5500 the page calls the local API automatically.

Check each of these, taking a screenshot of the preview:
1. Choosing `notes.txt` shows "Only .csv and .xlsx files are supported." and no Upload button.
2. Choosing a file over 4 MB shows the size message and no Upload button.
3. Choosing `/tmp/regions.csv` from Task 6 plus a two-sheet `.xlsx` lists both files, then Upload shows three table cards with column types and row counts, plus an "Ask about this data" link to `results.html?ds=<id>`.
4. After a reload, "Your recent uploads:" shows the upload.
5. At 375px wide (`resize_window` preset `mobile`), there's no horizontal scroll and the buttons show their text.

Stop both servers.

- [ ] **Step 6: Commit**

```bash
git add public/datasets.js public/index.html
git commit -m "Add the upload panel and table preview to the home page"
```

---

### Task 8: Dataset support on the results page

**Files:**
- Modify: `public/results.html`

**Interfaces:**
- Consumes: `GET /datasets/{id}`; `POST /ask` with `dataset_id` and the `truncated` response flag; `recentDatasets`, `rememberDataset`, `forgetDataset`, `expiresIn` from `public/datasets.js`.

- [ ] **Step 1: Add the styles**

Insert immediately before the single `</style>` tag in `public/results.html`:

```css
/* ---------- Active uploaded dataset ---------- */
.ds-badge {
  margin-top: 16px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px;
  padding: 10px 14px; border: 1px solid var(--border); border-radius: var(--radius-md);
  background: var(--surface); font-size: 13.5px; color: var(--muted);
}
.ds-badge[hidden] { display: none; }
.ds-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--steel); flex: none; }
.ds-text { color: var(--text); }
.ds-tables { font-family: var(--mono); font-size: 12.5px; color: var(--dim); overflow-wrap: anywhere; }
.ds-switch { margin-left: auto; color: var(--muted); }
.ds-switch:hover { color: #fff; }
```

- [ ] **Step 2: Add the markup and the shared script**

Insert immediately before `<div class="recent rise" style="--i:3" id="recent" hidden></div>`:

```html
    <div class="ds-badge rise" style="--i:3" id="dsBadge" hidden></div>
```

Immediately before the page's main `<script>` tag (the one whose first comment is `CONFIG — same as index.html`), add:

```html
<script src="datasets.js"></script>
```

- [ ] **Step 3: Read the dataset from the URL**

Directly below the line `const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;` add:

```js
const params = new URLSearchParams(location.search);
const dsId = params.get("ds");
// Recent questions are kept per dataset: sample-store questions make no sense
// against someone's upload, and vice versa.
const RECENT_KEY = dsId ? "dataBridgeRecent:" + dsId : "dataBridgeRecent";
let activeDataset = null, expired = false;
```

- [ ] **Step 4: Carry the truncation flag through rendering**

In `normalize`, replace:

```js
  return { sql, explanation, rows, columns: columns || [] };
```

with:

```js
  return { sql, explanation, rows, columns: columns || [], truncated: !!d.truncated };
```

Replace `function buildTable(rows, columns) {` with `function buildTable(rows, columns, truncated) {`, and inside it replace:

```js
  cell.append(el("p", "meta", `${rows.length} row${rows.length === 1 ? "" : "s"}` + (rows.length > 100 ? " (showing first 100)" : "")));
```

with:

```js
  let meta = `${rows.length}${truncated ? "+" : ""} row${rows.length === 1 ? "" : "s"}`;
  if (truncated) meta += " (more matched; results are capped at 500)";
  if (rows.length > 100) meta += " · showing the first 100";
  cell.append(el("p", "meta", meta));
```

In `render`, replace:

```js
  const { sql, explanation, rows, columns } = normalize(data);
```

with:

```js
  const { sql, explanation, rows, columns, truncated } = normalize(data);
```

and replace `table = buildTable(rows, columns);` with `table = buildTable(rows, columns, truncated);`. It's on the line starting `const chart = buildChart(rows, columns),`.

- [ ] **Step 5: Keep recent questions per dataset**

In `getRecent` and `pushRecent`, replace both occurrences of the string `"dataBridgeRecent"` with `RECENT_KEY`. The key is the variable, so drop the quotes.

- [ ] **Step 6: Send the dataset with each question**

In `run`, replace:

```js
  history.replaceState(null, "", "?q=" + encodeURIComponent(q));   // shareable / refresh-safe URL
```

with:

```js
  const query = new URLSearchParams();
  if (dsId) query.set("ds", dsId);
  query.set("q", q);
  history.replaceState(null, "", "?" + query);   // shareable / refresh-safe URL
```

Replace:

```js
      body: JSON.stringify({ [REQUEST_KEY]: q }),
```

with:

```js
      body: JSON.stringify({ [REQUEST_KEY]: q, ...(activeDataset ? { dataset_id: activeDataset.id } : {}) }),
```

Directly above `if (!res.ok) {` in `run`, add:

```js
    if (res.status === 404 && activeDataset) { forgetDataset(activeDataset.id); return showExpired(); }
```

In `run`'s `finally` block, replace `btn.disabled = false;` with `btn.disabled = expired;`.

- [ ] **Step 7: Badge, expiry, and loading the dataset first**

Replace the whole block at the bottom of the script:

```js
/* ---------- On load: read ?q= from the URL ---------- */
const initial = new URLSearchParams(location.search).get("q");
if (initial) run(initial);
else {
  const box = el("div", "empty", "Ask a question above to see the SQL, chart and insight here.");
  resultEl.append(box);
  renderRecent("");
}
```

with:

```js
/* ---------- Uploaded dataset: badge and expiry ---------- */
function renderBadge(ds) {
  const badge = $("#dsBadge");
  const count = ds.tables.length;
  badge.replaceChildren(
    el("span", "ds-dot"),
    el("span", "ds-text", `Your data · ${count} table${count === 1 ? "" : "s"} · ${expiresIn(ds.expires_at)}`),
    el("span", "ds-tables", ds.tables.map((t) => t.name).join(", ")),
  );
  const back = el("a", "ds-switch", "Use sample data instead");
  back.href = "results.html";
  badge.append(back);
  badge.hidden = false;
}

function showExpired() {
  clearInterval(stageTimer);
  expired = true;
  input.disabled = true;
  btn.disabled = true;
  $("#dsBadge").hidden = true;
  resultEl.replaceChildren();
  const box = el("div", "error", "This upload has expired or doesn't exist. Uploads are deleted after 24 hours.");
  const foot = el("div", "r-foot"), again = el("a", "r-link", "Upload your files again");
  again.href = "index.html#byod";
  foot.append(again);
  resultEl.append(box, foot);
}

/* ---------- On load: load the dataset (if any), then read ?q= ---------- */
async function start() {
  if (dsId) {
    try {
      const res = await fetch(API_BASE + "/datasets/" + encodeURIComponent(dsId));
      if (res.status === 404) { forgetDataset(dsId); return showExpired(); }
      if (!res.ok) throw new Error(String(res.status));
      activeDataset = await res.json();
    } catch {
      return showError("Your data", "Couldn't load this dataset.", `Make sure the API is reachable at ${API_BASE || location.origin}.`);
    }
    // Keep the file names if this browser uploaded it; a shared link gets table names.
    if (!recentDatasets().some((d) => d.id === dsId)) {
      rememberDataset(activeDataset, activeDataset.tables.map((t) => t.name).join(", "));
    }
    renderBadge(activeDataset);
    input.placeholder = "Ask a question about your uploaded data...";
  }

  const initial = params.get("q");
  if (initial) run(initial);
  else {
    const box = el("div", "empty", activeDataset
      ? "Ask a question about your uploaded data to see the SQL, chart and insight here."
      : "Ask a question above to see the SQL, chart and insight here.");
    resultEl.append(box);
    renderRecent("");
  }
}
start();
```

- [ ] **Step 8: Check it in a browser**

Start the API and the static server as in Task 7. `/ask` needs a real `GEMINI_API_KEY` in `.env`. Without one, check items 1, 3 and 4 locally and leave item 2 for the live check in Task 9.

1. Open `http://127.0.0.1:5500/results.html?ds=<id from Task 7>`. The badge shows "Your data · 3 tables · expires in 23h" and the table names, and the placeholder mentions uploaded data.
2. Ask "Which region sold the most units?" and get an answer from the uploaded data. The URL becomes `?ds=<id>&q=...`.
3. Open `results.html?ds=` followed by 24 zeros. It shows the expired message with an "Upload your files again" link, and the input is disabled.
4. Open `results.html` with no `ds`. The sample store works as before, with no badge.

Take a screenshot of item 1 or 2. Stop both servers.

- [ ] **Step 9: Commit**

```bash
git add public/results.html
git commit -m "Ask questions about an uploaded dataset from the results page" -m "Reads ds from the URL, sends dataset_id with each question, shows which data is active, handles expired uploads, and notes when results were capped at 500 rows."
```

---

### Task 9: Documentation, deploy, and live check

**Files:**
- Modify: `README.md`, `.env.example`

- [ ] **Step 1: Document the new configuration**

In `.env.example`, append:

```
# Vercel Cron sends this as "Authorization: Bearer <value>" to /cron/cleanup.
# Any long random string; set the same value in Vercel.
CRON_SECRET=

# Owner connection string for a throwaway database (e.g. a Neon branch).
# Only needed to run tests/test_datasets.py.
TEST_DATABASE_URL=
```

- [ ] **Step 2: Update the README**

In `README.md`:

1. In the project layout table, add these rows after the `src/schema_loader.py` row:

```
| `src/ingest.py` | Turns uploaded CSV/Excel files into typed tables. |
| `src/datasets.py` | Creates, finds and removes uploaded datasets, each in its own schema with its own read-only role. |
| `public/datasets.js` | Remembers recent uploads in the browser. |
```

2. Under "Sample questions", add a paragraph:

```
You can also upload your own CSV or Excel files from the home page. Each
file or sheet becomes a table, questions can join across them, and uploads
are deleted after 24 hours.
```

3. In the Vercel environment variables table, add:

```
| `CRON_SECRET` | Any long random string; lets the daily cleanup job run |
```

and note below the table that `DATABASE_URL`, set by the Neon integration, is now also used, by `src/datasets.py`, to create uploads.

4. In the Security section, add a paragraph:

```
Each upload gets its own Postgres schema and its own login role that can
read only that schema, in read-only transactions. Questions about an upload
run as that role, so they cannot see other uploads or the sample data. One
known gap: Postgres lets any role list other schemas' table names through
its system catalogs, though not their contents.
```

5. Replace the Tests section with:

````
## Tests

```bash
pytest
```

runs everything that needs no external services. Two groups are opt-in:

- `tests/test_datasets.py` needs a real Postgres. Set `TEST_DATABASE_URL`
  in `.env` to an owner connection string, ideally a Neon branch.
- `tests/test_api.py` calls a running server and makes real Gemini calls:
  `LIVE_API_URL=http://127.0.0.1:8000 pytest tests/test_api.py`.
````

- [ ] **Step 3: Run the full suite one last time**

Run: `python -m pytest -v`
Expected: all PASS. `test_datasets.py` passes if `TEST_DATABASE_URL` is set; `test_api.py` is SKIPPED.

- [ ] **Step 4: Commit and open the PR**

```bash
git add README.md .env.example
git commit -m "Document uploads, CRON_SECRET and the test setup"
git push -u origin feat/bring-your-own-data
gh pr create --repo Cronosspyy/DataBridge --base main --head feat/bring-your-own-data --title "Bring your own data: CSV and Excel uploads" --body "Implements docs/superpowers/specs/2026-09-21-bring-your-own-data-design.md. Before merging, add CRON_SECRET in Vercel (Settings -> Environments); new dependencies are openpyxl and python-multipart."
```

The PR body must carry no Claude attribution.

- [ ] **Step 5: Configure Vercel (the user does this)**

Ask the user to add `CRON_SECRET` in Vercel → Settings → Environments, **before** merging. To generate a value without it passing through the chat, run:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))" | clip
```

This puts it on the Windows clipboard. On macOS, use `pbcopy` in place of `clip`.

Then the PR can be merged. The merge pushes to `main` and deploys.

- [ ] **Step 6: Live end-to-end check**

Once the deployment is Ready, check on `https://databridge-lilac.vercel.app`:

1. `GET /health` returns `{"status":"ok"}`.
2. The sample store still answers "Top 3 product categories by revenue" with Beauty, Electronics and Clothing, and the response has `"truncated": false`.
3. Upload `regions.csv` plus a two-sheet workbook from the home page. The preview shows three tables.
4. Ask a question that joins two uploaded tables. The answer is correct and the SQL uses bare table names.
5. Copy the results URL into a private window. The same dataset loads, which confirms the link is shareable.
6. `GET /cron/cleanup` with no header returns `401`.
7. Vercel → Settings → Cron Jobs lists `/cron/cleanup` at `0 3 * * *`.

Report each result with evidence (response bodies and a screenshot). Do not claim success for any item that wasn't checked.
