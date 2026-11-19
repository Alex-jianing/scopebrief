import asyncio
import hashlib
import json
import logging
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from .benchmark import offline_report
from .harness import answer
from .model import ChatModel
from .settings import Settings
from .store import TERMINAL, Role, Store

COOKIE = "scopebrief_session"
SESSION_TTL = 12 * 60 * 60
MAX_ACTIVE = 4
STATIC = Path(__file__).resolve().parents[1] / "frontend" / "dist"
LOG = logging.getLogger(__name__)

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=40)]
QuestionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=600)
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]


class Ask(BaseModel):
    question: QuestionText
    project_ids: list[Slug] = Field(min_length=1, max_length=3)


class Login(BaseModel):
    role: Role
    key: str = Field(default="", max_length=512)


class Publish(BaseModel):
    project_id: Slug
    key: Slug
    title: Title
    body: str = Field(min_length=1, max_length=16000)


def session_id(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    return hashlib.sha256(token.encode()).hexdigest() if len(token) == 43 else ""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if bool(settings.model_base_url) != bool(settings.model_name):
        raise ValueError("Model configuration requires both a base URL and a model name")
    store = Store(settings.db)
    active: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize()
        store.recover_runs()
        async with httpx.AsyncClient(timeout=settings.model_timeout, trust_env=False) as client:
            app.state.model = ChatModel(settings, client) if settings.model_name else None
            yield
            for task in active.copy():
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)

    app = FastAPI(title="ScopeBrief", version="1.0.0", lifespan=lifespan)

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        if (
            request.url.path.startswith("/api/")
            and request.method == "POST"
            and request.headers.get("sec-fetch-site") == "cross-site"
        ):
            return JSONResponse({"detail": "请从工作台页面发起操作。"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        fields = "、".join(dict.fromkeys(str(error["loc"][-1]) for error in exc.errors()))
        return JSONResponse({"detail": f"请检查输入字段 {fields}。"}, status_code=422)

    def start_session(request: Request, response: Response, role: Role) -> None:
        old = session_id(request)
        if old:
            store.remove_session(old)
        token = secrets.token_urlsafe(32)
        store.add_session(hashlib.sha256(token.encode()).hexdigest(), role, SESSION_TTL)
        response.set_cookie(
            COOKIE,
            token,
            max_age=SESSION_TTL,
            httponly=True,
            secure=settings.secure_cookie,
            samesite="strict",
            path="/api",
        )

    def require_session(request: Request) -> tuple[str, Role]:
        identity = session_id(request)
        role = store.get_role(identity)
        if role is None:
            raise HTTPException(401, "请先登录项目证据台。")
        return identity, role

    def session_data(role: Role | None) -> dict:
        return {
            "role": role,
            "demo": settings.demo,
            "model": settings.model_name or None,
            "projects": [p.public() for p in store.projects(role)] if role else [],
        }

    def owned_run(owner: str, run_id: str) -> dict:
        run = store.run(owner, run_id)
        if run is None:
            raise HTTPException(404, "未找到该运行。")
        return run

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/session")
    def session(request: Request, response: Response):
        role = store.get_role(session_id(request))
        if role is None and settings.demo:
            role = "member"
            start_session(request, response, role)
        return session_data(role)

    @app.post("/api/session")
    def login(request: Request, response: Response, payload: Login):
        if not settings.demo:
            expected = settings.member_key if payload.role == "member" else settings.reviewer_key
            if not expected or not secrets.compare_digest(payload.key.encode(), expected.encode()):
                raise HTTPException(401, "角色口令无效。")
        start_session(request, response, payload.role)
        return session_data(payload.role)

    @app.get("/api/documents")
    def documents(identity: Annotated[tuple[str, Role], Depends(require_session)]):
        return store.documents(identity[1])

    @app.get("/api/documents/{document_id}")
    def document(document_id: str, identity: Annotated[tuple[str, Role], Depends(require_session)]):
        rows = store.documents(identity[1], document_id)
        if not rows:
            raise HTTPException(404, "未找到该资料。")
        return rows[0]

    @app.post("/api/documents", status_code=201)
    def publish(payload: Publish, identity: Annotated[tuple[str, Role], Depends(require_session)]):
        if identity[1] != "reviewer":
            raise HTTPException(403, "评审者可以发布文档。")
        if payload.project_id not in {p.id for p in store.projects(identity[1])}:
            raise HTTPException(404, "未找到该项目。")
        try:
            doc_id = store.publish(payload.project_id, payload.key, payload.title, payload.body)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return store.documents(identity[1], doc_id)[0]

    async def execute(run_id: str, role: Role, payload: Ask):
        try:
            result = await answer(
                store,
                role,
                payload.question,
                payload.project_ids,
                model=app.state.model,
                on_event=lambda stage, detail, ms: store.add_event(run_id, stage, detail, ms),
            )
            store.finish_run(run_id, result)
        except asyncio.CancelledError:
            store.finish_run(run_id, None, "运行已中断，请重新提问。")
            raise
        except sqlite3.IntegrityError:
            # A session can be replaced while a provider request is outstanding.
            store.finish_run(run_id, None, "会话已切换，请重新提问。")
        except Exception:
            LOG.exception("Run %s failed", run_id)
            store.finish_run(run_id, None, "运行失败，请重新提问。")

    @app.post("/api/runs", status_code=202)
    async def start(payload: Ask, identity: Annotated[tuple[str, Role], Depends(require_session)]):
        owner, role = identity
        ids = set(payload.project_ids)
        if len(ids) != len(payload.project_ids) or not ids <= {p.id for p in store.projects(role)}:
            raise HTTPException(404, "所选项目范围不可用。")
        if len(active) >= MAX_ACTIVE:
            raise HTTPException(429, "运行队列已满，请稍后重试。")
        run_id = secrets.token_hex(12)
        try:
            store.start_run(owner, run_id, payload.question, payload.project_ids)
        except sqlite3.IntegrityError as exc:
            if store.get_role(owner) is None:
                raise HTTPException(401, "会话已切换，请重新提问。") from exc
            raise HTTPException(409, "当前会话已有一条运行。") from exc
        task = asyncio.create_task(execute(run_id, role, payload))
        active.add(task)
        task.add_done_callback(active.discard)
        return {"id": run_id}

    @app.get("/api/runs")
    def runs(identity: Annotated[tuple[str, Role], Depends(require_session)]):
        return store.runs(identity[0])

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, identity: Annotated[tuple[str, Role], Depends(require_session)]):
        return owned_run(identity[0], run_id)

    @app.get("/api/runs/{run_id}/events")
    async def events(
        request: Request,
        run_id: str,
        identity: Annotated[tuple[str, Role], Depends(require_session)],
    ):
        owner, _ = identity
        initial = owned_run(owner, run_id)

        async def stream():
            snapshot, previous = initial, None
            while snapshot and not await request.is_disconnected():
                revision = (snapshot["status"], len(snapshot["events"]))
                if revision != previous:
                    encoded = json.dumps(snapshot, ensure_ascii=False)
                    yield f"event: snapshot\ndata: {encoded}\n\n"
                    previous = revision
                if snapshot["status"] in TERMINAL:
                    break
                await asyncio.sleep(0.2)
                if store.get_role(owner) is None:
                    break
                snapshot = store.run(owner, run_id)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/api/benchmark")
    def benchmark(_identity: Annotated[tuple[str, Role], Depends(require_session)]):
        return offline_report()

    if (STATIC / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def index():
        if not (STATIC / "index.html").is_file():
            return HTMLResponse(
                '<meta charset="utf-8"><h1>ScopeBrief API</h1>'
                '<p>前端开发使用 Vite。生产构建后重启服务。</p><a href="/docs">API 文档</a>'
            )
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    return app


app = create_app()
