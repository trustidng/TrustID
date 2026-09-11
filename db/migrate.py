"""Small, transactional migration runner for TrustID's numbered SQL migrations."""
from pathlib import Path
import re
import sys

from dotenv import load_dotenv
import mysql.connector

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402

MIGRATION_DIR = Path(__file__).with_name("migrations")


def statements(sql: str) -> list[str]:
    cleaned = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
    return [part.strip() for part in re.split(r";\s*(?:\n|$)", cleaned) if part.strip()]


def main() -> None:
    settings.validate()
    conn = mysql.connector.connect(
        host=settings.db_host, port=settings.db_port, user=settings.db_user,
        password=settings.db_password, database=settings.db_name, autocommit=False,
    )
    try:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(100) PRIMARY KEY,
            applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB""")
        conn.commit()
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}
        for path in sorted(MIGRATION_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            print(f"Applying {path.name}...")
            for statement in statements(path.read_text(encoding="utf-8")):
                cur.execute(statement)
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            conn.commit()
        print("Database migrations are current.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
