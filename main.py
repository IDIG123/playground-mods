#!/usr/bin/env python3
"""Playground Mods — a native desktop catalogue for People Playground mods."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from playground_mods import __version__
from playground_mods.paths import APP_NAME, ensure_dirs, setup_logging
from playground_mods.ui.theme import COLORS, STYLESHEET
from playground_mods.ui.window import MainWindow

log = logging.getLogger(__name__)


def _app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(COLORS["lime"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)
    font = QFont("Noto Sans Mono")
    font.setPixelSize(34)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#141b0d"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "▰")
    painter.end()
    return QIcon(pixmap)


def _install_excepthook() -> None:
    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.error(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        try:
            QMessageBox.critical(
                None,
                "Playground Mods",
                f"Something went wrong:\n\n{exc_value}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def main() -> int:
    ensure_dirs()
    setup_logging()
    log.info("Playground Mods %s starting", __version__)

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName("Playground Mods")
    QApplication.setDesktopFileName("playground-mods")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setWindowIcon(_app_icon())
    app.setStyleSheet(STYLESHEET)
    _install_excepthook()

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    code = app.exec()
    # Give any in-flight background task a moment to finish cleanly.
    QThreadPool.globalInstance().waitForDone(6000)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
