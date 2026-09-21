# Bring your own data — design

**Status:** proposed, awaiting review
**Date:** 2026-09-21

## Goal

Today DataBridge answers questions about one built-in e-commerce database. This
feature lets a visitor upload their own CSV and Excel files and ask questions
about them, with no account, while the built-in sample keeps working exactly as
it does now.

## Decisions

| Question | Decision |
| --- | --- |
| How users bring data | File upload. No connection strings, so we never hold anyone's database credentials or connect to arbitrary hosts. |
| Formats | `.csv` and `.xlsx`, several files per upload. Each CSV and each non-empty sheet becomes one table, so questions can join them. |
| Lifetime | 24 hours from upload, then deleted. No accounts; the dataset id in the link is the only key. |
| Where it lives | A separate Postgres schema per upload in the existing Neon database, read through a login role that can see only that schema. |

Rejected: storing uploads as DuckDB files in Vercel Blob. Isolation is simpler
there, but it adds a second query engine, a second storage service and a
second SQL dialect, and throws away the read-only role setup that is already
built and verified.

## User flow

1. The home page gets a **Use your own data** panel under the question box.
   Files can be dropped or picked; the page lists them with sizes and refuses a
   selection over 4 MB before sending anything.
2. After upload the page shows each table's name, its columns with their
   detected types, and its row count, then an **Ask about this data** button.
   This preview is where users catch a column that was read as text but should
   be a number.
3. The results page URL carries the dataset: `results.html?ds=<id>&q=...`.
   Anyone with the link can ask about that dataset until it expires.
4. A badge on the results page names the active data — "Your data · 3 tables ·
   expires in 23h" — with a switch back to the sample store.
5. Recent uploads are remembered in `localStorage`, so a refresh or a return
   visit within 24 hours does not lose them.

## API

| Endpoint | Behaviour |
| --- | --- |
| `POST /datasets` | Multipart upload, field `files`. Returns `201 {id, tables: [{name, columns: [{name, type}], row_count}], expires_at}`. |
| `GET /datasets/{id}` | The same metadata, or `404` if unknown or expired. |
| `POST /ask` | Gains optional `dataset_id`. Absent means the sample store, so existing callers are unaffected. |
| `GET /cron/cleanup` | Drops expired datasets. Requires `Authorization: Bearer <CRON_SECRET>`, which Vercel Cron sends; anything else gets `401`. |

`/ask` responses gain a `truncated` boolean (see Result limits).

## Components

### `src/ingest.py` — new

Turns uploaded files into in-memory tables. Never touches the database, so it
is tested without one.

- **CSV:** stdlib `csv`. Decode as UTF-8 (with or without BOM), falling back to
  Latin-1. Delimiter detected with `csv.Sniffer` among comma, semicolon, tab
  and pipe, defaulting to comma. First row is the header.
- **Excel:** `openpyxl` in read-only mode with `data_only=True`, so formulas
  are read as their last saved values and never evaluated. Each non-empty sheet
  becomes a table named `<file>_<sheet>`; a workbook with a single non-empty
  sheet is named after the file alone. First row is the header.
- **Names:** lowercased, runs of non-alphanumerics collapsed to `_`, a leading
  digit prefixed with `t_` (tables) or `c_` (columns), trimmed to 63
  characters. Blank headers become `column_<n>`. Duplicates get `_2`, `_3`. A
  name that is a Postgres reserved word gets a trailing `_`.
- **Types**, decided per column from its non-empty values, first match wins:

  | Type | Rule |
  | --- | --- |
  | `BIGINT` | every value is an integer |
  | `NUMERIC` | every value is a plain decimal number, e.g. `12.5` |
  | `BOOLEAN` | every value is `true` or `false`, case-insensitive |
  | `DATE` | every value is ISO `YYYY-MM-DD` |
  | `TIMESTAMP` | every value is ISO `YYYY-MM-DD HH:MM[:SS]`, with a space or `T` |
  | `TEXT` | anything else |

  Only ISO dates are parsed, deliberately. `03/04/2025` is ambiguous between day
  and month order, so it stays text rather than being silently misread.
  Likewise `1,234` stays text. Excel cells arrive already typed and are used as
  they are. Empty cells become `NULL`. A column with no non-empty values is
  `TEXT`.
