import os
import pandas as pd
from dotenv import load_dotenv
import hashlib
import base64
import hmac
import secrets


def init_sqlite():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        email TEXT,
        password TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        group_id INTEGER,
        name TEXT,
        upi_id TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        group_id INTEGER,
        expense_date TEXT,
        description TEXT,
        paid_by INTEGER,
        amount REAL,
        splits TEXT
    )
    """)

    conn.commit()
    conn.close()
init_sqlite()
from pathlib import Path

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT", "5432")

print("DB_HOST:", DB_HOST)
print("DB_NAME:", DB_NAME)
print("DB_USER:", DB_USER)
print("DB_PORT:", DB_PORT)

import sqlite3

def get_connection():
    return sqlite3.connect("friendship_ledger.db")

def return_connection(conn):
    if conn:
        conn.close()


def safe_rollback(conn):
    if conn is not None:
        try:
            conn.rollback()
        except Exception:
            pass


def safe_close_cursor(cur):
    if cur is not None:
        try:
            cur.close()
        except Exception:
            pass


# ---------------- PASSWORD ----------------
def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return (
        "pbkdf2$"
        + base64.b64encode(salt).decode()
        + "$"
        + base64.b64encode(digest).decode()
    )


def verify_password(password, stored):
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ---------------- USERS ----------------
def register_user(username, email, password):
    conn = get_connection()
    cur = conn.cursor()

    try:
        # basic validation
        if not username.strip():
            return "Username cannot be empty"

        if not email.strip():
            return "Email cannot be empty"

        if not password.strip():
            return "Password cannot be empty"

        cur.execute(
            """
            INSERT INTO users (username, email, password)
            VALUES (?, ?, ?)
            """,
            (username, email, hash_password(password)),
        )

        conn.commit()
        return True

    except Exception as e:
        safe_rollback(conn)
        return f"Database Error: {str(e)}"

    finally:
        safe_close_cursor(cur)
        return_connection(conn)


def login_user(username_or_email, password):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT id, password
            FROM users
            WHERE username=? OR email=?
            """,
            (username_or_email, username_or_email),
        )
        row = cur.fetchone()

        if not row:
            return None

        stored_password = row[1]

        # ✅ Handle hashed password
        if stored_password.startswith("pbkdf2$"):
            if verify_password(password, stored_password):
                return row[0]

        # ✅ Handle old plain text password (temporary fix)
        else:
            if password == stored_password:
                return row[0]

        return None

    except Exception as e:
        print("login_user error:", str(e))
        return None
    finally:
        safe_close_cursor(cur)
        return_connection(conn)


# ---------------- GROUPS ----------------
def create_group(user_id, group_name):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO groups (user_id, name)
            VALUES (?, ?)
            """,
            (user_id, group_name),
        )
        conn.commit()
        return True
    except Exception as e:
        print("create_group error:", str(e))
        safe_rollback(conn)
        return False
    finally:
        safe_close_cursor(cur)
        return_connection(conn)


def get_user_groups(user_id):
    conn = get_connection()
    try:
        return pd.read_sql(
            """
            SELECT id, name
            FROM groups
            WHERE user_id = ?
            ORDER BY id
            """,
            conn,
            params=(user_id,),
        )
    finally:
        return_connection(conn)


# ---------------- FRIENDS ----------------
def add_friend(user_id, group_id, name, upi_id):
    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            INSERT INTO friends (user_id, group_id, name, upi_id)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, group_id, name, upi_id),
        )
        conn.commit()
        return True
    except Exception as e:
        print("add_friend error:", str(e))
        safe_rollback(conn)
        return False
    finally:
        safe_close_cursor(cur)
        return_connection(conn)


def get_friends(user_id, group_id):
    conn = get_connection()
    try:
        return pd.read_sql(
            """
            SELECT id, name, upi_id
            FROM friends
            WHERE user_id=? AND group_id=?
            ORDER BY id
            """,
            conn,
            params=(user_id, group_id),
        )
    finally:
        return_connection(conn)


# ---------------- EXPENSES ----------------
def add_expense(user_id, group_id, expense_date, description, paid_by, amount, split_ids):
    conn = get_connection()
    cur = conn.cursor()

    try:
        split_string = ",".join(map(str, split_ids))

        cur.execute(
            """
            INSERT INTO expenses
            (user_id, group_id, expense_date, description, paid_by, amount, splits)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, group_id, expense_date, description, paid_by, amount, split_string),
        )

        conn.commit()
        return True
    except Exception as e:
        print("add_expense error:", str(e))
        safe_rollback(conn)
        return False
    finally:
        safe_close_cursor(cur)
        return_connection(conn)

def delete_friend(friend_id):
    conn = get_connection()
    cur = conn.cursor()

    try:
        # check if used in expenses
        cur.execute("""
            SELECT COUNT(*) FROM expenses
            WHERE paid_by = ? OR splits LIKE ?      
        """, (friend_id, f"%{friend_id}%"))

        count = cur.fetchone()[0]

        if count > 0:
            return "Friend involved in expenses, cannot delete"

        cur.execute("DELETE FROM friends WHERE id = ?", (friend_id,))
        conn.commit()
        return True

    except Exception as e:
        safe_rollback(conn)
        return str(e)
    finally:
        safe_close_cursor(cur)
        return_connection(conn)


def get_expenses(user_id, group_id):
    conn = get_connection()
    try:
        return pd.read_sql(
            """
            SELECT id, description, amount, paid_by, splits,expense_date
            FROM expenses
            WHERE user_id=? AND group_id=?
            ORDER BY id DESC
            """,
            conn,
            params=(user_id, group_id),
        )
    finally:
        return_connection(conn)
