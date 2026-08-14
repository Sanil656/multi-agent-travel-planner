"""
auth.py – Authentication helpers for the Travel Planner application.

Supports:
  • Google OAuth 2.0 (Authorization Code flow)
  • Phone OTP  (6-digit code; shown on-screen for demo;
                swap send_otp_sms() body for Twilio to go live)

Session-state contract
──────────────────────
  st.session_state.authenticated  bool
  st.session_state.user           dict | None
      {name, email, picture, phone, auth_method}
  st.session_state.threads        dict  (managed by frontend.py)
  st.session_state.otp_code       str   (temporary, cleared after verify)
  st.session_state.otp_phone      str
  st.session_state.otp_sent       bool
"""

from __future__ import annotations

import os
import random
import string
from urllib.parse import urlencode

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Google OAuth config ────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID: str     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI: str  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8501")

_GOOGLE_AUTH_ENDPOINT  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL   = "https://www.googleapis.com/oauth2/v2/userinfo"


# ── Google OAuth ───────────────────────────────────────────────────────────────

def google_configured() -> bool:
    """Return True only when both Client ID and Secret are set."""
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def get_google_auth_url() -> str:
    """Build the Google OAuth 2.0 authorization URL."""
    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "prompt":        "select_account",
        "access_type":   "offline",
    }
    return f"{_GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code_for_user(code: str) -> dict | None:
    """
    Exchange an OAuth authorization code for a user profile dict.
    Returns None on any failure so the caller can show an error.
    """
    try:
        token_resp = requests.post(
            _GOOGLE_TOKEN_ENDPOINT,
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            timeout=10,
        )
        token_data   = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return None

        user_resp = requests.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        info = user_resp.json()
        return {
            "name":        info.get("name", "Traveller"),
            "email":       info.get("email", ""),
            "picture":     info.get("picture", ""),
            "phone":       "",
            "auth_method": "google",
        }
    except Exception:
        return None


# ── Phone OTP ──────────────────────────────────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """Return a random numeric OTP string of *length* digits."""
    return "".join(random.choices(string.digits, k=length))


def send_otp_sms(phone: str, otp: str) -> bool:
    """
    Send the OTP to *phone* via SMS.

    Demo mode (default): does nothing and returns False so the caller
    shows the OTP on-screen.

    Production: uncomment the Twilio block below, add
        TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
    to your .env, and install the `twilio` package.

    Returns True when SMS was dispatched successfully.
    """
    # ── Twilio (production) ────────────────────────────────────────────────────
    # from twilio.rest import Client
    # account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    # auth_token  = os.getenv("TWILIO_AUTH_TOKEN",  "")
    # from_number = os.getenv("TWILIO_FROM_NUMBER", "")
    # if account_sid and auth_token and from_number:
    #     try:
    #         client = Client(account_sid, auth_token)
    #         client.messages.create(
    #             body=f"Your Travel Planner OTP is: {otp}",
    #             from_=from_number,
    #             to=phone,
    #         )
    #         return True
    #     except Exception:
    #         return False
    # ──────────────────────────────────────────────────────────────────────────
    return False  # Demo mode: OTP shown on-screen


# ── Session helpers ────────────────────────────────────────────────────────────

def is_authenticated() -> bool:
    return st.session_state.get("authenticated", False)


def get_current_user() -> dict | None:
    return st.session_state.get("user")


def login_user(user: dict) -> None:
    """Mark the session as authenticated and store the user profile."""
    st.session_state.authenticated = True
    st.session_state.user          = user
    # Ensure threads bucket exists for the main app
    if "threads" not in st.session_state:
        st.session_state.threads = {}


def logout_user() -> None:
    """Clear all auth and app state from the session."""
    for key in (
        "authenticated", "user", "threads", "active_thread_id",
        "otp_code", "otp_phone", "otp_sent",
    ):
        st.session_state.pop(key, None)
