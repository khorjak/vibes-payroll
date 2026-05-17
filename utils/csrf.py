import secrets
from typing import Annotated
from fastapi import Depends, Form, HTTPException, Request


def _get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def csrf_token_global(request: Request) -> str:
    """Jinja2 global: {{ csrf_token(request) }}"""
    return _get_csrf_token(request)


def _csrf_dep(request: Request, csrf_token: str = Form(default="")) -> None:
    if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
        return
    session_token = request.session.get("csrf_token", "")
    if not session_token or csrf_token != session_token:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


CsrfProtect = Annotated[None, Depends(_csrf_dep)]
