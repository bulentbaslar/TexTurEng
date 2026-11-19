"""Window listing past dictations; double-click or the button copies the text."""
from __future__ import annotations

import time

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..config import APP_NAME


class HistoryWindow(QDialog):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.setWindowTitle(f"{APP_NAME} history")
        self.resize(820, 480)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "App", "Pasted text", "What you said"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self.copy_selected)

        copy_button = QPushButton("Copy polished text")
        copy_button.clicked.connect(self.copy_selected)
        clear_button = QPushButton("Clear history")
        clear_button.clicked.connect(self.clear)
        buttons = QHBoxLayout()
        buttons.addWidget(copy_button)
        buttons.addStretch()
        buttons.addWidget(clear_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        rows = self.history.recent()
        self.table.setRowCount(len(rows))
        for r, (ts, app, _profile, lang, raw, text, translated_to) in enumerate(rows):
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
            if translated_to:
                app = f"{app}  {lang.upper()} → {translated_to.upper()}"
            for c, value in enumerate((stamp, app, text, raw)):
                self.table.setItem(r, c, QTableWidgetItem(value))
        self.table.resizeRowsToContents()

    def copy_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            QGuiApplication.clipboard().setText(self.table.item(row, 2).text())

    def clear(self) -> None:
        answer = QMessageBox.question(self, APP_NAME, "Delete all saved dictations? This cannot be undone.")
        if answer == QMessageBox.Yes:
            self.history.clear()
            self.reload()
