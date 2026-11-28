"""Window for turning text into audio files (tray > Text to audio file…).

Three tabs: typed or pasted text, .txt files, and .srt subtitles (voice-over in sync
with the subtitle times)."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import text_to_audio as ta
from .. import tts
from ..config import APP_NAME
from .settings import _combo
from .transcribe_window import _show_in_folder

log = logging.getLogger(__name__)
TEXT_ROW = -1          # job id of the typed / pasted text
SRT_BASE = 1_000_000   # job ids of subtitle rows are SRT_BASE + row
SPEEDS = [(0.8, "Slower"), (0.9, "A little slower"), (1.0, "Normal"), (1.15, "A little faster"), (1.3, "Faster")]
TAB_TEXT, TAB_FILES, TAB_SRT = 0, 1, 2


def voice_summary(cfg) -> tuple[str, str]:
    """(which voices will read, a licence note or "")."""
    names, notes = [], []
    for lang in ("en", "tr"):
        if tts.engine_for(cfg, lang) == "neural":
            voice_id = tts.voice_for(cfg, lang)
            voice = next(v for v in tts.NEURAL_VOICES[lang] if v.id == voice_id)
            names.append(voice.label.split(" (")[0] + (" (English)" if lang == "en" else " (Turkish)"))
            if "non-commercial" in voice.licence or "not published" in voice.licence:
                notes.append(f"{voice.label.split(' (')[0]}: {voice.licence}")
        else:
            names.append(("English" if lang == "en" else "Turkish") + " Windows voice")
    text = "Voices: " + ", ".join(names) + ". Change them in Settings → Voice."
    note = ""
    if notes:
        note = ("Licence: " + "; ".join(notes) + ". For audio you publish or sell, choose voices "
                "marked CC0 or public domain in Settings → Voice (Fettah, LJ).")
    return text, note


def result_summary(result) -> str:
    text = f"Done ({result.duration / 60:.1f} min of audio)"
    if isinstance(result, ta.VoiceOverResult):
        if result.late:
            numbers = ", ".join(str(n) for n, _ in result.late[:5]) + ("…" if len(result.late) > 5 else "")
            worst = max(s for _, s in result.late)
            text += f"; {len(result.late)} line(s) too long, up to {worst:.1f} s late (lines {numbers})"
        elif result.faster:
            text += f"; {result.faster} line(s) read a little faster to fit"
    return text


class SpeechJob(QObject):
    itemStarted = Signal(int)
    itemProgress = Signal(int, int)       # job id, percent
    itemDone = Signal(int, object)        # job id, SpeechResult / VoiceOverResult
    itemFailed = Signal(int, str)
    status = Signal(str)                  # voice downloads
    allDone = Signal()
    previewDone = Signal(str)             # "" or an error message

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.cancel = threading.Event()

    def _voices(self, speed: float) -> ta.VoiceSet:
        return ta.VoiceSet(self.cfg, speed=speed, status=self.status.emit, stop=self.cancel)

    @Slot(object, str, float)
    def run(self, jobs, fmt: str, speed: float) -> None:
        """jobs: list of (job id, kind "text" | "file" | "srt", text or path, output path)."""
        self.cancel.clear()
        voices = self._voices(speed)
        for job_id, kind, payload, out_path in jobs:
            if self.cancel.is_set():
                self.itemFailed.emit(job_id, "Cancelled")
                continue
            self.itemStarted.emit(job_id)
            progress = lambda f, j=job_id: self.itemProgress.emit(j, int(f * 100))  # noqa: E731
            try:
                if kind == "srt":
                    result = ta.create_voice_over_file(payload, out_path, fmt, voices, speed, progress, self.cancel)
                else:
                    text = ta.read_text_file(payload) if kind == "file" else payload
                    result = ta.create_speech_file(text, out_path, fmt, voices, progress, self.cancel)
                self.itemDone.emit(job_id, result)
            except ta.Cancelled:
                self.itemFailed.emit(job_id, "Cancelled; nothing was written")
            except (ta.SpeechError, tts.SpeechError) as exc:
                self.itemFailed.emit(job_id, str(exc))
            except Exception as exc:
                log.exception("Creating the audio file failed")
                self.itemFailed.emit(job_id, f"Failed: {exc}")
        self.status.emit("")
        self.allDone.emit()

    @Slot(str, float)
    def preview(self, text: str, speed: float) -> None:
        self.cancel.clear()
        try:
            audio = ta.preview_audio(text, self._voices(speed))
            self.status.emit("")
            if len(audio):
                tts._play(audio, ta.OUTPUT_RATE, self.cancel)
            self.previewDone.emit("")
        except Exception as exc:
            log.warning("Preview failed: %s", exc)
            self.previewDone.emit(f"Could not play the preview: {exc}")


class FileList(QWidget):
    """A list of input files with status and Open buttons, plus Add / Clear list."""

    changed = Signal()

    def __init__(self, explanation: str, add_label: str, dialog_filter: str, base: int):
        super().__init__()
        self.base = base
        self.dialog_filter = dialog_filter
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["File", "Status", ""])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 0)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.add_button = QPushButton(add_label)
        self.add_button.clicked.connect(self.add_dialog)
        self.clear_button = QPushButton("Clear list")
        self.clear_button.setToolTip("Empty this list. Audio files already made are kept.")
        self.clear_button.clicked.connect(self.clear)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        label = QLabel(explanation)
        label.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

    def add_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", self.dialog_filter)
        self.add(paths)

    def add(self, paths) -> None:
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
            self.table.setItem(row, 1, QTableWidgetItem("Waiting"))
        self.changed.emit()

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.table.setColumnWidth(2, 0)
        self.changed.emit()

    def waiting(self) -> list[int]:
        return [r for r in range(self.table.rowCount()) if self.table.item(r, 1).text() == "Waiting"]

    def path(self, row: int) -> Path:
        return Path(self.table.item(row, 0).data(Qt.UserRole))

    def set_status(self, row: int, text: str) -> None:
        item = QTableWidgetItem(text)
        item.setToolTip(text)
        self.table.setItem(row, 1, item)

    def set_busy(self, busy: bool) -> None:
        self.add_button.setEnabled(not busy)
        self.clear_button.setEnabled(not busy)

    def show_result(self, row: int, result) -> None:
        self.set_status(row, result_summary(result))
        actions = QWidget()
        row_layout = QHBoxLayout(actions)
        row_layout.setContentsMargins(2, 0, 2, 0)
        play = QPushButton("Open audio")
        play.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.path))))
        folder = QPushButton("Open folder")
        folder.clicked.connect(lambda: _show_in_folder(result.path))
        row_layout.addWidget(play)
        row_layout.addWidget(folder)
        self.table.setCellWidget(row, 2, actions)
        self.table.resizeColumnToContents(1)
        self.table.setColumnWidth(2, actions.sizeHint().width() + 8)
        self.table.setRowHeight(row, max(self.table.rowHeight(row), actions.sizeHint().height()))


class SpeechWindow(QDialog):
    startJob = Signal(object, str, float)
    startPreview = Signal(str, float)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle(f"{APP_NAME}: text to audio file")
        self.resize(780, 540)
        self.setAcceptDrops(True)
        self._running = False
        self._busy_preview = False
        self._last_result: ta.SpeechResult | None = None

        intro = QLabel("Turn text into speech saved as an audio file. Turkish and English sentences are "
                       "each read in their own voice, so mixed texts work too.")
        intro.setWordWrap(True)

        # Tab 1: typed or pasted text
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Type or paste text here…")
        self.text.textChanged.connect(self._update_buttons)
        self.text_result = QLabel()
        self.open_audio = QPushButton("Open audio")
        self.open_audio_folder = QPushButton("Open folder")
        self.open_audio.clicked.connect(lambda: self._last_result and
                                        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_result.path))))
        self.open_audio_folder.clicked.connect(lambda: self._last_result and _show_in_folder(self._last_result.path))
        self.clear_text_button = QPushButton("Clear")
        self.clear_text_button.setToolTip("Empty the text box. Audio files already saved are kept.")
        self.clear_text_button.clicked.connect(self.clear_text)
        result_row = QHBoxLayout()
        result_row.addWidget(self.clear_text_button)
        result_row.addWidget(self.text_result, 1)
        result_row.addWidget(self.open_audio)
        result_row.addWidget(self.open_audio_folder)
        text_page = QWidget()
        text_layout = QVBoxLayout(text_page)
        text_layout.addWidget(self.text)
        text_layout.addLayout(result_row)

        # Tab 2: text files; Tab 3: subtitles
        self.files = FileList("Each text file becomes an audio file with the same name, next to it.",
                              "Add .txt files…", "Text files (*.txt *.md);;All files (*.*)", 0)
        self.srts = FileList(
            "Each subtitle line is spoken at its own time, giving a voice-over track as long as the "
            "subtitles (saved next to them as \"name voice-over\"). Add it to the video in a video editor, "
            f"starting at 0:00. Lines that are too long for their time are read up to "
            f"{int((ta.MAX_SPEEDUP - 1) * 100)} % faster; if they still do not fit, the next lines start a "
            "little later and the result says which lines.",
            "Add .srt files…", "Subtitles (*.srt);;All files (*.*)", SRT_BASE)
        for file_list in (self.files, self.srts):
            file_list.changed.connect(self._update_buttons)

        self.tabs = QTabWidget()
        self.tabs.addTab(text_page, "Type or paste")
        self.tabs.addTab(self.files, "Text files")
        self.tabs.addTab(self.srts, "Subtitles (.srt)")
        self.tabs.currentChanged.connect(self._update_buttons)

        # options
        self.format = _combo([("mp3", "MP3 (plays everywhere)"), ("m4a", "M4A (smaller)"), ("wav", "WAV (uncompressed)")],
                             cfg.get("speech_format", "mp3"))
        self.speed = _combo(SPEEDS, cfg.get("tts_speed", 1.0))
        options = QHBoxLayout()
        options.addWidget(QLabel("Format:"))
        options.addWidget(self.format)
        options.addSpacing(16)
        options.addWidget(QLabel("Speed:"))
        options.addWidget(self.speed)
        options.addStretch()
        voices, note = voice_summary(cfg)
        self.voices_label = QLabel(voices)
        self.note = QLabel(note)
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: gray;")
        self.note.setVisible(bool(note))

        self.status = QLabel()
        self.status.setStyleSheet("color: gray;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.listen_button = QPushButton("🔊 Listen")
        self.listen_button.setToolTip("Hear the first sentences before saving")
        self.listen_button.clicked.connect(self.listen)
        self.create_button = QPushButton("Create audio file")
        self.create_button.setDefault(True)
        self.create_button.clicked.connect(self.create)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.listen_button)
        buttons.addWidget(self.create_button)
        buttons.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(options)
        layout.addWidget(self.voices_label)
        layout.addWidget(self.note)
        layout.addWidget(self.progress)
        layout.addLayout(buttons)

        self.thread = QThread(self)
        self.job = SpeechJob(cfg)
        self.job.moveToThread(self.thread)
        self.startJob.connect(self.job.run)
        self.startPreview.connect(self.job.preview)
        self.job.itemStarted.connect(lambda job_id: self._set_status(job_id, "Creating… 0 %"))
        self.job.itemProgress.connect(self._on_progress)
        self.job.itemDone.connect(self._on_done)
        self.job.itemFailed.connect(self._on_failed)
        self.job.allDone.connect(self._on_all_done)
        self.job.status.connect(self.status.setText)
        self.job.previewDone.connect(self._on_preview_done)
        self.thread.start()
        self._show_text_result(None)

    # ---- compatibility for the text-files tab ------------------------------------
    @property
    def table(self) -> QTableWidget:
        return self.files.table

    def add_files(self, paths) -> None:
        """Route dropped or added files: .srt to the subtitle tab, others to text files."""
        srt = [p for p in paths if str(p).lower().endswith(".srt")]
        text = [p for p in paths if not str(p).lower().endswith(".srt")]
        if text:
            self.files.add(text)
            self.tabs.setCurrentIndex(TAB_FILES)
        if srt:
            self.srts.add(srt)
            self.tabs.setCurrentIndex(TAB_SRT)

    def clear_list(self) -> None:
        if not self._running:
            self.files.clear()
            self.progress.setValue(0)

    # ---- input ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def clear_text(self) -> None:
        """Empty the text box and the "Saved" line (not while working); files stay."""
        if self._running:
            return
        self.text.clear()
        self._show_text_result(None)
        self.status.setText("")
        self.progress.setValue(0)
        self._update_buttons()

    def _list_for(self, job_id: int) -> tuple[FileList, int]:
        return (self.srts, job_id - SRT_BASE) if job_id >= SRT_BASE else (self.files, job_id)

    def _update_buttons(self) -> None:
        if not hasattr(self, "cancel_button"):
            return
        idle = not self._running and not self._busy_preview
        tab = self.tabs.currentIndex()
        has_text = bool(self.text.toPlainText().strip())
        ready = {TAB_TEXT: has_text, TAB_FILES: bool(self.files.waiting()), TAB_SRT: bool(self.srts.waiting())}[tab]
        self.create_button.setEnabled(idle and ready)
        self.create_button.setText("Create voice-over" if tab == TAB_SRT else "Create audio file")
        self.listen_button.setEnabled(idle and tab == TAB_TEXT and has_text)
        self.listen_button.setVisible(tab == TAB_TEXT)
        for widget in (self.format, self.speed, self.text):
            widget.setEnabled(not self._running)
        for file_list in (self.files, self.srts):
            file_list.set_busy(self._running)
        self.clear_text_button.setEnabled(not self._running and (has_text or self._last_result is not None))
        self.cancel_button.setEnabled(self._running or self._busy_preview)

    # ---- actions ----------------------------------------------------------------
    def listen(self) -> None:
        text = self.text.toPlainText().strip()
        if not text or self._running or self._busy_preview:
            return
        self._busy_preview = True
        self.status.setText("Playing the first sentences…")
        self._update_buttons()
        self.startPreview.emit(text, float(self.speed.currentData()))

    def _on_preview_done(self, error: str) -> None:
        self._busy_preview = False
        self.status.setText(error)
        self._update_buttons()

    def create(self) -> None:
        if self._running:
            return
        fmt = self.format.currentData()
        extension = ta.FORMATS[fmt]
        tab = self.tabs.currentIndex()
        if tab == TAB_TEXT:
            text = self.text.toPlainText().strip()
            if not text:
                return
            folder = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            suggested = ta.free_output_path(Path(folder) / "TexTurEng speech", extension)
            path, _ = QFileDialog.getSaveFileName(self, "Save audio file as", str(suggested),
                                                  f"{fmt.upper()} audio (*{extension})")
            if not path:
                return
            jobs = [(TEXT_ROW, "text", text, Path(path).with_suffix(extension))]
            self._show_text_result(None)
        elif tab == TAB_FILES:
            jobs = [(row, "file", self.files.path(row), ta.free_output_path(self.files.path(row), extension))
                    for row in self.files.waiting()]
        else:
            jobs = [(SRT_BASE + row, "srt", self.srts.path(row), ta.voice_over_path(self.srts.path(row), extension))
                    for row in self.srts.waiting()]
        if not jobs:
            return
        self.cfg["speech_format"] = fmt
        self.cfg.save()
        self._running = True
        self._done_count = 0
        self._job_count = len(jobs)
        self.progress.setValue(0)
        self._update_buttons()
        self.startJob.emit(jobs, fmt, float(self.speed.currentData()))

    def cancel(self) -> None:
        self.job.cancel.set()
        self.cancel_button.setEnabled(False)

    # ---- job events --------------------------------------------------------------
    def _set_status(self, job_id: int, text: str) -> None:
        if job_id == TEXT_ROW:
            self.status.setText(text)
        else:
            file_list, row = self._list_for(job_id)
            file_list.set_status(row, text)

    def _on_progress(self, job_id: int, percent: int) -> None:
        self._set_status(job_id, f"Creating… {percent} %")
        self.progress.setValue(int((self._done_count * 100 + percent) / max(1, self._job_count)))

    def _on_done(self, job_id: int, result) -> None:
        self._done_count += 1
        self.progress.setValue(int(self._done_count * 100 / max(1, self._job_count)))
        if job_id == TEXT_ROW:
            self.status.setText("")
            self._show_text_result(result)
            return
        file_list, row = self._list_for(job_id)
        file_list.show_result(row, result)

    def _on_failed(self, job_id: int, message: str) -> None:
        self._done_count += 1
        self._set_status(job_id, message)

    def _on_all_done(self) -> None:
        self._running = False
        self.progress.setValue(100 if self._done_count else 0)
        self._update_buttons()

    def _show_text_result(self, result) -> None:
        self._last_result = result
        self.text_result.setText("" if result is None else
                                 f"Saved: {result.path.name} ({result.duration / 60:.1f} min of audio)")
        self.open_audio.setVisible(result is not None)
        self.open_audio_folder.setVisible(result is not None)
        self._update_buttons()

    # ---- closing ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._running

    def closeEvent(self, event) -> None:
        if self._busy_preview:
            self.job.cancel.set()
        if self._running:        # keeps working in the background; the tray brings it back
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)

    def shutdown(self) -> None:
        self.job.cancel.set()
        self.thread.quit()
        self.thread.wait(30_000)
