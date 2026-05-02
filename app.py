import streamlit as st
import pandas as pd
import random
import os
import urllib.parse
import qrcode
from io import BytesIO
import smtplib
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime
from db import *

# ---------------- ENV ----------------
load_dotenv()
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Friendship Ledger", layout="wide")

# ---------------- SESSION ----------------
for k in ["user_id", "username", "group_id", "otp", "otp_sent"]:
    if k not in st.session_state:
        st.session_state[k] = None


# ---------------- OTP ----------------
def get_otp_delivery_mode():
    return os.getenv("OTP_DELIVERY_MODE", "email").strip().lower()


def send_otp(email):
    otp = str(random.randint(100000, 999999))
    st.session_state.otp = otp

    if get_otp_delivery_mode() == "debug":
        st.info(f"Debug OTP: {otp}")
        return True

    sender = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")

    if not sender or not password:
        st.error("Email config missing")
        return False

    msg = f"Subject: OTP\n\nYour OTP is {otp}"

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as s:
            s.starttls()
            s.login(sender, password)
            s.sendmail(sender, email, msg)
        return True
    except Exception as e:
        st.error(f"OTP failed: {str(e)}")
        return False


# ---------------- LOGIN UI ----------------
def login_ui():
    st.title("💰 Friendship Ledger")

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        u = st.text_input("Username / Email")
        p = st.text_input("Password", type="password")

        if st.button("Login"):
            uid = login_user(u, p)
            if uid:
                st.session_state.user_id = uid
                st.session_state.username = u
                st.rerun()
            else:
                st.error("Invalid login")

    with tab2:
        u = st.text_input("Username", key="r1")
        e = st.text_input("Email", key="r2")
        p = st.text_input("Password", type="password", key="r3")

        if st.button("Send OTP"):
            if send_otp(e):
                st.session_state.otp_sent = True

        if st.session_state.otp_sent:
            otp_in = st.text_input("Enter OTP")

        if st.button("Register"):
            if otp_in == st.session_state.otp:
                result = register_user(u, e, p)

                if result is True:
                    st.success("Registered successfully")
                else:
                    st.error(result)
            else:
                st.error("Invalid OTP")
                
if st.session_state.user_id is None:
    login_ui()
    st.stop()


# ---------------- SIDEBAR ----------------
st.sidebar.success(f"👤 {st.session_state.username}")

if st.sidebar.button("Logout"):
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.group_id = None
    st.rerun()


# ---------------- DASHBOARD ----------------
st.title("📊 Dashboard")


# ---------------- CREATE GROUP ----------------
st.subheader("➕ Create Group")
new_group = st.text_input("Group Name")

if st.button("Create Group"):
    if new_group.strip():
        if create_group(st.session_state.user_id, new_group.strip()):
            st.success("Group created successfully")
            st.rerun()
        else:
            st.error("Failed to create group")
    else:
        st.warning("Enter group name")


# ---------------- GROUP SELECT ----------------

groups = get_user_groups(st.session_state.user_id)

if groups.empty:
    st.warning("Create group first")
    st.stop()

group_map = {
    row["id"]: row["name"]
    for _, row in groups.iterrows()
}

gid = st.selectbox(
    "Select Group",
    options=list(group_map.keys()),
    format_func=lambda x: group_map[x]
)

st.session_state.group_id = gid

# ---------------- FRIENDS ----------------
st.subheader("👥 Friends")

fname = st.text_input("Friend Name")
upi = st.text_input("UPI ID")

if st.button("Add Friend"):
    if fname.strip() and upi.strip():
        if add_friend(st.session_state.user_id, gid, fname.strip(), upi.strip()):
            st.success("Friend added")
            st.rerun()
        else:
            st.error("Failed to add friend")
    else:
        st.warning("Enter all details")

friends = get_friends(st.session_state.user_id, gid)

if friends.empty:
    st.info("Add at least one friend")
    st.stop()

# ---------------Delete friend ----------------
st.subheader("❌ Delete Friend")

del_friend = st.selectbox(
    "Select Friend to Delete",
    friends["id"],
    format_func=lambda x: friends[friends["id"] == x]["name"].values[0],
)

if st.button("Delete Friend"):
    res = delete_friend(del_friend)
    if res is True:
        st.success("Deleted successfully")
        st.rerun()
    else:
        st.error(res)

# ---------------- EXPENSE ----------------
st.subheader("💸 Add Expense")

desc = st.text_input("Description")
amt = st.number_input("Amount", min_value=0.0)

payer = st.selectbox(
    "Paid By",
    friends["id"],
    format_func=lambda x: friends[friends["id"] == x]["name"].values[0],
)

split = st.multiselect(
    "Split Among",
    friends["id"],
    default=list(friends["id"]),
)

