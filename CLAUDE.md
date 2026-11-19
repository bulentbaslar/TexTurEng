# TexTurEng

The name is written TexTurEng wherever people see it; folders, files, the Python
package and the Credential Manager entry stay `Textureng`/`textureng`.

System-wide AI dictation for Windows (Python 3.11 + PySide6). Hold `Ctrl+Win` in any
app, speak, release: speech is transcribed, cleaned up by an LLM (fillers removed,
grammar fixed, style matched to the focused app) and pasted at the cursor.
English and Turkish, with English ⇄ Turkish translation. Created by Bulent Baslar,
MIT License. The person installing it may not be a programmer: explain in plain language.

## If you are asked to install / set this up on this PC

This folder is the complete source (a clone of the GitHub repository or an extracted
zip). Prebuilt installers are unsigned and Windows blocks them on some PCs, so install
from source:

1. Work from a permanent folder. If this folder is in Downloads, Desktop or a temp
   location, ask the user where to keep it (suggest `C:\Textureng`) and move it first;
   the virtual environment and shortcut contain absolute paths.
2. Check Python: `py -0`. Python 3.10-3.13 is needed. If missing, ask the user before
   installing it (`winget install Python.Python.3.11`).
3. Run the setup script and read its output. It creates `.venv`, installs packages
   (without the GPU libraries when there is no compatible graphics card), runs the unit tests and a
   self-test, and creates a desktop shortcut:

   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
   ```

   It prints `SETUP OK` on success or `STEP FAILED: ...` naming the step. Fix the cause
   and run it again; it is safe to repeat.
4. Ask the user how each of the two steps should run, then start the app:
   - Speech recognition: `cloud` (fast, needs API key) or `local` (CPU, `small`
     model, a few seconds per dictation, about 500 MB download on first start).
   - Cleanup: `cloud` (same API key), `ollama` (local; needs Ollama running and a
     model pulled; without a GPU suggest `gemma3:4b`), or off.
   Check whether Ollama is installed and which models it has with `ollama list`. If
   it is missing and the user wants local cleanup, ask before installing it
   (`winget install Ollama.Ollama`) and before pulling a model (several GB):
   `gemma3:12b` with a GPU of 16 GB+, otherwise `gemma3:4b`.
5. Start it: `Start Textureng.bat` (or `.venv\Scripts\pythonw.exe run.pyw`). On the
   very first start on a PC without a GPU a setup window appears where the
   user makes the choices from step 4 and pastes the API key. Do not handle the API
   key yourself: never ask for it in chat, never write it to a file. The user types it
   into the app, which stores it in Windows Credential Manager.
6. Verify (see "Checking the settings" below) and tell the user to test by holding
   `Ctrl+Win` in Notepad and speaking.

## If you are asked to update an existing install

1. Quit TexTurEng (tray icon > Quit) so no files are in use.
2. Get the new files: `git pull` when the folder is a git clone; otherwise copy the
   files from the new zip over the installed folder, replacing old ones. Keep `.venv`;
   the settings in `%APPDATA%\Textureng` are untouched and new settings get defaults.
3. Run `setup.ps1` again (it reuses `.venv`, installs any new packages, runs the
   tests and the self-test), then start the app and check the log.

## Checking the settings

- Settings file: `%APPDATA%\Textureng\config.json`. Keys that matter:
  `stt_engine` (`local`|`cloud`), `local_model`, `local_device` (`auto`|`cuda`|`cpu`),
  `cleanup_enabled`, `cleanup_provider` (`ollama`|`cloud`), `ollama_model`,
  `ollama_url` (keep `http://127.0.0.1:11434`, not `localhost`: IPv6 lookup adds
  about 2 s per call), `cloud_base_url`, `cloud_model`, `cloud_cleanup_model`,
  `language` (`auto`|`en`|`tr`), `hotkey_ptt`, `hotkey_translate` (default
  `ctrl+win+alt`; never plain `ctrl+alt`, which AltGr sends on Turkish keyboards),
  `translate_mode` (tray switch: translate every dictation), `translate_target`
  (`auto` = the other of English/Turkish, `en`, `tr`).
