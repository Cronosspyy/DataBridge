# DataBridge

Ask a database questions in plain English. DataBridge sends your question and the
live database schema to Gemini, gets a PostgreSQL query back, checks that the
query only reads, runs it, and then has Gemini explain the rows in plain language.

The web UI shows all three things: the answer, the table and chart, and the SQL
that produced them — so you can check the machine's work.

```
question ──▶ Gemini ──▶ SQL ──▶ validator ──▶ PostgreSQL ──▶ rows ──▶ Gemini ──▶ explanation
```

## Sample questions

- Top 5 customers by spending
- Revenue by category
- Orders by month
- Most used payment method

## Project layout

| Path | What it does |
| --- | --- |
| `app.py` | FastAPI app: `GET /health`, `POST /ask`. The deployment entrypoint. |
| `cli.py` | The same pipeline as a terminal prompt, for quick manual testing. |
| `src/ai.py` | The two Gemini calls: generate SQL, explain results. |
| `src/sql_validator.py` | Rejects anything that is not a single read-only statement. |
| `src/db.py` | SQLAlchemy engine and query execution. |
| `src/schema_loader.py` | Reflects the live database into the text handed to the model. |
| `src/schema.sql` | The four tables: customers, products, orders, order_items. |
| `src/grants.sql` | Read-only Postgres role used in production. |
| `scripts/load_data.py` | Creates the tables and loads `data/*.csv`. |
| `scripts/create_readonly_role.py` | Applies `grants.sql` and emits the read-only connection string. |
| `public/` | The two static pages, served as the site root. |
| `tests/` | Validator unit tests and live API tests. |

## Running it locally

You need Python 3.12+, a PostgreSQL database, and a
[Gemini API key](https://aistudio.google.com/apikey).

```bash
git clone https://github.com/Cronosspyy/DataBridge.git
cd DataBridge
```

Create the environment and install dependencies. With
[uv](https://docs.astral.sh/uv/):

```bash
uv venv && uv pip install -r requirements-dev.txt
```

Or with plain pip:

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
```

Set your secrets:

```bash
cp .env.example .env
```

Fill in `DATABASE_URL` and `GEMINI_API_KEY`, then create the tables and load the
sample data:

```bash
python scripts/load_data.py
```

Start the API:

```bash
uvicorn app:app --reload
```

`http://127.0.0.1:8000` now serves the API, and the interactive docs are at
`/docs`. Open `public/index.html` with any static server — VS Code's Live Server
works — and the pages will talk to the local API automatically.

## Deploying to Vercel

The whole thing runs as one Vercel project: `public/` is served as static files
and everything else is routed to `app.py`.

**1. Create a database.** Vercel functions cannot reach your laptop, so you need
a hosted Postgres. Easiest route is the Vercel **Storage** tab -> Marketplace ->
[Neon](https://neon.tech), which attaches a database to the project and injects
`DATABASE_URL` and friends automatically. Creating it at neon.tech and copying
the connection string by hand works too.

**2. Load the data** from your machine. Put the **unpooled** owner connection
string in `.env` as `DATABASE_URL` - bulk `COPY` is happier on a direct
connection - then:

```bash
python scripts/load_data.py
```

**3. Create the read-only role:**

```bash
python scripts/create_readonly_role.py
```

This applies `src/grants.sql` with a generated password and writes the resulting
read-only connection string to `.env` as `DATABASE_URL_READONLY`, pointed at
Neon's pooled endpoint. Use `--show` to print it when you need to paste it into
Vercel. This is what actually stops a generated `DROP` - see
[Security](#security).

**4. Import the repository** at [vercel.com/new](https://vercel.com/new). Vercel
detects FastAPI from `requirements.txt`; leave the build settings alone.

**5. Set environment variables** before the first deploy, under
Settings -> Environments:

| Name | Value |
| --- | --- |
| `DATABASE_URL_READONLY` | Output of `create_readonly_role.py --show` |
| `GEMINI_API_KEY` | Your Gemini key |

`src/db.py` prefers `DATABASE_URL_READONLY` and falls back to `DATABASE_URL`.
The two names exist because the Neon integration manages `DATABASE_URL` itself,
points it at the owner role, and does not let you edit it in the dashboard, so
the read-only string is supplied under its own name rather than fighting it.

**6. Deploy.** Check `/health` returns `{"status":"ok"}`, then ask a question on
the home page.

## Security

The model writes the SQL, so the SQL cannot be trusted. Two layers handle that,
and they are deliberately different in kind:

`src/sql_validator.py` rejects anything that does not start with `SELECT` or
`WITH`, anything containing a second statement, and anything containing a
comment or a write keyword. It is a text filter, and text filters on SQL are
approximate — it is a fast first pass, not a guarantee.

`src/grants.sql` is the guarantee. The production connection string belongs to a
role with `SELECT` and nothing else, whose transactions are read-only by
default. A write that slipped past the validator still fails at the database.

**Use the read-only role in production.** The validator alone is not enough.

Two things to be aware of before sharing a public URL: query results are sent to
Gemini to be explained, so whatever is in your database reaches Google; and the
endpoint is unauthenticated, so anyone with the link can spend your Gemini quota.

## Tests

```bash
pytest tests/test_validator.py
```

`tests/test_api.py` runs against a live server and makes real Gemini calls — it
needs `uvicorn app:app` running in another terminal, and it costs API quota:

```bash
pytest tests/test_api.py
```

## Dataset

`data/*.csv` is a synthetic sample: 4,997 customers, 9,226 products, 5,000
orders and 12,447 order items. No real people are in it. `src/select_data.py`
is the script that sampled it from a larger source dataset.
