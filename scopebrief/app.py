import asyncio
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .api_models import Archive, Ask, FeedbackInput, Publish, SharedLogin, Slug
from .benchmark import offline_report
from .http_session import COOKIE as COOKIE
from .http_session import SessionDep, current_session, replace_session, session_data
from .identity import Conflict, Denied, QueueFull, Session
from .intake import UPLOAD_BYTES, import_document, source_name
from .model import ChatModel
from .review import Review
from .run_queue import QUEUE_CAPACITY, RunQueue
from .settings import Settings
from .store import TERMINAL, Store
from .team import Team
from .team_routes import router as team_router

STATIC = Path(__file__).resolve().parents[1] / "frontend" / "dist"
JSON_BYTES = 2_400_000


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if bool(settings.model_base_url) != bool(settings.model_name):
        raise ValueError("Model configuration requires both a base URL and a model name")
    store = Store(settings.db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store.initialize(seed=settings.mode != "team")
        store.recover_runs()
        app.state.import_slots = asyncio.Semaphore(2)
        app.state.evaluate_lock = asyncio.Lock()
        async with httpx.AsyncClient(timeout=settings.model_timeout, trust_env=False) as client:
            model = ChatModel(settings, client) if settings.model_name else None
            queue = RunQueue(store, settings.mode, model)
            app.state.queue = queue
            try:
                yield
            finally:
                await queue.close()

    app = FastAPI(title="ScopeBrief", version="2.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.team = Team(store)
    app.state.review = Review(store)
    app.include_router(team_router)

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        api = request.url.path.startswith("/api/")
        if api and request.method == "POST":
            origin = request.headers.get("origin")
            host = request.headers.get("host", "")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc.casefold() != host.casefold()
            ):
                return JSONResponse({"detail": "请从工作台页面发起操作。"}, status_code=403)
            declared = request.headers.get("content-length", "")
            limit = UPLOAD_BYTES if request.url.path == "/api/intake/preview" else JSON_BYTES
            if declared.isdigit() and int(declared) > limit:
                return JSONResponse({"detail": "请求超过允许的大小。"}, status_code=413)
        response = await call_next(request)
        if api:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        fields = "、".join(dict.fromkeys(str(error["loc"][-1]) for error in exc.errors()))
        return JSONResponse({"detail": f"请检查输入字段 {fields}。"}, status_code=422)

    @app.exception_handler(Denied)
    async def denied(_request: Request, exc: Denied):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(Conflict)
    async def conflict(_request: Request, exc: Conflict):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(QueueFull)
    async def overloaded(_request: Request, exc: QueueFull):
        return JSONResponse({"detail": str(exc)}, status_code=429)

    @app.exception_handler(LookupError)
    async def not_found(_request: Request, exc: LookupError):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(_request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    def owned_run(session: Session, run_id: str) -> dict:
        run = store.run(session, run_id)
        if run is None:
            raise HTTPException(404, "未找到该运行。")
        return run

    @app.get("/api/health")
    def health():
        with store.connect() as conn:
            conn.execute("SELECT 1 FROM workspace_settings LIMIT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/session")
    def session(request: Request, response: Response):
        current = current_session(request)
        if current is None and settings.demo:
            current = replace_session(request, response, "member")
        return session_data(request, current)

    @app.post("/api/session")
    def login(request: Request, response: Response, payload: SharedLogin):
        if settings.mode == "team":
            raise HTTPException(404, "请使用团队账号登录。")
        if settings.mode == "shared":
            expected = settings.member_key if payload.role == "member" else settings.reviewer_key
            if not expected or not secrets.compare_digest(payload.key.encode(), expected.encode()):
                raise HTTPException(401, "角色口令无效。")
        return session_data(request, replace_session(request, response, payload.role))

    @app.get("/api/documents")
    def documents(session: SessionDep):
        return store.documents(session.access)

    @app.get("/api/documents/{document_id}")
    def document(document_id: str, session: SessionDep):
        rows = store.documents(session.access, document_id)
        if not rows:
            raise HTTPException(404, "未找到该资料。")
        return rows[0]

    @app.post("/api/intake/preview")
    async def intake(
        request: Request,
        session: SessionDep,
        project_id: Slug,
        filename: Annotated[str, Query(min_length=1, max_length=220)],
    ):
        if project_id not in {p.id for p in store.projects(session.access, writable=True)}:
            raise Denied("当前身份无法向此项目导入资料。")
        slots = request.app.state.import_slots
        if slots.locked():
            raise QueueFull("其他文件正在解析，请稍后再试。")
        async with slots:
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > UPLOAD_BYTES:
                    raise HTTPException(413, "单个文件上限为 8 MiB。")
                data.extend(chunk)
            return await run_in_threadpool(import_document, filename, bytes(data))

    @app.post("/api/documents", status_code=201)
    def publish(payload: Publish, session: SessionDep):
        doc_id = store.publish(
            payload.project_id,
            payload.key,
            payload.title,
            payload.body,
            access=session.access,
            source_name=source_name(payload.source_name),
            change_note=payload.change_note,
            expected_revision=payload.expected_revision,
            create_only=payload.create_only,
        )
        visible = store.documents(session.access, doc_id)
        if not visible:
            raise Denied("资料已发布，当前会话的项目权限已变化。")
        return visible[0]

    @app.post("/api/documents/{project_id}/{key}/archive")
    def archive(project_id: Slug, key: Slug, payload: Archive, session: SessionDep):
        store.archive(session.access, project_id, key, payload.archived)
        return {"ok": True}

    @app.post("/api/runs", status_code=202)
    async def start(request: Request, payload: Ask, session: SessionDep):
        ids = set(payload.project_ids)
        if len(ids) != len(payload.project_ids) or not ids <= {
            p.id for p in store.projects(session.access)
        }:
            raise HTTPException(404, "所选项目范围不可用。")
        run_id = secrets.token_hex(12)
        store.enqueue(session, run_id, payload.question, payload.project_ids, QUEUE_CAPACITY)
        request.app.state.queue.notice()
        return {"id": run_id}

    @app.get("/api/runs")
    def runs(session: SessionDep):
        return store.runs(session)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, session: SessionDep):
        return owned_run(session, run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(request: Request, run_id: str, session: SessionDep):
        owned_run(session, run_id)
        if store.cancel(run_id):
            request.app.state.queue.cancel(run_id)
        return owned_run(session, run_id)

    @app.post("/api/runs/{run_id}/feedback")
    def feedback(run_id: str, payload: FeedbackInput, session: SessionDep):
        store.save_feedback(session, run_id, payload.rating, payload.note)
        return owned_run(session, run_id)

    @app.get("/api/runs/{run_id}/events")
    async def events(request: Request, run_id: str, session: SessionDep):
        initial = owned_run(session, run_id)

        async def stream():
            snapshot, previous = initial, None
            while snapshot and not await request.is_disconnected():
                live = current_session(request)
                if live is None or live.id != session.id:
                    break
                snapshot = store.run(live, run_id)
                if not snapshot:
                    break
                revision = (snapshot["status"], len(snapshot["events"]))
                if revision != previous:
                    encoded = json.dumps(snapshot, ensure_ascii=False)
                    yield f"event: snapshot\ndata: {encoded}\n\n"
                    previous = revision
                if snapshot["status"] in TERMINAL:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.post("/api/benchmark")
    def benchmark(_session: SessionDep):
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