if st.button("Add Expense"):
    if desc.strip() and amt > 0 and len(split) > 0:
        add_expense(
            st.session_state.user_id,
            gid,
            datetime.now().strftime("%Y-%m-%d"),
            desc.strip(),
            int(payer),
            float(amt),
            split,
        )
        st.success("Expense added")
        st.rerun()
    else:
        st.warning("Fill all fields")


# ---------------- EXPENSE TABLE ----------------
df = get_expenses(st.session_state.user_id, gid)
st.subheader("📋 Expenses")
st.dataframe(df, width="stretch")

# ---------------- who paid whom ----------------
def calculate_balances(user_id, group_id):
    df = get_expenses(user_id, group_id)

    balances = {}

    for _, row in df.iterrows():
        amount = float(row["amount"])
        paid_by = row["paid_by"]
        split_ids = list(map(int, row["splits"].split(",")))

        share = amount / len(split_ids)

        for person in split_ids:
            balances[person] = balances.get(person, 0) - share

        balances[paid_by] = balances.get(paid_by, 0) + amount

    return balances

def settle_debts(balances):
    creditors = []
    debtors = []

    for person, amt in balances.items():
        if amt > 0:
            creditors.append([person, amt])
        elif amt < 0:
            debtors.append([person, -amt])

    transactions = []

    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        d_person, d_amt = debtors[i]
        c_person, c_amt = creditors[j]

        pay = min(d_amt, c_amt)

        transactions.append((d_person, c_person, pay))

        debtors[i][1] -= pay
        creditors[j][1] -= pay

        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return transactions

st.subheader("💰 Settlements")

balances = calculate_balances(st.session_state.user_id, gid)
txns = settle_debts(balances)

for d, c, amt in txns:
    d_name = friends[friends["id"] == d]["name"].values[0]
    c_name = friends[friends["id"] == c]["name"].values[0]

    st.write(f"👉 {d_name} pays ₹{amt:.2f} to {c_name}")

df = get_expenses(st.session_state.user_id, gid)



if not df.empty:
    df["amount"] = df["amount"].astype(float)
    df["expense_date"] = pd.to_datetime(df["expense_date"])

    # ✅ Create month column
    df["month"] = df["expense_date"].dt.to_period("M").astype(str)

    st.subheader("📊 Monthly Analysis")

    # ✅ Dropdown for month
    selected_month = st.selectbox(
        "Select Month",
        sorted(df["month"].unique(), reverse=True)
    )

    # ✅ Filter data
    month_df = df[df["month"] == selected_month]

    st.write(f"Showing data for: {selected_month}")
    
    # ✅ DEFINE daily HERE
    daily = month_df.groupby("expense_date")["amount"].sum()

    col1, col2 = st.columns(2)

    with col1:
        st.line_chart(daily)

    with col2:
        st.bar_chart(daily)

    # ✅ Charts (smaller + meaningful)
   # Group by date
    daily = month_df.groupby("expense_date")["amount"].sum()

    st.line_chart(daily)
    st.bar_chart(daily)

    # ✅ Pie chart (FIXED SIZE + names)
    import matplotlib.pyplot as plt

    spend = month_df.groupby("paid_by")["amount"].sum()

    name_map = dict(zip(friends["id"], friends["name"]))
    labels = [name_map[i] for i in spend.index]

    fig, ax = plt.subplots(figsize=(4, 4))  # 👈 smaller size

    ax.pie(
        spend,
        labels=labels,
        autopct="%1.1f%%"
    )

    st.pyplot(fig)

def generate_upi_link(upi_id, name, amount):
    return f"upi://pay?pa={upi_id}&pn={name}&am={amount}&cu=INR"

def generate_qr(data):
    qr = qrcode.make(data)
    buf = BytesIO()
    qr.save(buf)
    return buf

st.subheader("📱 Pay via UPI")

for d, c, amt in txns:
    receiver = friends[friends["id"] == c].iloc[0]

    upi_link = generate_upi_link(receiver["upi_id"], receiver["name"], amt)

    st.write(f"Pay {receiver['name']} ₹{amt}")

    st.markdown(f"[Pay Now]({upi_link})")

    qr = generate_qr(upi_link)
    st.image(qr)

def add_payment(group_id, payer, receiver, amount):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO payments (group_id, payer, receiver, amount)
            VALUES (%s, %s, %s, %s)
        """, (group_id, payer, receiver, amount))
        conn.commit()
    finally:
        safe_close_cursor(cur)
        return_connection(conn)

def mark_paid(payment_id):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE payments SET status='PAID'
            WHERE id=%s
        """, (payment_id,))
        conn.commit()
    finally:
        safe_close_cursor(cur)
        return_connection(conn)

