"""
OAuth authentication for the Drive Scanner.
Subset of the main pipeline auth — only Drive + Activity services.
"""

import os
import json
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from drive_scanner.config import SCOPES, CLIENT_SECRET_FILE, TOKEN_FILE


def authenticate():
    """
    Authenticate via OAuth.
    - GitHub Actions: reads token from GOOGLE_TOKEN env var (secret).
    - Local: uses cached/refreshed token file, or opens browser.
    Returns google.oauth2.credentials.Credentials
    """
    creds = None

    # Option 1: Token from environment variable (GitHub Actions)
    token_env = os.environ.get("GOOGLE_TOKEN")
    if token_env:
        try:
            token_data = json.loads(token_env)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"Warning: Failed to load token from GOOGLE_TOKEN env: {e}")

    # Option 2: Token from file (local development)
    if not creds and os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    # Refresh or re-authenticate
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            if token_env:
                raise RuntimeError(
                    "GOOGLE_TOKEN is set but invalid/expired with no refresh token. "
                    "Re-run local auth to generate a fresh token."
                )
            print("Opening browser for Google login...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for future runs (local only)
        if not token_env:
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
            print("Token saved.\n")

    return creds


def get_drive_service(creds=None):
    """Build and return Google Drive API v3 service."""
    if creds is None:
        creds = authenticate()
    return build("drive", "v3", credentials=creds)


def get_activity_service(creds=None):
    """Build and return Drive Activity API v2 service."""
    if creds is None:
        creds = authenticate()
    return build("driveactivity", "v2", credentials=creds)