- **Limits:** 4 MB total upload, 20 tables, 100 columns per table, 200,000 rows
  total. For `.xlsx`, the zip's total uncompressed size is checked before
  parsing and must be under 50 MB, which stops zip bombs.

### `src/datasets.py` — new

Owns a dataset's lifecycle. The only module that uses the owner connection
(`DATABASE_URL`).

- **Identifiers:** the id is 24 random hex characters (96 bits). Schema
  `ds_<id>`, role `ds_<id>_ro`. Hex keeps both valid unquoted identifiers.
- **`create(tables)`**, in a single transaction, so a failure at any step
  leaves nothing behind:
  1. `CREATE SCHEMA ds_<id>`
  2. `CREATE ROLE ds_<id>_ro LOGIN PASSWORD <random> NOSUPERUSER NOCREATEDB NOCREATEROLE`
  3. Create each table, then `COPY` its rows in.
  4. `GRANT USAGE ON SCHEMA ds_<id>` and `GRANT SELECT ON ALL TABLES IN SCHEMA ds_<id>` to the role.
  5. On the role, set `default_transaction_read_only = on`,
     `statement_timeout = '5s'` and `search_path = ds_<id>`. The search path
     means Gemini can write `sales` rather than `ds_<id>.sales`.
  6. Insert the metadata row.
- **`get(id)`** returns metadata, or `None` if missing or past `expires_at`.
  Expiry is enforced here, so an expired dataset is unreachable immediately,
  whether or not cleanup has run.
- **`engine_for(id)`** returns an engine logged in as the dataset's role, on the
  same pooled host as `DATABASE_URL_READONLY`. Engines are cached per warm
  function instance.
- **`cleanup()`** drops the schema (`CASCADE`), the role and the metadata row
  for every expired dataset.
- **Capacity:** `create` refuses when 200 unexpired datasets already exist.
  `create` runs `cleanup()` first, so the limit does not depend on the cron
  having run.

**Metadata** lives in its own schema, `databridge_meta`, with no grants to any
other role:

```sql
CREATE TABLE databridge_meta.datasets (
    id            TEXT PRIMARY KEY,
    schema_name   TEXT NOT NULL,
    role_name     TEXT NOT NULL,
    role_password TEXT NOT NULL,
    tables        JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ NOT NULL
);
```

The role password is stored in plain text. Reading it requires the owner
credentials, and the role it unlocks can read only one temporary upload, which
its own uploader provided. Encrypting it would protect that one upload only
against someone who already holds the owner credentials, which is not a
meaningful gain.

### `src/db.py` and `src/schema_loader.py` — small changes

- `execute_query(sql, engine=None)`: `None` means the existing sample engine.
- `get_database_schema(engine=None, schema="public")`: reflects the given
  schema. Output format unchanged.

### `app.py`

The new endpoints, and `/ask` choosing the engine: sample by default, or
`engine_for(dataset_id)` after `get()` confirms the dataset is live.

### Frontend

- `public/index.html`: the upload panel and the table preview.
- `public/results.html`: reads `ds` from the URL, sends `dataset_id` with each
  question, shows the dataset badge, and handles `404` by offering a new upload.

## Result limits

This applies to the sample store too, and fixes the unbounded-results issue
noted in the original code review.

- `execute_query` fetches at most 501 rows from the cursor, without rewriting
  the SQL, returns the first 500, and sets `truncated: true` if a 501st existed.
- Only the first 50 rows go into the explanation prompt, together with the
  number of rows returned, so the explanation can say it is describing a sample.
