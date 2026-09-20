"""
Create (or rotate) the databridge_readonly role and print its connection string.

    python scripts/create_readonly_role.py

Connects as the owner using DATABASE_URL from .env, applies src/grants.sql with
a freshly generated password, and writes the resulting read-only connection
string back to .env as DATABASE_URL_READONLY.

The password is generated here and never printed. Use --show to print the
connection string when you need to paste it somewhere, such as the Vercel
environment variable.
"""

import argparse
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
GRANTS_SQL = ROOT / "src" / "grants.sql"
ENV_FILE = ROOT / ".env"
ROLE = "databridge_readonly"


def pooled(netloc):
    """Neon's pooled endpoint is the direct host with -pooler on the endpoint id."""
    host = netloc.rsplit("@", 1)[-1]

    if "-pooler." in host or ".neon.tech" not in host:
        return host

    endpoint, _, rest = host.partition(".")
    return f"{endpoint}-pooler.{rest}"


def build_readonly_url(owner_url, password):
    parts = urlsplit(owner_url)
    netloc = f"{ROLE}:{password}@{pooled(parts.netloc)}"

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def write_env(url):
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    entry = f"DATABASE_URL_READONLY={url}"

    for index, line in enumerate(lines):
        if line.startswith("DATABASE_URL_READONLY="):
            lines[index] = entry
            break
    else:
        lines += ["", "# Read-only role used by the app. Created by", "# scripts/create_readonly_role.py -- do not commit.", entry]

    ENV_FILE.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print the connection string, password included")
    args = parser.parse_args()

    load_dotenv()
    owner_url = os.getenv("DATABASE_URL")

    if not owner_url:
        sys.exit("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")

    password = secrets.token_urlsafe(24)

    # The checked-in file carries a placeholder password; swap in the real one.
    ddl = re.sub(
        r"PASSWORD '[^']*'",
        f"PASSWORD '{password}'",
        GRANTS_SQL.read_text(),
        count=1,
    )

    engine = create_engine(owner_url)

    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": ROLE}
        ).scalar()

    if exists:
        # Re-running should rotate the password, not fail on CREATE ROLE.
        ddl = re.sub(
            r"CREATE ROLE \w+ LOGIN PASSWORD '[^']*';",
            f"ALTER ROLE {ROLE} WITH LOGIN PASSWORD '{password}';",
            ddl,
            count=1,
        )
        print(f"Role {ROLE} already existed; rotating its password.")

    # The DDL is a multi-statement script, which psycopg2 runs in one execute.
    # SQLAlchemy's text()/exec_driver_sql would try to parse it for parameters.
    raw_connection = engine.raw_connection()

    try:
        cursor = raw_connection.cursor()
        cursor.execute(ddl)
        cursor.close()
        raw_connection.commit()

    except Exception:
        raw_connection.rollback()
        raise

    finally:
        raw_connection.close()

    readonly_url = build_readonly_url(owner_url, password)
    write_env(readonly_url)

    host = urlsplit(readonly_url).netloc.rsplit("@", 1)[-1]
    print(f"Role    : {ROLE}")
    print(f"Host    : {host}")
    print("Password: generated, written to .env as DATABASE_URL_READONLY")

    if args.show:
        print(f"\n{readonly_url}")


if __name__ == "__main__":
    main()
