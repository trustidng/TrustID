from contextlib import contextmanager
from typing import Any, Iterator

import mysql.connector
from mysql.connector import MySQLConnection

from .config import settings


@contextmanager
def connection() -> Iterator[MySQLConnection]:
    conn = mysql.connector.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        autocommit=False,
    )
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_one(conn: MySQLConnection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()


def fetch_all(conn: MySQLConnection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return list(cur.fetchall())
    finally:
        cur.close()


def execute(conn: MySQLConnection, sql: str, params: tuple[Any, ...] = ()) -> int:
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.rowcount
    finally:
        cur.close()

