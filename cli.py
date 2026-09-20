from src.ai import generate_sql, explain_results
from src.sql_validator import validate_sql
from src.db import execute_query
from src.schema_loader import get_database_schema
schema = get_database_schema()

question = input("Ask your question: ")

sql = generate_sql(schema, question)

is_valid, message = validate_sql(sql)
if is_valid:
    print("SQL validation successful!")
    print(sql)
    print()

    result = execute_query(sql)
    if result["success"]:
        print(f"Query executed successfully! ({result['row_count']} rows)")
        print()
        for row in result["rows"]:
            print(row)
        explanation = explain_results(question, result["rows"])
        print()
        print("AI Explanation:")
        print(explanation)
    else:
        print("Query execution failed!")
        print(result["error"])

else:
    print("SQL validation failed!")
    print(message)

