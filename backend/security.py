"""Synthetic local-demo accounts and expiring server-side sessions."""

import hashlib
import hmac
from http.cookies import SimpleCookie, CookieError
import secrets
import time


DEMO_ACCOUNTS = {
    "analyst": {"password": "AnalystDemo!2026", "role": "analyst"},
    "manager": {"password": "ManagerDemo!2026", "role": "manager"},
}
SESSION_SECONDS = 4 * 60 * 60


def password_hash(username, password):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), ("icontinuum-demo-" + username).encode(), 120000)


PASSWORD_HASHES = {name: password_hash(name, account["password"]) for name, account in DEMO_ACCOUNTS.items()}


def authenticate(username, password):
    if not isinstance(username, str) or not isinstance(password, str) or len(username) > 64 or len(password) > 128:
        return None
    expected = PASSWORD_HASHES.get(username, PASSWORD_HASHES["analyst"])
    matches = hmac.compare_digest(password_hash(username, password), expected)
    if not matches or username not in DEMO_ACCOUNTS:
        return None
    return {"username": username, "role": DEMO_ACCOUNTS[username]["role"]}


def session_token(headers):
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("Cookie", ""))
    except CookieError:
        return None
    value = cookie.get("icontinuum_session")
    return value.value if value else None


def new_session(sessions, user):
    now = time.time()
    for token in list(sessions):
        if sessions[token]["expires"] <= now:
            del sessions[token]
    token = secrets.token_urlsafe(32)
    sessions[token] = {"user": user, "expires": now + SESSION_SECONDS}
    return token


def cookie_header(token, logout=False):
    return "icontinuum_session={}; HttpOnly; SameSite=Strict; Path=/; Max-Age={}".format(
        token, 0 if logout else SESSION_SECONDS)
