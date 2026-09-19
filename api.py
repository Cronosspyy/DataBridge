from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.ai import generate_sql, explain_results
from src.sql_validator import validate_sql
from src.db import execute_query
from src.schema_loader import get_database_schema

app = FastAPI(title="DataBridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5501",
        "http://127.0.0.1:5501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)


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
        raise HTTPException(
            status_code=500,
            detail=result["error"]
        )

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