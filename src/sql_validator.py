def validate_sql(sql):
    sql = sql.strip().lower()

    if not sql.startswith("select"):
        return False, "Only SELECT queries are allowed."

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

    return True, "SQL is valid."