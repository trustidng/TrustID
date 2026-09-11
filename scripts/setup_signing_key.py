"""Generate and activate a local Ed25519 key without storing private material in MySQL."""
import base64
from pathlib import Path
import re
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.auth import audit
from app.db import connection, execute


def set_env_value(path: Path, name: str, value: str) -> None:
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"{name}={value}"
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    content = pattern.sub(line, content) if pattern.search(content) else content.rstrip() + "\n" + line + "\n"
    path.write_text(content, encoding="utf-8")


def main() -> None:
    key = Ed25519PrivateKey.generate()
    private_raw = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public_raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = "dev-" + uuid4().hex[:12]
    with connection() as conn:
        execute(conn, "UPDATE signing_keys SET status='RETIRED',retired_at=UTC_TIMESTAMP() WHERE status='ACTIVE'")
        execute(conn, """INSERT INTO signing_keys
            (key_id,algorithm,public_key_b64,status,activated_at)
            VALUES (%s,'Ed25519',%s,'ACTIVE',UTC_TIMESTAMP())""",
            (key_id, base64.b64encode(public_raw).decode("ascii")))
        audit(conn, "SIGNING_KEY_CREATED", "SYSTEM", None, key_id, {"algorithm": "Ed25519"})
        audit(conn, "SIGNING_KEY_ACTIVATED", "SYSTEM", None, key_id, None)
        conn.commit()
    env_path = Path(__file__).resolve().parents[1] / ".env"
    set_env_value(env_path, "TRUSTID_SIGNING_KEY_ID", key_id)
    set_env_value(env_path, "TRUSTID_SIGNING_PRIVATE_KEY_B64", base64.b64encode(private_raw).decode("ascii"))
    if "PUBLIC_BASE_URL=" not in env_path.read_text(encoding="utf-8"):
        set_env_value(env_path, "PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    print(f"Activated local signing key {key_id}. Restart the application to load it.")


if __name__ == "__main__":
    main()
