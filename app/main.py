import json
import os
import sqlite3
import time
import urllib.parse
from typing import Any

import httpx
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, PlainTextResponse, HTMLResponse, Response
from starlette.routing import Route

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", f"{PUBLIC_BASE_URL}/auth/linkedin/callback")
SCOPES = os.getenv("LINKEDIN_SCOPES", "openid profile email w_member_social")
LINKEDIN_VERSION = os.getenv("LINKEDIN_VERSION", "202609")
APP_SECRET = os.getenv("APP_SECRET", "dev-only-change-me")
DATA_PATH = os.getenv("DATA_PATH", "/tmp/linkedin.sqlite3")
FERNET_KEY = os.getenv("FERNET_KEY", "")

if FERNET_KEY:
    _fernet = Fernet(FERNET_KEY.encode())
else:
    # Local-development fallback only; production should always set FERNET_KEY.
    _fernet = Fernet(Fernet.generate_key())

_state = URLSafeTimedSerializer(APP_SECRET, salt="linkedin-oauth-state")


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(DATA_PATH)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS auth (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            access_token BLOB NOT NULL,
            expires_at INTEGER,
            member_sub TEXT,
            member_name TEXT,
            member_email TEXT,
            updated_at INTEGER NOT NULL
        )
        """
    )
    return con


def _save_auth(token: str, expires_in: int | None, userinfo: dict[str, Any]) -> None:
    encrypted = _fernet.encrypt(token.encode())
    expires_at = int(time.time()) + int(expires_in or 0) if expires_in else None
    with _db() as con:
        con.execute(
            """
            INSERT INTO auth(singleton, access_token, expires_at, member_sub, member_name, member_email, updated_at)
            VALUES(1,?,?,?,?,?,?)
            ON CONFLICT(singleton) DO UPDATE SET
              access_token=excluded.access_token,
              expires_at=excluded.expires_at,
              member_sub=excluded.member_sub,
              member_name=excluded.member_name,
              member_email=excluded.member_email,
              updated_at=excluded.updated_at
            """,
            (
                encrypted,
                expires_at,
                userinfo.get("sub"),
                userinfo.get("name"),
                userinfo.get("email"),
                int(time.time()),
            ),
        )


def _load_auth() -> dict[str, Any] | None:
    with _db() as con:
        row = con.execute(
            "SELECT access_token, expires_at, member_sub, member_name, member_email, updated_at FROM auth WHERE singleton=1"
        ).fetchone()
    if not row:
        return None
    token = _fernet.decrypt(row[0]).decode()
    return {
        "access_token": token,
        "expires_at": row[1],
        "member_sub": row[2],
        "member_name": row[3],
        "member_email": row[4],
        "updated_at": row[5],
    }


def _public_auth_status() -> dict[str, Any]:
    auth = _load_auth()
    if not auth:
        return {"connected": False, "reason": "not_authorized"}
    expired = bool(auth["expires_at"] and auth["expires_at"] <= int(time.time()))
    return {
        "connected": not expired,
        "expired": expired,
        "expires_at": auth["expires_at"],
        "member_sub": auth["member_sub"],
        "member_name": auth["member_name"],
        "member_email": auth["member_email"],
        "updated_at": auth["updated_at"],
    }


async def health(_: Request) -> Response:
    return JSONResponse({"ok": True, "service": "linkedin-executive-mcp", "version": "0.1.1"})


async def privacy(_: Request) -> Response:
    return HTMLResponse(
        """<!doctype html><html><head><meta charset='utf-8'><title>Privacy Policy</title></head>
        <body><h1>Privacy Policy - LinkedIn Executive Profile</h1>
        <p>This private integration is used by its authorized owner to connect ChatGPT with the owner's LinkedIn account.</p>
        <p>It stores an encrypted LinkedIn OAuth access token and the minimum identity information returned by LinkedIn needed to operate the integration. It does not sell personal data or share it with third parties except LinkedIn as necessary to perform authorized actions.</p>
        <p>The owner may revoke the LinkedIn authorization at any time from LinkedIn account settings or by deleting the stored authorization data from the service.</p>
        <p>Contact: integration owner / administrator.</p></body></html>"""
    )


async def terms(_: Request) -> Response:
    return HTMLResponse(
        """<!doctype html><html><head><meta charset='utf-8'><title>Terms</title></head>
        <body><h1>Terms of Use - LinkedIn Executive Profile</h1>
        <p>This is a private, owner-operated integration. Actions are performed only on the authenticated owner's behalf and remain subject to LinkedIn's terms and API policies.</p></body></html>"""
    )


async def auth_start(_: Request) -> Response:
    if not CLIENT_ID:
        return JSONResponse({"error": "LINKEDIN_CLIENT_ID is not configured"}, status_code=503)
    state = _state.dumps({"ts": int(time.time())})
    q = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT_URI,
            "state": state,
            "scope": SCOPES,
        }
    )
    return RedirectResponse(f"https://www.linkedin.com/oauth/v2/authorization?{q}")


async def auth_callback(request: Request) -> Response:
    err = request.query_params.get("error")
    if err:
        return PlainTextResponse(f"LinkedIn authorization failed: {err}", status_code=400)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        return PlainTextResponse("Missing code/state", status_code=400)
    try:
        _state.loads(state, max_age=900)
    except (BadSignature, SignatureExpired):
        return PlainTextResponse("Invalid or expired OAuth state", status_code=400)
    if not CLIENT_SECRET:
        return PlainTextResponse("LINKEDIN_CLIENT_SECRET is not configured", status_code=503)

    async with httpx.AsyncClient(timeout=30) as client:
        token_resp = await client.post(
            "https://www.linkedin.com/oauth/v2/accessToken",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
            },
        )
        if token_resp.status_code >= 400:
            return PlainTextResponse(f"Token exchange failed: {token_resp.text}", status_code=502)
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        userinfo_resp = await client.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code >= 400:
            return PlainTextResponse(f"Userinfo failed: {userinfo_resp.text}", status_code=502)
        userinfo = userinfo_resp.json()

    _save_auth(access_token, token_data.get("expires_in"), userinfo)
    return HTMLResponse(
        f"<h1>LinkedIn connected</h1><p>Authorized as {userinfo.get('name','member')}.</p><p>You may close this window and return to ChatGPT.</p>"
    )


async def _publish_text(text: str, visibility: str = "PUBLIC") -> dict[str, Any]:
    auth = _load_auth()
    if not auth:
        raise RuntimeError("LinkedIn is not authorized. Open /auth/linkedin/start first.")
    if auth["expires_at"] and auth["expires_at"] <= int(time.time()):
        raise RuntimeError("LinkedIn access token has expired. Re-authorize the connection.")
    sub = auth.get("member_sub")
    if not sub:
        raise RuntimeError("LinkedIn member identifier is missing. Re-authorize with openid profile scope.")
    payload = {
        "author": f"urn:li:person:{sub}",
        "commentary": text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.linkedin.com/rest/posts",
            headers={
                "Authorization": f"Bearer {auth['access_token']}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
                "Linkedin-Version": LINKEDIN_VERSION,
            },
            json=payload,
        )
    if resp.status_code != 201:
        raise RuntimeError(f"LinkedIn post failed ({resp.status_code}): {resp.text}")
    return {"ok": True, "post_id": resp.headers.get("x-restli-id"), "status_code": resp.status_code}


def _tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": "linkedin_connection_status",
            "description": "Check whether the private LinkedIn OAuth connection is active. This is read-only.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "linkedin_get_authorization_url",
            "description": "Return the private URL the owner should open to authorize or re-authorize LinkedIn.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "linkedin_get_my_identity",
            "description": "Return the minimum LinkedIn identity stored for the authenticated owner. Read-only.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "linkedin_publish_text_post",
            "description": "Publish a text post to the authenticated owner's LinkedIn profile. This is a write action. Only call after the user explicitly approves the exact final post text in the current conversation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 3000},
                    "visibility": {"type": "string", "enum": ["PUBLIC", "CONNECTIONS"], "default": "PUBLIC"},
                    "confirm": {"type": "boolean", "description": "Must be true only after explicit user approval of the exact post text."},
                },
                "required": ["text", "confirm"],
                "additionalProperties": False,
            },
        },
    ]


def _tool_result(data: Any, *, is_error: bool = False) -> dict[str, Any]:
    txt = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return {"content": [{"type": "text", "text": txt}], "isError": is_error}


async def mcp(request: Request) -> Response:
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)

    method = payload.get("method")
    req_id = payload.get("id")
    params = payload.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "linkedin-executive-mcp", "version": "0.1.1"},
        }
    elif method == "notifications/initialized":
        return Response(status_code=202)
    elif method == "tools/list":
        result = {"tools": _tool_defs()}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "linkedin_connection_status":
                result = _tool_result(_public_auth_status())
            elif name == "linkedin_get_authorization_url":
                result = _tool_result({"authorization_url": f"{PUBLIC_BASE_URL}/auth/linkedin/start"})
            elif name == "linkedin_get_my_identity":
                st = _public_auth_status()
                result = _tool_result({k: st.get(k) for k in ["connected", "expired", "member_sub", "member_name", "member_email", "expires_at"]})
            elif name == "linkedin_publish_text_post":
                if args.get("confirm") is not True:
                    raise RuntimeError("Explicit user approval is required before publishing.")
                text = (args.get("text") or "").strip()
                if not text:
                    raise RuntimeError("Post text cannot be empty.")
                visibility = args.get("visibility", "PUBLIC")
                result = _tool_result(await _publish_text(text, visibility))
            else:
                result = _tool_result({"error": f"Unknown tool: {name}"}, is_error=True)
        except Exception as exc:
            result = _tool_result({"error": str(exc)}, is_error=True)
    else:
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}})

    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})


routes = [
    Route("/", endpoint=lambda request: HTMLResponse("<h1>LinkedIn Executive MCP</h1><p><a href='/health'>Health</a> · <a href='/privacy'>Privacy</a></p>")),
    Route("/health", health),
    Route("/privacy", privacy),
    Route("/terms", terms),
    Route("/auth/linkedin/start", auth_start),
    Route("/auth/linkedin/callback", auth_callback),
    Route("/mcp", mcp, methods=["POST"]),
]

app = Starlette(routes=routes)
