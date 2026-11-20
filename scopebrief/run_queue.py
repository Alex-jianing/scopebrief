import asyncio
import logging

from .harness import answer
from .identity import Mode
from .model import ChatModel
from .store import Store

LOG = logging.getLogger(__name__)
WORKERS = 4
QUEUE_CAPACITY = 64


class RunQueue:
    def __init__(self, store: Store, mode: Mode, model: ChatModel | None):
        self.store = store
        self.mode = mode
        self.model = model
        self.wake = asyncio.Event()
        self.tasks: dict[str, asyncio.Task] = {}
        self.workers = [asyncio.create_task(self._work()) for _ in range(WORKERS)]

    def notice(self) -> None:
        self.wake.set()

    def cancel(self, run_id: str) -> None:
        if task := self.tasks.get(run_id):
            task.cancel()

    async def close(self) -> None:
        for task in self.workers:
            task.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    async def _work(self) -> None:
        # Stop waiting briefly as a fallback for a committed queue item after a prior restart.
        while True:
            try:
                job = self.store.claim(self.mode)
                if not job:
                    self.wake.clear()
                    try:
                        await asyncio.wait_for(self.wake.wait(), timeout=1)
                    except TimeoutError:
                        pass
                    continue
                task = asyncio.create_task(self._execute(job))
                self.tasks[job["id"]] = task
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    self.tasks.pop(job["id"], None)
            except Exception:
                LOG.exception("Could not claim or run a queued question")
                await asyncio.sleep(1)

    async def _execute(self, job: dict) -> None:
        run_id = job["id"]
        try:
            session = self.store.session(job["session_id"], self.mode, allow_expired_account=True)
            if session is None or not set(job["scope"]) <= {
                p.id for p in self.store.projects(session.access)
            }:
                self.store.finish_run(run_id, None, "项目授权或会话已变化，请重新提交。")
                return
            result = await answer(
                self.store,
                session.access,
                job["question"],
                job["scope"],
                model=self.model,
                on_event=lambda stage, detail, ms: self.store.add_event(run_id, stage, detail, ms),
            )
            self.store.finish_run(run_id, result)
        except asyncio.CancelledError:
            self.store.finish_run(run_id, None, "运行已中断，请重新提问。")
            raise
        except Exception:
            LOG.exception("Run %s failed", run_id)
            self.store.finish_run(run_id, None, "运行失败，请重新提问。")
