from __future__ import annotations

import inspect
import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

log = logging.getLogger(__name__)


class TaskSignals(QObject):
    progress = Signal(int, str)
    status = Signal(str)
    done = Signal(object)
    error = Signal(str)


class Task(QRunnable):
    """Runs a callable on the Qt thread pool and reports results safely.

    Any ``progress`` or ``status`` keyword the callable accepts is wired to the
    matching signal so worker threads never touch widgets directly.
    """

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.setAutoDelete(True)
        self._accepts_progress, self._accepts_status = self._inspect_callable()

    def _inspect_callable(self) -> tuple[bool, bool]:
        """Work out once whether the callable accepts progress/status kwargs."""
        try:
            parameters = inspect.signature(self.function).parameters
        except (TypeError, ValueError):
            return False, False
        accepts_any = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        return (
            accepts_any or "progress" in parameters,
            accepts_any or "status" in parameters,
        )

    @Slot()
    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            if self._accepts_progress and "progress" not in kwargs:
                kwargs["progress"] = self._emit_progress
            if self._accepts_status and "status" not in kwargs:
                kwargs["status"] = self._emit_status
            result = self.function(*self.args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - reported to the UI thread
            log.error("Background task failed: %s\n%s", exc, traceback.format_exc())
            self._safe_emit(self.signals.error, str(exc) or exc.__class__.__name__)
            return
        self._safe_emit(self.signals.done, result)

    def _emit_progress(self, value: int, text: str = "") -> None:
        self._safe_emit(self.signals.progress, value, text)

    def _emit_status(self, text: str) -> None:
        self._safe_emit(self.signals.status, text)

    @staticmethod
    def _safe_emit(signal, *args: Any) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            # The application is shutting down and the receiver is gone.
            pass
