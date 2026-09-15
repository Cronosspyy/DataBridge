import os
from dotenv import load_dotenv
from google import genai
from src.sql_validator import validate_sql
from src.db import execute_query

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

schema = """
Database: PostgreSQL

Tables:

customers
- customer_id BIGINT PRIMARY KEY
- name TEXT
- email TEXT
- gender TEXT
- signup_date DATE
- country TEXT

orders
- order_id BIGINT PRIMARY KEY
- customer_id BIGINT REFERENCES customers(customer_id)
- order_date DATE
- total_amount NUMERIC(12,2)
- payment_method TEXT
- shipping_country TEXT

products
- product_id BIGINT PRIMARY KEY
- product_name TEXT
- category TEXT
- price NUMERIC(12,2)

order_items
- order_id BIGINT REFERENCES orders(order_id)
- product_id BIGINT REFERENCES products(product_id)
- quantity INTEGER
- unit_price NUMERIC(12,2)
"""

question = input("Ask your question: ")

prompt = f"""
You are a SQL expert.

Generate a PostgreSQL SQL query to answer the user's question.

Database schema:
{schema}

User question:
{question}

Rules:
- Return ONLY the SQL query.
- Do not use markdown.
- Do not explain anything.
- Use only tables and columns from the schema.
"""

response = client.models.generate_content(
    model="gemini-3.5-flash-lite",
    contents=prompt
)

sql = response.text.strip()

is_valid, message = validate_sql(sql)
def explain_results(question, results):
    prompt = f"""
    You are an AI data analyst.
    User question:
    {question}
SQL query results:
{results}

Explain the results in simple, clear language.

Rules:
- Answer the user's question directly.
- Mention important numbers.
- Do not mention SQL or database implementation details.
- Keep the explanation concise.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt
    )

    return response.text.strip()

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

def explain_results(question, results):
    prompt = f"""
You are an AI data analyst.

User question:
{question}

SQL query results:
{results}

Explain the results in simple, clear language.

Rules:
- Answer the user's question directly.
- Mention important numbers.
- Do not mention SQL or database implementation details.
- Keep the explanation concise.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt
    )

    return response.text.strip()