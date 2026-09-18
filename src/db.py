import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

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