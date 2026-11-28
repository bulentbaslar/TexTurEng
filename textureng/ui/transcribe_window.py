"""Window for transcribing recordings into .txt / .srt files (tray > Transcribe audio files…)."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import transcribe_file as tf
from ..config import APP_NAME
from .settings import _combo

log = logging.getLogger(__name__)
FILTER = "Audio and video ({});;All files (*.*)".format(" ".join("*" + e for e in tf.AUDIO_EXTENSIONS))


class FileJob(QObject):
    """Transcribes the queued files one after another on a background thread."""

    fileStarted = Signal(int)
    fileProgress = Signal(int, int)          # row, percent
    fileDone = Signal(int, object)           # row, transcribe_file.FileResult
    fileFailed = Signal(int, str)
    allDone = Signal()

    def __init__(self, transcriber_source, cfg):
        super().__init__()
        self._transcriber_source = transcriber_source   # callable returning a loaded transcriber
        self.cfg = cfg
        self.cancel = threading.Event()

    @Slot(object, str, bool)
    def run(self, rows_and_paths, language: str, make_srt: bool) -> None:
        self.cancel.clear()
        try:
            transcriber = self._transcriber_source()
        except Exception as exc:
            for row, _ in rows_and_paths:
                self.fileFailed.emit(row, f"Speech engine not available: {exc}")
            self.allDone.emit()
            return
        for row, path in rows_and_paths:
            if self.cancel.is_set():
                self.fileFailed.emit(row, "Cancelled")
                continue
            self.fileStarted.emit(row)
            try:
                result = tf.transcribe_file(
                    path, transcriber, language=language, make_srt=make_srt,
                    terms=list(self.cfg["dictionary"]),
                    progress=lambda f, r=row: self.fileProgress.emit(r, int(f * 100)),
                    cancel=self.cancel,
                )
                self.fileDone.emit(row, result)
            except tf.Cancelled:
                self.fileFailed.emit(row, "Cancelled; nothing was written")
            except tf.TranscribeError as exc:
                self.fileFailed.emit(row, str(exc))
            except Exception as exc:
                log.exception("File transcription failed")
                self.fileFailed.emit(row, f"Failed: {exc}")
        self.allDone.emit()


class TranscribeWindow(QDialog):
    startJob = Signal(object, str, bool)

    def __init__(self, cfg, transcriber_source, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(f"{APP_NAME}: transcribe audio files")
        self.resize(760, 440)
        self.setAcceptDrops(True)
        self._running = False
        self._results: dict[int, tf.FileResult] = {}

        intro = QLabel(
            "Turn recordings into text. Add audio or video files (m4a, mp3, wav, mp4…) or drag them "
            "here. The text (.txt) and subtitles (.srt) are saved next to each recording."
        )
        intro.setWordWrap(True)

        self.language = _combo(
            [("auto", "Auto: Turkish, English or both mixed"), ("tr", "Turkish only"), ("en", "English only")],
            cfg.get("transcribe_language", "auto"),
        )
        self.make_srt = QCheckBox("Also create .srt subtitles")
        self.make_srt.setChecked(bool(cfg.get("transcribe_srt", True)))
        options = QHBoxLayout()
        options.addWidget(QLabel("Language:"))
        options.addWidget(self.language)
        options.addSpacing(16)
        options.addWidget(self.make_srt)
        options.addStretch()

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Recording", "Status", ""])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 0)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        if cfg["stt_engine"] == "cloud":
            self.note.setText("Cloud speech recognition detects one language per 10 minutes, so recordings that "
                              "switch between Turkish and English are more precise with local speech recognition.")

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.add_button = QPushButton("Add files…")
        self.add_button.clicked.connect(self.add_files_dialog)
        self.start_button = QPushButton("Start")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        self.clear_button = QPushButton("Clear list")
        self.clear_button.setToolTip("Empty this list. The .txt and .srt files on disk are kept.")
        self.clear_button.clicked.connect(self.clear_list)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(options)
        layout.addWidget(self.table)
        layout.addWidget(self.note)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)

        self.thread = QThread(self)
        self.job = FileJob(transcriber_source, cfg)
        self.job.moveToThread(self.thread)
        self.startJob.connect(self.job.run)
        self.job.fileStarted.connect(lambda row: self._set_status(row, "Transcribing… 0 %"))
        self.job.fileProgress.connect(self._on_progress)
        self.job.fileDone.connect(self._on_done)
        self.job.fileFailed.connect(self._on_failed)
        self.job.allDone.connect(self._on_all_done)
        self.thread.start()

    # ---- adding files --------------------------------------------------------
    def add_files_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose recordings", "", FILTER)
        self.add_files(paths)

    def add_files(self, paths) -> None:
        for path in paths:
            path = str(Path(path))
            if any(self.table.item(r, 0).data(Qt.UserRole) == path for r in range(self.table.rowCount())):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(Path(path).name)
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.table.setItem(row, 0, item)
            self._set_status(row, "Waiting")
        self.start_button.setEnabled(not self._running and bool(self._waiting_rows()))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def clear_list(self) -> None:
        """Empty the list (not while files are being transcribed); files on disk stay."""
        if self._running:
            return
        self.table.setRowCount(0)
        self.table.setColumnWidth(2, 0)
        self._results.clear()
        self.progress.setValue(0)
        self.start_button.setEnabled(False)

    # ---- running ---------------------------------------------------------------
    def _waiting_rows(self) -> list[int]:
        return [r for r in range(self.table.rowCount()) if self.table.item(r, 1).text() == "Waiting"]

    def start(self) -> None:
        rows = self._waiting_rows()
        if not rows or self._running:
            return
        self.cfg["transcribe_language"] = self.language.currentData()
        self.cfg["transcribe_srt"] = self.make_srt.isChecked()
        self.cfg.save()
        self._running = True
        self._queue = rows
        self._finished = 0
        self.progress.setValue(0)
        for widget in (self.start_button, self.add_button, self.clear_button, self.language, self.make_srt):
            widget.setEnabled(False)
        self.cancel_button.setEnabled(True)
        jobs = [(r, self.table.item(r, 0).data(Qt.UserRole)) for r in rows]
        self.startJob.emit(jobs, self.language.currentData(), self.make_srt.isChecked())

    def cancel(self) -> None:
        self.job.cancel.set()
        self.cancel_button.setEnabled(False)

    def _overall(self, row: int, percent: int) -> None:
        if self._running and self._queue:
            position = self._queue.index(row) if row in self._queue else self._finished
            self.progress.setValue(int((position * 100 + percent) / len(self._queue)))

    def _on_progress(self, row: int, percent: int) -> None:
        self._set_status(row, f"Transcribing… {percent} %")
        self._overall(row, percent)

    def _on_done(self, row: int, result) -> None:
        self._finished += 1
        self._results[row] = result
        minutes = result.duration / 60
        languages = " + ".join({"tr": "Turkish", "en": "English"}.get(l, l) for l in result.languages)
        self._set_status(row, f"Done ({minutes:.1f} min, {languages})")
        self._overall(row, 100)
        actions = QWidget()
        row_layout = QHBoxLayout(actions)
        row_layout.setContentsMargins(2, 0, 2, 0)
        open_text = QPushButton("Open text")
        open_text.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.txt_path))))
        open_folder = QPushButton("Open folder")
        open_folder.clicked.connect(lambda: _show_in_folder(result.txt_path))
        row_layout.addWidget(open_text)
        row_layout.addWidget(open_folder)
        self.table.setCellWidget(row, 2, actions)
        self.table.resizeColumnToContents(1)
        self.table.setColumnWidth(2, actions.sizeHint().width() + 8)
        self.table.setRowHeight(row, max(self.table.rowHeight(row), actions.sizeHint().height()))

    def _on_failed(self, row: int, message: str) -> None:
        self._finished += 1
        self._set_status(row, message)
        self._overall(row, 100)

    def _on_all_done(self) -> None:
        self._running = False
        self.progress.setValue(100)
        for widget in (self.add_button, self.clear_button, self.language, self.make_srt):
            widget.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.start_button.setEnabled(bool(self._waiting_rows()))

    def _set_status(self, row: int, text: str) -> None:
        self.table.setItem(row, 1, QTableWidgetItem(text))

    @property
    def running(self) -> bool:
        return self._running

    def closeEvent(self, event) -> None:
        # Closing the window while files are being transcribed only hides it; the work
        # continues and the tray menu brings the same window back.
        if self._running:
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Called when the app quits: stop after the current chunk, write nothing partial."""
        self.job.cancel.set()
        self.thread.quit()
        self.thread.wait(30_000)


def _show_in_folder(path: Path) -> None:
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
