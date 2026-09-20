import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()

# Prefer the read-only role whenever one is configured, and fall back to
# DATABASE_URL for local work against a database you own.
#
# Two names are needed because Vercel's Neon integration manages DATABASE_URL
# itself and points it at the owner role; that variable cannot be edited in the
# dashboard. DATABASE_URL_READONLY is set alongside it so the deployed app
# connects as databridge_readonly (see src/grants.sql).
DATABASE_URL = os.getenv("DATABASE_URL_READONLY") or os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "Neither DATABASE_URL_READONLY nor DATABASE_URL is set. "
        "Copy .env.example to .env and fill it in."
    )

engine = create_engine(DATABASE_URL)


def test_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))
            print("Database connection successful!")
            print("Result:", result.scalar())

    except Exception as e:
        print("Database connection failed!")
        print(e)


def execute_query(sql: str, params: dict = None) -> dict:
    """
    Executes a validated, read-only SQL query against PostgreSQL.

    Returns a dict:
        {
            "success": bool,
            "columns": list[str],
            "rows": list[dict],
            "row_count": int,
            "error": str | None
        }
    """
    try:
        with engine.connect() as connection:
        # Limit each query to 5 seconds
            connection.execute(text("SET LOCAL statement_timeout = '5000'"))

            result = connection.execute(text(sql), params or {})
            columns = list(result.keys())
            rows = [dict(row._mapping) for row in result]

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "error": None,
            }

    except SQLAlchemyError as e:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": str(e.__cause__ or e),
        }

    except Exception as e:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": str(e),
        }


if __name__ == "__main__":
    test_connection()