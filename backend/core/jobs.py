# -*- coding: utf-8 -*-
"""极简后台任务管理器：进度 + 日志 + 结果，供前端轮询。"""
from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wxjob")
_jobs: dict[str, "Job"] = {}
_lock = threading.Lock()


class Job:
    def __init__(self, kind: str, payload: dict):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.payload = payload
        self.state = "running"          # running | done | error
        self.progress = 0
        self.logs: deque[str] = deque(maxlen=500)
        self.result: dict | None = None
        self.error: str | None = None
        self.created = time.time()

    def log(self, msg: str) -> None:
        line = time.strftime("[%H:%M:%S] ") + msg
        self.logs.append(line)

    def to_dict(self, with_logs: bool = True) -> dict:
        d = {
            "id": self.id, "kind": self.kind, "state": self.state,
            "progress": self.progress, "result": self.result, "error": self.error,
        }
        if with_logs:
            d["logs"] = list(self.logs)
        return d


def submit(kind: str, payload: dict, fn) -> Job:
    job = Job(kind, payload)

    def _run():
        try:
            job.result = fn(job)
            job.state = "done"
            job.progress = 100
        except Exception as e:
            job.state = "error"
            job.error = str(e)
            job.log(f"✗ 出错: {e}")

    with _lock:
        _jobs[job.id] = job
        # 清理 1 小时前的旧任务
        now = time.time()
        for jid in [j for j, job2 in _jobs.items() if now - job2.created > 3600]:
            _jobs.pop(jid, None)
    _pool.submit(_run)
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def all_jobs() -> list[Job]:
    return list(_jobs.values())
