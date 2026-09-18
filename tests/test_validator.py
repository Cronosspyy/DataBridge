from src.sql_validator import validate_sql


# Valid query
def test_valid_select():
    valid, message = validate_sql(
        "SELECT * FROM customers;"
    )

    assert valid is True


# Block INSERT
def test_block_insert():
    valid, message = validate_sql(
        "INSERT INTO customers VALUES (1, 'Test');"
    )

    assert valid is False


# Block DELETE
def test_block_delete():
    valid, message = validate_sql(
        "DELETE FROM customers;"
    )

    assert valid is False


# Block DROP
def test_block_drop():
    valid, message = validate_sql(
        "DROP TABLE customers;"
    )

    assert valid is False


# Block multiple statements
def test_block_multiple_statements():
    valid, message = validate_sql(
        "SELECT * FROM customers; DROP TABLE customers;"
    )

    assert valid is False

# Block dangerous keyword with different capitalization
def test_block_mixed_case_drop():
    valid, message = validate_sql(
        "SELECT * FROM customers; DrOp TABLE customers;"
    )

    assert valid is False


# Block multiple statements with comments
def test_block_multiple_statements_with_comment():
    valid, message = validate_sql(
        "SELECT * FROM customers; -- DROP TABLE customers"
    )

    assert valid is False


# Block block-comment based multiple statements
def test_block_block_comment():
    valid, message = validate_sql(
        "SELECT * FROM customers; /* DROP TABLE customers */"
    )

    assert valid is False