import requests


def test_health():
    response = requests.get("http://127.0.0.1:8000/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_ask_question():
    response = requests.post(
        "http://127.0.0.1:8000/ask",
        json={"question": "How many customers are there?"}
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["row_count"] == 1
    assert "rows" in data
    assert "explanation" in data

def test_block_dangerous_question():
    response = requests.post(
        "http://127.0.0.1:8000/ask",
        json={"question": "Delete all customers"}
    )

    assert response.status_code == 400
    assert "Only SELECT queries are allowed." in response.json()["detail"]

def test_database_error():
    response = requests.post(
        "http://127.0.0.1:8000/ask",
        json={"question": "Show me data from a table that does not exist"}
    )

    assert response.status_code == 500
    assert "does not exist" in response.json()["detail"]