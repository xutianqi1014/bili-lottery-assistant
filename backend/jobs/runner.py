import asyncio
from collections.abc import Awaitable, Callable

from .events import EventHub


class JobRunner:
    def __init__(self, events: EventHub):
        self.events = events
        self._tasks: dict[str, asyncio.Task] = {}
        self._active_job_id: str | None = None

    def can_submit(self, job_id: str) -> bool:
        active = self._active_job_id
        if active is None:
            return True
        task = self._tasks.get(active)
        return task is None or task.done()

    def submit(self, job_id: str, callback: Callable[[], Awaitable[None]]) -> None:
        if job_id in self._tasks and not self._tasks[job_id].done():
            raise RuntimeError("JOB_ALREADY_RUNNING")
        active = self._active_job_id
        if active is not None:
            task = self._tasks.get(active)
            if task is not None and not task.done() and active != job_id:
                raise RuntimeError("JOB_SLOT_BUSY")
        task = asyncio.create_task(self._run(job_id, callback), name=f"job:{job_id}")
        self._tasks[job_id] = task
        self._active_job_id = job_id
        task.add_done_callback(lambda completed: self._forget(job_id, completed))

    async def _run(self, job_id: str, callback: Callable[[], Awaitable[None]]) -> None:
        try:
            await self.events.publish("job.started", {"jobId": job_id})
            await callback()
        except asyncio.CancelledError:
            await self.events.publish("job.cancelled", {"jobId": job_id})
            raise
        except Exception as exc:
            await self.events.publish(
                "job.failed", {"jobId": job_id, "error": type(exc).__name__}
            )
        else:
            await self.events.publish("job.finished", {"jobId": job_id})
        finally:
            task = asyncio.current_task()
            if task is not None:
                self._forget(job_id, task)

    def _forget(self, job_id: str, task: asyncio.Task) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)
            if self._active_job_id == job_id:
                self._active_job_id = None

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
