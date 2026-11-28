"""`python -m textureng` starts the tray app.
`python -m textureng --wav file.wav [--profile email]` runs the pipeline on a file."""
from __future__ import annotations

import argparse
import sys


def run_file(args) -> int:
    import logging

    from .audio import load_wav
    from .config import Config
    from .context import AppInfo
    from .pipeline import run_pipeline
    from .stt import make_transcriber

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "huggingface_hub", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    cfg = Config()
    if args.lang:
        cfg["language"] = args.lang
    if args.no_cleanup:
        cfg["cleanup_enabled"] = False
    transcriber = make_transcriber(cfg)
    transcriber.load()
    audio = load_wav(args.wav)
    if args.translate:
        cfg["translate_target"] = args.translate
    result = run_pipeline(audio, AppInfo(), cfg, transcriber, profile_key=args.profile, translate=bool(args.translate))
    print(f"language : {result.language}")
    print(f"profile  : {result.profile}")
    if result.translated_to:
        print(f"translate: {result.language} -> {result.translated_to}")
    print(f"timing   : stt {result.stt_seconds:.2f}s, cleanup {result.cleanup_seconds:.2f}s")
    print(f"raw      : {result.raw}")
    print(f"polished : {result.text}")
    if result.warning:
        print(f"warning  : {result.warning}")
    return 0


def selftest(out_path: str) -> int:
    """Check that a packaged build has everything it needs; writes a JSON report."""
    import json

    report: dict = {}

    def check(name, func):
        try:
            report[name] = func()
        except Exception as exc:
            report[name] = f"FAILED: {type(exc).__name__}: {exc}"

    def vad_assets():
        import os

        from faster_whisper.utils import get_assets_path

        return sorted(os.listdir(get_assets_path()))

    def tls():
        import httpx

        return httpx.get("https://api.groq.com/openai/v1/models", timeout=15).status_code  # 401 = reachable

    def ui():
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from .config import Config
        from .ui.overlay import Overlay  # noqa: F401
        from .ui.settings import SettingsWindow, _startup_command
        from .ui.translation_popup import TranslationPopup
        from .ui.tray import Tray  # noqa: F401
        from . import main as _main  # noqa: F401  (the tray app itself)

        TranslationPopup()
        from .ui.welcome import WelcomeDialog, has_local_gpu

        cfg = Config()
        WelcomeDialog(cfg), SettingsWindow(cfg)
        del app
        return {"local_gpu": has_local_gpu(), "startup_command": _startup_command()}

    check("frozen", lambda: bool(getattr(sys, "frozen", False)))
    check("keyring", lambda: type(__import__("keyring").get_keyring()).__name__)
    check("microphones", lambda: __import__("textureng.audio", fromlist=["x"]).list_input_devices())
    check("ctranslate2", lambda: __import__("ctranslate2").__version__)
    check("vad_assets", vad_assets)
    check("pynput", lambda: bool(__import__("pynput.keyboard", fromlist=["x"]).Listener))
    check("cloud_reachable_status", tls)
    def media_decoding():
        """Write a 1-second .m4a with PyAV and read it back like a user's recording."""
        import os
        import tempfile

        import av
        import numpy as np

        from .transcribe_file import load_media

        path = os.path.join(tempfile.mkdtemp(), "selftest.m4a")
        container = av.open(path, "w")
        stream = container.add_stream("aac", rate=16000)
        stream.layout = "mono"
        tone = (np.sin(np.linspace(0, 2000, 16000)) * 8000).astype(np.int16).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(tone, format="s16", layout="mono")
        frame.rate = 16000
        for packet in list(stream.encode(frame)) + list(stream.encode(None)):
            container.mux(packet)
        container.close()
        seconds = len(load_media(path)) / 16000
        os.remove(path)
        # MP3 saving, used by Text to audio file
        from pathlib import Path

        from .text_to_audio import write_audio

        mp3 = Path(tempfile.mkdtemp()) / "selftest.mp3"
        write_audio(np.sin(np.linspace(0, 2000, 22050)).astype(np.float32) * 0.3, mp3, "mp3")
        mp3_seconds = len(load_media(mp3)) / 16000
        mp3.unlink()
        return f"m4a ok ({seconds:.1f}s), mp3 ok ({mp3_seconds:.1f}s)"

    check("media_decoding", media_decoding)
    check("read_aloud", lambda: {
        "natural_voices": __import__("textureng.tts", fromlist=["x"]).neural_available(),
        "windows_voice_languages": sorted(__import__("textureng.tts", fromlist=["x"]).WindowsEngine.available_languages()),
    })
    check("ui", ui)
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="textureng")
    parser.add_argument("--selftest", metavar="REPORT.json", help=argparse.SUPPRESS)
    parser.add_argument("--wav", help="run the pipeline on a WAV file and print the result")
    parser.add_argument("--profile", default="default", help="email | chat | code | document | default")
    parser.add_argument("--lang", choices=["auto", "en", "tr"])
    parser.add_argument("--no-cleanup", action="store_true", help="skip the Ollama cleanup step")
    parser.add_argument("--translate", choices=["auto", "en", "tr"], help="translate (auto = the other language)")
    args = parser.parse_args()
    if args.selftest:
        return selftest(args.selftest)
    if args.wav:
        return run_file(args)
    from .main import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
