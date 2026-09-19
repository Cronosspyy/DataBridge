import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def generate_sql(schema, question):
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
- When the question asks for a metric such as revenue, spending, sales, quantity, or count, include the calculated metric in the SELECT output.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt
    )

    return response.text.strip()


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