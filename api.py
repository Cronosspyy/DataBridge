from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.ai import generate_sql, explain_results
from src.sql_validator import validate_sql
from src.db import execute_query
from src.schema_loader import get_database_schema

app = FastAPI(title="AI SQL Analyst")


class QuestionRequest(BaseModel):
    question: str

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.post("/ask")
def ask_question(request: QuestionRequest):
    schema = get_database_schema()

    sql = generate_sql(schema, request.question)

    is_valid, message = validate_sql(sql)

    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=message
        )

    result = execute_query(sql)

    if not result["success"]:
        return {
            "success": False,
            "sql": sql,
            "error": result["error"]
        }

    explanation = explain_results(
        request.question,
        result["rows"]
    )

    return {
        "success": True,
        "question": request.question,
        "sql": sql,
        "rows": result["rows"],
        "row_count": result["row_count"],
        "explanation": explanation
    }