"""
Create the DataBridge tables and load the sample CSVs into Postgres.

    python scripts/load_data.py            # create tables and load
    python scripts/load_data.py --reset    # drop existing tables first

Reads DATABASE_URL from .env. Point it at the database owner, not the
read-only role from src/grants.sql -- that role cannot create tables.
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = ROOT / "src" / "schema.sql"

# Load order matters: each table is loaded after the tables it references.
TABLES = [
    ("customers", "selected_customers.csv"),
    ("products", "selected_products.csv"),
    ("orders", "selected_orders.csv"),
    ("order_items", "selected_order_items.csv"),
]


def load_table(raw_connection, table, csv_path):
    """COPY one CSV into one table, matching columns by header name."""
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        header = handle.readline().strip()
        handle.seek(0)

        cursor = raw_connection.cursor()
        cursor.copy_expert(
            f"COPY {table} ({header}) FROM STDIN WITH (FORMAT csv, HEADER true)",
            handle,
        )
        cursor.close()

    return header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop the four tables before creating them (destroys existing data)",
    )
    args = parser.parse_args()

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        sys.exit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

    engine = create_engine(database_url)

    existing = set(inspect(engine).get_table_names())
    wanted = {table for table, _ in TABLES}
    clashes = existing & wanted

    if clashes and not args.reset:
        sys.exit(
            f"These tables already exist: {', '.join(sorted(clashes))}.\n"
            "Re-run with --reset to drop and rebuild them."
        )

    with engine.begin() as connection:
        if args.reset and clashes:
            # Reverse order so a table is dropped before the ones it points at.
            for table, _ in reversed(TABLES):
                connection.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
            print(f"Dropped: {', '.join(sorted(clashes))}")

        connection.execute(text(SCHEMA_SQL.read_text()))
        print(f"Created {len(TABLES)} tables from {SCHEMA_SQL.relative_to(ROOT)}")

    # COPY needs the psycopg2 connection directly; SQLAlchemy has no wrapper.
    raw_connection = engine.raw_connection()

    try:
        for table, filename in TABLES:
            csv_path = ROOT / "data" / filename

            if not csv_path.exists():
                raise SystemExit(f"Missing data file: {csv_path.relative_to(ROOT)}")

            load_table(raw_connection, table, csv_path)

            count = raw_connection.cursor()
            count.execute(f"SELECT count(*) FROM {table}")
            print(f"Loaded {count.fetchone()[0]:>6} rows into {table}")
            count.close()

        raw_connection.commit()

    except Exception:
        raw_connection.rollback()
        raise

    finally:
        raw_connection.close()

    print("\nDone. Check it with: python -m src.schema_loader")


if __name__ == "__main__":
    main()
