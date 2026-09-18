def validate_sql(sql):
    sql = sql.strip().lower()
        # Block SQL comments
    if "--" in sql or "/*" in sql or "*/" in sql:
        return False, "SQL comments are not allowed."

    # Remove single-line comments
    lines = sql.splitlines()
    cleaned_lines = []

    for line in lines:
        if "--" in line:
            line = line.split("--")[0]

        cleaned_lines.append(line)

    sql = "\n".join(cleaned_lines)

    # Remove block comments
    while "/*" in sql and "*/" in sql:
        start = sql.find("/*")
        end = sql.find("*/", start)

        sql = sql[:start] + sql[end + 2:]

    sql = sql.strip()

    # Only SELECT queries are allowed
    if not sql.startswith("select"):
        return False, "Only SELECT queries are allowed."

    # Block multiple SQL statements
    if ";" in sql.rstrip(";"):
        return False, "Multiple SQL statements are not allowed."

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