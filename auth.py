"""Streamlit local user accounts. Store the credential DB on persistent storage in production."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from db_backend import connect as db_connect, is_neon
from datetime import datetime, timezone

import streamlit as st

AUTH_DB = os.environ.get("AUTH_DB_PATH", os.path.join(os.path.dirname(__file__), "users.db"))
ROLES = ("管理员", "运营人员", "只读用户")


def _connect():
    conn = db_connect(AUTH_DB, timeout=15)
    if not is_neon():
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY COLLATE NOCASE,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.commit()
    return conn


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                              bytes.fromhex(salt), 600000).hex()


def _new_password(password):
    salt = secrets.token_hex(16)
    return salt, _hash(password, salt)


def bootstrap():
    """Create the first admin from Streamlit Secrets, never from public source code."""
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count:
            return True
        initial = str(st.secrets.get("ADMIN_PASSWORD", ""))
        if not initial or len(initial) < 12:
            return False
        salt, digest = _new_password(initial)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                     ("admin", salt, digest, "管理员", 1, now, now))
    return True


def authenticate(username, password):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=? AND enabled=1",
                           (username.strip(),)).fetchone()
    if row is None:
        # Keep a comparable password derivation even for unknown usernames.
        _hash(password, "00" * 16)
        return None
    actual = _hash(password, row["salt"])
    if hmac.compare_digest(actual, row["password_hash"]):
        return {"username": row["username"], "role": row["role"]}
    return None


def current_user():
    username = st.session_state.get("auth_username")
    if not username:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT username, role, enabled FROM users WHERE username=?",
                           (username,)).fetchone()
    if row is None or not row["enabled"]:
        st.session_state.pop("auth_username", None)
        return None
    return {"username": row["username"], "role": row["role"]}


def login_gate():
    if not bootstrap():
        st.error("尚未初始化管理员。请在 Streamlit Cloud → App settings → Secrets 配置长度至少 12 位的 ADMIN_PASSWORD。")
        st.stop()
    user = current_user()
    if user:
        return user
    st.markdown("## 🔐 用户登录")
    st.caption("司顺国际物流港后运营工作台 · 请登录后访问业务数据")
    with st.form("user_login", clear_on_submit=True):
        username = st.text_input("用户名")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录工作台", type="primary")
    if submitted:
        verified = authenticate(username, password)
        if verified:
            st.session_state["auth_username"] = verified["username"]
            st.rerun()
        st.error("用户名或密码错误，或账号已停用。")
    st.stop()


def manage_users(user):
    if user["role"] != "管理员":
        st.error("仅管理员可访问用户管理。")
        return
    st.subheader("👥 用户管理")
    st.caption("账号信息存储于当前数据库后端（Neon 或 SQLite）。")
    with _connect() as conn:
        rows = conn.execute("SELECT username, role, enabled, created_at FROM users ORDER BY username").fetchall()
    st.dataframe([{"用户名": r["username"], "角色": r["role"],
                   "状态": "启用" if r["enabled"] else "停用",
                   "创建时间": r["created_at"][:19]} for r in rows],
                 hide_index=True, use_container_width=True)
    with st.expander("➕ 新建用户"):
        with st.form("create_user", clear_on_submit=True):
            username = st.text_input("新用户名")
            password = st.text_input("初始密码（至少12位）", type="password")
            role = st.selectbox("角色", ROLES)
            submit = st.form_submit_button("创建账号")
        if submit:
            username = username.strip()
            if not username or len(username) > 64 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in username):
                st.error("用户名仅允许英文字母、数字、下划线、点和短横线，最长64位。")
            elif len(password) < 12:
                st.error("密码至少12位。")
            else:
                salt, digest = _new_password(password)
                now = datetime.now(timezone.utc).isoformat()
                try:
                    with _connect() as conn:
                        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                                     (username, salt, digest, role, 1, now, now))
                    st.success("用户已创建。")
                    st.rerun()
                except (sqlite3.IntegrityError, __import__("psycopg").errors.UniqueViolation):
                    st.error("用户名已存在。")
    with st.expander("🛠️ 修改账号 / 重置密码"):
        selected = st.selectbox("选择账号", [r["username"] for r in rows])
        existing = next(r for r in rows if r["username"] == selected)
        with st.form("edit_user"):
            new_role = st.selectbox("角色", ROLES, index=ROLES.index(existing["role"]))
            enabled = st.checkbox("启用账号", value=bool(existing["enabled"]))
            new_password = st.text_input("重置密码（留空则不修改）", type="password")
            save = st.form_submit_button("保存修改")
        if save:
            if new_password and len(new_password) < 12:
                st.error("新密码至少12位。")
            elif selected.lower() == user["username"].lower() and (not enabled or new_role != "管理员"):
                st.error("不能停用自己或取消自己的管理员权限。")
            else:
                with _connect() as conn:
                    if new_password:
                        salt, digest = _new_password(new_password)
                        conn.execute("UPDATE users SET role=?, enabled=?, salt=?, password_hash=?, updated_at=? WHERE username=?",
                                     (new_role, int(enabled), salt, digest, datetime.now(timezone.utc).isoformat(), selected))
                    else:
                        conn.execute("UPDATE users SET role=?, enabled=?, updated_at=? WHERE username=?",
                                     (new_role, int(enabled), datetime.now(timezone.utc).isoformat(), selected))
                st.success("账号已更新。")
                st.rerun()


def change_own_password(user):
    st.subheader("修改我的密码")
    with st.form("change_own_password", clear_on_submit=True):
        old = st.text_input("当前密码", type="password")
        new = st.text_input("新密码（至少12位）", type="password")
        confirm = st.text_input("确认新密码", type="password")
        submit = st.form_submit_button("修改密码")
    if submit:
        if not authenticate(user["username"], old):
            st.error("当前密码不正确。")
        elif len(new) < 12 or new != confirm:
            st.error("新密码至少12位，且两次输入必须一致。")
        else:
            salt, digest = _new_password(new)
            with _connect() as conn:
                conn.execute("UPDATE users SET salt=?, password_hash=?, updated_at=? WHERE username=?",
                             (salt, digest, datetime.now(timezone.utc).isoformat(), user["username"]))
            st.success("密码修改成功。")
