from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock
from typing import Callable


class RequestCancelled(RuntimeError):
    """Raised when a user cancels an in-flight provider request."""


@dataclass(frozen=True)
class RequestToken:
    request_id: int
    cancelled: Event


class ManagedRequest:
    """Translate stream cancellation and release resources exactly once."""

    def __init__(
        self,
        request: object,
        finish: Callable[[], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        self._request = request
        self._finish = finish
        self._is_cancelled = is_cancelled
        self._close_lock = Lock()
        self._closed = False

    def __getattr__(self, name: str):
        return getattr(self._request, name)

    def _check_cancelled(self) -> None:
        if self._is_cancelled():
            raise RequestCancelled("Provider request cancelled.")

    def __iter__(self):
        try:
            self._check_cancelled()
            for chunk in self._request:
                self._check_cancelled()
                yield chunk
            # Some SDKs end the stream silently after transport.close().
            self._check_cancelled()
        except BaseException as error:
            try:
                self.close()
            except Exception:
                # Cleanup must not replace the original iteration exception.
                pass
            if (
                isinstance(error, Exception)
                and not isinstance(error, RequestCancelled)
                and self._is_cancelled()
            ):
                raise RequestCancelled("Provider request cancelled.") from error
            raise
        else:
            self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        try:
            close = getattr(self._request, "close", None)
            if callable(close):
                close()
        except Exception as error:
            if self._is_cancelled():
                raise RequestCancelled("Provider request cancelled.") from error
            raise
        finally:
            self._finish()


class RequestController:
    """Track cancellable provider calls without coupling to a specific SDK."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = 0
        self._active: dict[int, tuple[RequestToken, Callable[[], None]]] = {}

    def begin(self, cancel_callback: Callable[[], None]) -> RequestToken:
        with self._lock:
            self._next_id += 1
            token = RequestToken(self._next_id, Event())
            self._active[token.request_id] = (token, cancel_callback)
            return token

    def finish(self, token: RequestToken | None) -> None:
        if token is None:
            return
        with self._lock:
            self._active.pop(token.request_id, None)

    def cancel_all(self) -> int:
        with self._lock:
            active = [
                entry for entry in self._active.values()
                if not entry[0].cancelled.is_set()
            ]
            for token, _callback in active:
                token.cancelled.set()

        cancelled = 0
        for _token, callback in active:
            try:
                callback()
            except Exception:
                continue
            cancelled += 1
        return cancelled

    def is_cancelled(self, token: RequestToken | None) -> bool:
        return bool(token is not None and token.cancelled.is_set())

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