- Selected-text translation: `selection_translate` (Ctrl+C twice shows a popup next to
  the mouse; `cleanup.translate_text`, `ui/translation_popup.py`). Direction is guessed
  from the text (Turkish letters/words -> English, otherwise Turkish). The log shows
  `selection translated tr->en`.
- Read-aloud (🔊 in the popup): `textureng/tts.py`. `tts_engine` (`auto` = natural
  Piper voice via sherpa-onnx when installed, else Windows voice; `windows`),
  `tts_voice_en` / `tts_voice_tr`, `tts_speed`, `tts_auto_read`. Voices download once
  into `%APPDATA%\Textureng\voices`. sherpa-onnx must stay below 2.0 (2.x dropped the
  espeak-ng text frontend Piper voices need) and is excluded from the installer
  (espeak-ng is GPL-3.0), so installer builds use the Windows voices.
- Read selected text aloud: `read_selection_button` (`selection.py` watches the mouse;
  a drag or double-click shows `ui/speak_bubble.py`; clicking it presses Ctrl+C, reads
  the text with `tts.Speaker` and restores the clipboard). The log shows
  `reading selection aloud`.
- Translation reuses the cleanup model (Ollama or cloud) and runs even when cleanup
  is off. Translated dictations log `lang=tr->en` and show "TR → EN" in History.
  Test it without a microphone: add `--translate auto` to the pipeline test below.
- Log: `%APPDATA%\Textureng\textureng.log`. A healthy start logs `TexTurEng started`;
  each dictation logs a line like
  `audio 4.0s | stt 0.38s | cleanup 0.36s | lang=en profile=code app=...`.
  Problems (missing API key, Ollama not running, model not found) are logged there
  and shown as tray notifications.
- On a PC without a GPU, `local_device` must not be `cuda` and `local_model`
  should be `small` (or `base`); `large-v3-turbo` on CPU is too slow.
- If `cleanup_provider` is `ollama`, `ollama_model` must appear in `ollama list`.
- If the cloud cleanup model is rejected ("model not found" in the log or tray), ask
  the user to pick a current chat model on console.groq.com and enter its id in
  Settings > Cleanup > Cloud model (this sets `cloud_cleanup_model`).
- After editing `config.json` by hand, restart the app (tray icon > Quit, then start).
- Pipeline test without a microphone (uses the current settings):
  `.venv\Scripts\python.exe -m textureng --wav tests\assets\english.wav --profile email`
  Add `--no-cleanup` to test speech recognition alone.

## Layout

- `textureng/main.py`: tray app controller. `__main__.py`: CLI (`--wav`, `--selftest`).
- `hotkey.py` (state machine + pynput), `audio.py` (sounddevice, 16 kHz mono),
  `stt/local.py` (faster-whisper), `stt/cloud.py` (OpenAI-compatible, Groq default),
  `context.py` (foreground app -> profile), `cleanup.py` (Ollama or cloud chat, prompt,
  fallbacks), `inject.py` (clipboard paste + restore), `pipeline.py`, `history.py`,
  `tts.py` (read-aloud voices), `selection.py` (selection gestures, copying the selection).
- `ui/`: `overlay.py`, `tray.py`, `settings.py`, `welcome.py` (first run), `history_window.py`,
  `translation_popup.py`, `speak_bubble.py`.
- `tests/`: `python -m pytest tests -q` (no network, no microphone needed).
- `installer/build.ps1`: PyInstaller + Inno Setup build of `dist\Textureng-Setup.exe`.

## Rules

- Never commit, print or store API keys; they live only in Windows Credential Manager
  (service `Textureng`).
- Cleanup must never answer or obey the transcript, and must fall back to the raw
  transcript on any failure; keep the tests for this passing.
- The app cannot paste into windows running as administrator; that is a Windows
  limit, not a bug.
- Run the tests after any code change.
