import os
import pandas as pd
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
import hashlib
import base64
import hmac
import secrets
import streamlit as st

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

@st.cache_resource
def init_db_pool():
    try:
        pool = psycopg2.pool.SimpleConnectionPool(
            1,
            20,
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=int(DB_PORT),
        )
        print("✅ DB Connected")
        return pool
    except Exception as e:
        print("❌ DB Connection Error:", e)
        return None
    
db_pool = init_db_pool()

def get_connection():
    if db_pool is None:
        raise Exception("Database not connected")
    return db_pool.getconn()


def return_connection(conn):
    if conn is not None:
        try:
            db_pool.putconn(conn)
        except Exception:
            pass


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
            VALUES (%s, %s, %s)
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
            WHERE username=%s OR email=%s
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
            VALUES (%s, %s)
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
            WHERE user_id = %s
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
            VALUES (%s, %s, %s, %s)
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
            WHERE user_id=%s AND group_id=%s
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
            VALUES (%s, %s, %s, %s, %s, %s, %s)
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
            WHERE paid_by = %s OR splits LIKE %s
        """, (friend_id, f"%{friend_id}%"))

        count = cur.fetchone()[0]

        if count > 0:
            return "Friend involved in expenses, cannot delete"

        cur.execute("DELETE FROM friends WHERE id = %s", (friend_id,))
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
            WHERE user_id=%s AND group_id=%s
            ORDER BY id DESC
            """,
            conn,
            params=(user_id, group_id),
        )
    finally:
        return_connection(conn)
