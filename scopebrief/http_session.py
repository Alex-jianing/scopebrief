import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from .identity import Access, Account, Session, digest
from .store import Store

COOKIE = "scopebrief_session"
TEAM_COOKIE = "scopebrief_team_session"
SESSION_TTL = 12 * 60 * 60


def request_store(request: Request) -> Store:
    return request.app.state.store


def cookie_name(request: Request) -> str:
    return TEAM_COOKIE if request.app.state.settings.mode == "team" else COOKIE


def current_session(request: Request) -> Session | None:
    token = request.cookies.get(cookie_name(request), "")
    if len(token) != 43:
        return None
    return request_store(request).session(digest(token), request.app.state.settings.mode)


def require_session(request: Request) -> Session:
    session = current_session(request)
    if session is None:
        raise HTTPException(401, "请先登录项目证据台。")
    return session


SessionDep = Annotated[Session, Depends(require_session)]


def require_team_admin(session: SessionDep) -> Account:
    if session.account is None or not session.account.admin:
        raise HTTPException(403, "需要团队管理员身份。")
    return session.account


AdminDep = Annotated[Account, Depends(require_team_admin)]


def replace_session(request: Request, response: Response, access: Access) -> Session:
    settings = request.app.state.settings
    store = request_store(request)
    old = current_session(request)
    token = secrets.token_urlsafe(32)
    session = Session(digest(token), settings.mode, access)
    store.add_session(session, SESSION_TTL)
    if old:
        store.remove_session(old.id, old.mode)
    response.set_cookie(
        cookie_name(request),
        token,
        max_age=SESSION_TTL,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="strict",
        path="/api",
    )
    return session


def session_data(request: Request, session: Session | None) -> dict:
    settings, store = request.app.state.settings, request_store(request)
    account = session.account if session else None
    role = (
        ("reviewer" if account.admin else "member")
        if account
        else session.access
        if session
        else None
    )
    projects = []
    if session:
        editable = {p.id for p in store.projects(session.access, writable=True)}
        projects = [
            p.public() | {"can_edit": p.id in editable} for p in store.projects(session.access)
        ]
    return {
        "role": role,
        "demo": settings.demo,
        "mode": settings.mode,
        "account": account.public() if account else None,
        "model": settings.model_name or None,
        "projects": projects,
    }
