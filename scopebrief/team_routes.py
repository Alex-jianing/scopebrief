from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .api_models import (
    Activation,
    Archive,
    CaseInput,
    Credentials,
    InviteInput,
    MemberInput,
    ProjectInput,
)
from .http_session import (
    AdminDep,
    SessionDep,
    cookie_name,
    replace_session,
    request_store,
    session_data,
)
from .team import Team

router = APIRouter(prefix="/api")


def get_team(request: Request) -> Team:
    if request.app.state.settings.mode != "team":
        raise HTTPException(404, "请在团队工作区使用此功能。")
    return request.app.state.team


TeamDep = Annotated[Team, Depends(get_team)]


@router.post("/auth/login")
def login(request: Request, response: Response, payload: Credentials, team: TeamDep):
    team.throttle(request.client.host if request.client else "unknown")
    actor = team.authenticate(payload.username, payload.password)
    if actor is None:
        raise HTTPException(401, "用户名或密码无效。")
    return session_data(request, replace_session(request, response, actor))


@router.post("/auth/activate", status_code=201)
def activate(request: Request, response: Response, payload: Activation, team: TeamDep):
    team.throttle(request.client.host if request.client else "unknown")
    actor = team.redeem(payload.code, payload.username, payload.name, payload.password)
    return session_data(request, replace_session(request, response, actor))


@router.post("/auth/logout")
def logout(request: Request, response: Response, session: SessionDep):
    request_store(request).remove_session(session.id, session.mode)
    response.delete_cookie(cookie_name(request), path="/api")
    return {"ok": True}


@router.get("/team")
def overview(actor: AdminDep, team: TeamDep):
    return team.overview(actor)


@router.post("/team/projects")
def save_project(payload: ProjectInput, actor: AdminDep, team: TeamDep):
    team.projects(
        actor, payload.id, payload.name, payload.description, payload.aliases, payload.color
    )
    return {"id": payload.id}


@router.post("/team/invitations", status_code=201)
def invite(payload: InviteInput, actor: AdminDep, team: TeamDep):
    return team.issue(actor, payload.label, payload.grants)


@router.post("/team/invitations/{invitation_id}/revoke")
def revoke(invitation_id: str, actor: AdminDep, team: TeamDep):
    team.revoke(actor, invitation_id)
    return {"ok": True}


@router.post("/team/members/{member_id}")
def update_member(member_id: str, payload: MemberInput, actor: AdminDep, team: TeamDep):
    team.update_member(actor, member_id, payload.enabled, payload.grants)
    return {"ok": True}


@router.get("/review")
def review(request: Request, actor: AdminDep):
    return request.app.state.review.overview(actor)


@router.post("/review/cases", status_code=201)
def save_case(request: Request, payload: CaseInput, actor: AdminDep):
    return {"id": request.app.state.review.save_case(actor, payload)}


@router.post("/review/cases/{case_id}")
def edit_case(request: Request, case_id: str, payload: CaseInput, actor: AdminDep):
    return {"id": request.app.state.review.save_case(actor, payload, case_id)}


@router.post("/review/cases/{case_id}/availability")
def toggle_case(request: Request, case_id: str, payload: Archive, actor: AdminDep):
    request.app.state.review.toggle_case(actor, case_id, not payload.archived)
    return {"ok": True}


@router.post("/review/feedback/{run_id}/resolve")
def resolve(request: Request, run_id: str, actor: AdminDep):
    request.app.state.review.resolve(actor, run_id)
    return {"ok": True}


@router.get("/review/reports/{report_id}")
def report(request: Request, report_id: str, actor: AdminDep):
    return request.app.state.review.report(actor, report_id)


@router.post("/review/evaluate")
async def evaluate(request: Request, actor: AdminDep):
    guard = request.app.state.evaluate_lock
    if guard.locked():
        raise HTTPException(409, "已有一轮团队评测正在运行。")
    async with guard:
        return await request.app.state.review.evaluate(actor)
