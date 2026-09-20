# DataBridge

An AI-powered SQL analyst for an e-commerce relational database. Ask a question in plain English, and the system converts it into SQL, safely validates and executes it against PostgreSQL, and returns a human-readable answer — end to end, through a FastAPI backend and a web frontend.

> Who are the top 5 customers by total spending?

```
Natural Language Question
        │
        ▼
   AI understands schema
        │
        ▼
   AI generates SQL (Gemini)
        │
        ▼
   SQL Validation (read-only only)
        │
        ▼
      PostgreSQL
        │
        ▼
    Query Results
        │
        ▼
   AI explains result
        │
        ▼
   FastAPI (POST /ask)
        │
        ▼
        UI
```

## Features

- **Natural language to SQL** — powered by Google Gemini, using the live database schema as context
- **SQL safety validation** — blocks `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`, and other destructive operations; only read-only queries are executed
- **SQL execution** — validated queries run against PostgreSQL via SQLAlchemy and return structured results
- **AI-generated explanations** — raw query results are turned into a plain-English answer
- **FastAPI backend** — a `POST /ask` endpoint that ties the full pipeline together
- **Web frontend** — single-page interface for asking questions and viewing the generated SQL, results, and AI explanation
- **Relational e-commerce dataset** — customers, orders, order items, and products, with preserved foreign-key relationships

## Demo Flow

1. Type a question in plain English (e.g. *"Who are the top 5 customers by total spending?"*)
2. Gemini generates a SQL query from the schema and the question
3. The query is validated — only safe, read-only `SELECT` statements proceed
4. The query runs against PostgreSQL
5. Gemini explains the result in plain English
6. The frontend displays the generated SQL, the result table, and the explanation

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11.6 |
| Environment | Conda (`ai-sql-analyst`) |
| Database | PostgreSQL 16 |
| ORM / DB access | SQLAlchemy, psycopg2-binary |
| AI provider | Google Gemini API |
| Data handling | pandas |
| Config | python-dotenv |
| Backend | FastAPI, Uvicorn |
| Frontend | HTML/CSS (single-page app) |

## Project Structure

```
ai-sql-analyst/
│
├── data/
│   ├── customers.csv
│   ├── orders.csv
│   ├── order_items.csv
│   ├── products.csv
│   ├── product_reviews.csv
│   ├── selected_customers.csv
│   ├── selected_orders.csv
│   ├── selected_order_items.csv
│   └── selected_products.csv
│
├── src/
│   ├── chunk_test.py       # Chunk-based processing for large CSVs
│   ├── db.py                # SQLAlchemy engine, connection, query execution
│   ├── schema.sql            # Table definitions, PKs, FKs
│   ├── select_data.py        # Builds the smaller relational dev dataset
│   └── sql_validator.py      # Read-only SQL safety validation
│
├── frontend/
│   └── index.html            # Landing page + results view
│
├── tests/
│
├── .env                       # DATABASE_URL, GEMINI_API_KEY (not committed)
├── main.py                    # Full question → SQL → validate → execute → explain pipeline
├── app.py                     # FastAPI app exposing POST /ask
├── inspect_data.py            # Dataset inspection utility
├── test_gemini.py             # Gemini integration test script
└── .vscode/
```

> If your FastAPI entrypoint has a different filename than `app.py`, update the run command below to match.

## Database Schema

Four relational tables in the `ai_sql_db` PostgreSQL database:

**customers**
```
customer_id BIGINT PRIMARY KEY
name TEXT
email TEXT
gender TEXT
signup_date DATE
country TEXT
```

**orders**
```
order_id BIGINT PRIMARY KEY
customer_id BIGINT REFERENCES customers(customer_id)
order_date DATE
total_amount NUMERIC(12,2)
payment_method TEXT
shipping_country TEXT
```

**products**
```
product_id BIGINT PRIMARY KEY
product_name TEXT
category TEXT
price NUMERIC(12,2)
```

**order_items**
```
order_id BIGINT REFERENCES orders(order_id)
product_id BIGINT REFERENCES products(product_id)
quantity INTEGER
unit_price NUMERIC(12,2)
```

```
customers ──< orders ──< order_items >── products
```

## Getting Started

### Prerequisites

- Python 3.11+
- Conda
- PostgreSQL 16
- A Google Gemini API key ([Google AI Studio](https://aistudio.google.com))

### Setup

```bash
# Clone the repo
git clone https://github.com/Cronosspyy/ai-sql-analyst.git
cd ai-sql-analyst

# Create and activate the environment
conda create -n ai-sql-analyst python=3.11
conda activate ai-sql-analyst

# Install dependencies
pip install -r requirements.txt
```

### Configure environment variables

Create a `.env` file in the project root:

```env
DATABASE_URL=postgresql+psycopg2://localhost/ai_sql_db
GEMINI_API_KEY=your_api_key_here
```

> Never commit `.env` to GitHub — it's already listed in `.gitignore`.

### Set up the database

```bash
# Create the database
createdb ai_sql_db

# Apply the schema
psql ai_sql_db < src/schema.sql

# Import the sample dataset
psql ai_sql_db -c "\copy customers FROM 'data/selected_customers.csv' CSV HEADER"
psql ai_sql_db -c "\copy orders FROM 'data/selected_orders.csv' CSV HEADER"
psql ai_sql_db -c "\copy products FROM 'data/selected_products.csv' CSV HEADER"
psql ai_sql_db -c "\copy order_items FROM 'data/selected_order_items.csv' CSV HEADER"
```

### Run the backend

```bash
uvicorn app:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

### Run the frontend

Open `frontend/index.html` in a browser (or serve it with any static file server). It calls the backend at `http://127.0.0.1:8000/ask`.

## API Reference

### `POST /ask`

**Request**

```json
{
  "question": "Who are the top 5 customers by total spending?"
}
```

**Response**

```json
{
  "question": "Who are the top 5 customers by total spending?",
  "sql": "SELECT c.name, SUM(o.total_amount) AS total_spending FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.name ORDER BY total_spending DESC LIMIT 5;",
  "results": [
    { "name": "...", "total_spending": 0 }
  ],
  "answer": "The top customer is ... with a total spend of ..."
}
```

## How SQL Safety Works

AI-generated SQL is never executed directly. Every query passes through `src/sql_validator.py` first:

```
AI generates SQL
      │
      ▼
  SQL Validator
      │
 ┌────┴────┐
 │         │
Unsafe    Safe
 │         │
 ▼         ▼
Reject   Execute
```

Only single, read-only `SELECT` statements are allowed. Destructive keywords (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`) are rejected outright.

## What This Project Demonstrates

- Relational database design and data engineering
- Large-file (500MB+) chunked data processing
- SQL and PostgreSQL
- Python, SQLAlchemy, and API integration
- Generative AI / text-to-SQL
- AI safety and input validation
- Backend API development (FastAPI)
- Frontend integration

## Author

**Cronos** ([@Cronosspyy](https://github.com/Cronosspyy)) — MCA student, VIPS-TC Delhi

## License

MIT