- The results table already notes when it shows only part of a result; it will
  use `truncated` to say so accurately.

## Isolation

What a dataset role can do:

- `SELECT` on tables in its own schema, in read-only transactions, with a
  5-second limit per statement.

What it cannot do, each of which is an explicit test:

- read another dataset's tables
- read the sample store's tables in `public`
- read `databridge_meta`
- insert, update, delete, drop or create anything

**Accepted gap:** any Postgres role can read the system catalogs, so a dataset
role can *list* other datasets' schema and table names, though not their
contents. Hiding catalog entries means fighting Postgres internals for little
benefit, so this is documented rather than prevented.

## Cleanup

- `vercel.json` gains a daily cron: `{"path": "/cron/cleanup", "schedule": "0 3 * * *"}`.
  Daily is the most frequent schedule the Vercel Hobby plan allows.
- Expired datasets are already unreachable through `get()`, so the cron only
  reclaims storage; it does not enforce expiry.

## Errors

| Case | Status | Message |
| --- | --- | --- |
| Unsupported extension | 400 | names the file |
| File cannot be parsed | 400 | names the file and the reason |
| Empty file, or header only | 400 | names the file |
| Over a table, column or row limit | 400 | names the limit |
| Upload over 4 MB | 413 | names the limit |
| Unknown or expired dataset | 404 | the page offers to upload again |
| At the 200-dataset capacity | 503 | "busy, try again later" |

Errors from answering questions are unchanged.

## Configuration

| Variable | Status |
| --- | --- |
| `DATABASE_URL` | Already set in Vercel by the Neon integration (owner role). Now used by `datasets.py`. |
| `DATABASE_URL_READONLY` | Already set. Still used for the sample store; its host is reused for dataset roles. |
| `CRON_SECRET` | **New.** Must be added in Vercel before the cron works. |

New dependency: `openpyxl`, for reading Excel files. Pure Python and small.

## Testing

- **Unit, `tests/test_ingest.py`:** name cleaning, each type rule including the
  ambiguous-date and thousands-separator cases, multi-sheet and single-sheet
  Excel naming, encoding fallback, delimiter detection, every limit, and the
  zip bomb guard. Fixture files are generated inside the tests.
- **Integration, `tests/test_datasets.py`:** runs against a real Postgres named
  by `TEST_DATABASE_URL` and skips when that is unset. Covers:
  - an upload produces the right tables, types and row counts
  - a failure partway through `create` leaves no schema, role or metadata row
  - the isolation matrix above, each case asserting a permission error
  - `get()` returns `None` after expiry, and `cleanup()` removes the schema,
    role and row
  - the capacity limit
- **Existing tests** in `tests/test_validator.py` keep passing unchanged.
- **End to end on the live site:** upload a CSV and a two-sheet workbook, ask a
  question that joins across them, check the badge and the shareable link, and
  confirm a `404` once a dataset has expired.

## Build order

The riskiest assumption is checked first:

1. **Check two things against the real Neon database**, since everything else
   depends on them:
   - the pooled endpoint accepts a login from a role created with SQL;
   - `CREATE ROLE`, `CREATE TABLE` and `COPY` all succeed inside one
     transaction through the pooled owner connection, which is what
     `DATABASE_URL` is in Vercel. The existing loader has only been run on the
     direct endpoint.

   If either fails, the affected connections use the direct endpoint instead,
   which works but holds more connections open; this spec gets updated before
   continuing.
2. `ingest.py` with its unit tests.
3. `datasets.py` with its integration tests, including the isolation matrix.
4. Result limits in `db.py`.
5. API endpoints and the cron.
6. Frontend.
7. End-to-end run on the live site.

## Out of scope

Deleting a dataset early, renaming tables or columns after upload, suggested
questions for uploaded data, connection strings, SQLite files, and accounts.
Each can be added later without changing this design.
