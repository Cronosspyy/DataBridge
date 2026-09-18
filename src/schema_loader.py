from sqlalchemy import inspect
from src.db import engine


def get_database_schema():
    inspector = inspect(engine)

    schema = "Database: PostgreSQL\n\n"
    schema += "Tables:\n\n"

    for table_name in inspector.get_table_names():
        schema += f"{table_name}\n"

        columns = inspector.get_columns(table_name)

        for column in columns:
            column_name = column["name"]
            column_type = str(column["type"])

            schema += f"- {column_name} {column_type}"

            if column.get("primary_key"):
                schema += " PRIMARY KEY"

            schema += "\n"

        foreign_keys = inspector.get_foreign_keys(table_name)

        for fk in foreign_keys:
            column = fk["constrained_columns"][0]
            referred_table = fk["referred_table"]
            referred_column = fk["referred_columns"][0]

            schema += (
                f"- FOREIGN KEY: {column} "
                f"REFERENCES {referred_table}({referred_column})\n"
            )

        schema += "\n"

    return schema


if __name__ == "__main__":
    print(get_database_schema())