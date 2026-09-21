"""공통 유틸: 시각, 로깅, 진단 누적기."""

from __future__ import annotations

import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


def setup_logging(level: str = "INFO") -> None:
    """structlog JSON 로그를 설정한다. 필수 필드는 layer, equip, event."""
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, level.upper(), logging.INFO), format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(layer: str) -> Any:
    """지연 프록시를 돌려준다. setup_logging 이후 설정이 적용된다."""
    return structlog.get_logger(layer=layer)


STATUS_OK, STATUS_DELAY, STATUS_DOWN, STATUS_ERROR = 0, 1, 2, 3
STATUS_NAMES = {0: "OK", 1: "DELAY", 2: "DOWN", 3: "ERROR"}


@dataclass
class Frame:
    ts: str
    tx: str
    rx: str
    result: str
    rtt_ms: float | None


@dataclass
class Diag:
    """장비 한 대의 통신 진단 누적. 상태 판정 규칙은 ARCHITECTURE 6장.

    attempts: 요청 1건 단위(재시도 포함) — 오류 비율(ERROR) 판정용
    polls: 폴링 1회 단위(재시도 후 최종 결과) — 성공률·연속 실패(DOWN) 판정용
    """

    delay_ms: float
    attempts: deque[tuple[float, bool, float | None, str | None]] = field(default_factory=lambda: deque(maxlen=6000))
    polls: deque[tuple[float, bool]] = field(default_factory=lambda: deque(maxlen=4000))
    frames: deque[Frame] = field(default_factory=lambda: deque(maxlen=50))
    consecutive_fail: int = 0
    last_ok_iso: str | None = None
    counter: int = 0
    errors: dict[str, int] = field(default_factory=lambda: {"timeout": 0, "crc": 0, "exception": 0, "frame": 0})
    ever_ok: bool = False

    def attempt(self, ok: bool, rtt_ms: float | None, err: str | None) -> None:
        self.attempts.append((time.monotonic(), ok, rtt_ms, err))
        if err:
            self.errors[err] = self.errors.get(err, 0) + 1

    def poll(self, ok: bool) -> None:
        self.polls.append((time.monotonic(), ok))
        if ok:
            self.consecutive_fail = 0
            self.last_ok_iso = iso(now_kst())
            self.counter = (self.counter + 1) & 0xFFFF or 1
            self.ever_ok = True
        else:
            self.consecutive_fail += 1

    def add_frame(self, tx: bytes | str, rx: bytes | str, result: str, rtt_ms: float | None) -> None:
        def fmt(b: bytes | str) -> str:
            return b.hex(" ").upper() if isinstance(b, bytes) else b

        self.frames.append(Frame(iso(now_kst()), fmt(tx), fmt(rx), result, rtt_ms))

    def success_rate(self, seconds: float) -> float | None:
        cut = time.monotonic() - seconds
        w = [p for p in self.polls if p[0] >= cut]
        return None if not w else sum(1 for p in w if p[1]) / len(w)

    def avg_rtt(self, n: int = 5) -> float | None:
        rtts = [a[2] for a in list(self.attempts)[-n:] if a[1] and a[2] is not None]
        return sum(rtts) / len(rtts) if rtts else None

    def status(self) -> int:
        """0 OK / 1 DELAY / 2 DOWN / 3 ERROR."""
        if not self.ever_ok or self.consecutive_fail >= 3:
            return STATUS_DOWN
        cut = time.monotonic() - 60
        w = [a for a in self.attempts if a[0] >= cut]
        bad = sum(1 for a in w if a[3] in ("crc", "exception", "frame"))
        if w and bad / len(w) > 0.10:
            return STATUS_ERROR
        avg = self.avg_rtt()
        if avg is not None and avg > self.delay_ms:
            return STATUS_DELAY
        return STATUS_OK

    def summary(self) -> dict[str, Any]:
        avg = self.avg_rtt(20)
        cut = time.monotonic() - 60
        return {
            "status": STATUS_NAMES[self.status()],
            "success_1m": self.success_rate(60),
            "success_1h": self.success_rate(3600),
            "avg_rtt_ms": round(avg, 1) if avg is not None else None,
            "last_ok": self.last_ok_iso,
            "consecutive_fail": self.consecutive_fail,
            "errors": dict(self.errors),
            "polls_1m": sum(1 for p in self.polls if p[0] >= cut),
        }
