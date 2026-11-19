# TexTurEng

**AI dictation and Turkish ⇄ English translation for Windows.**

Hold a hotkey in any app, speak naturally, and polished text is pasted where your
cursor is. TexTurEng removes filler words ("um", "uh", "şey", "yani"), applies your
self-corrections ("Tuesday, no wait, Wednesday" → "Wednesday"), fixes grammar and
punctuation, and formats the text for the app you are in. Hold one extra key and it
translates as well: speak Turkish and get English, or speak English and get Turkish.

Everything can run on your own PC (private, free, works offline), or in the cloud for
computers without a strong graphics card.

Created by **Bulent Baslar** · MIT License

## Features

- **Works in any app:** Outlook, Gmail, WhatsApp, Slack, Teams, Word, VS Code, Notepad…
- **Turkish and English**, detected automatically for each dictation.
- **Translation:** Turkish → English or English → Turkish, with the same cleanup and formatting.
- **Translate selected text:** select text anywhere, press `Ctrl+C` twice, and the
  translation appears in a popup next to it. Turkish text becomes English, anything
  else becomes Turkish.
- **Read aloud:** press 🔊 in the popup to hear the translation in a natural English
  or Turkish voice. Works offline; each voice downloads once (about 65 MB).
- **Read any selected text aloud:** select text in any app and a small 🔊 button
  appears next to it; click it to hear the text in English or Turkish.
- **App-aware styles:** emails get a greeting and paragraphs, chat messages stay short
  and casual, code editors keep file names and identifiers exact, documents get lists.
  All styles are editable.
- **Personal dictionary** for names and technical terms that must be spelled exactly.
- **Local or cloud, chosen separately** for speech recognition and for the AI cleanup.
- **Safe fallbacks:** if the AI is unavailable, your words are pasted unpolished with a
  warning; dictation never silently fails. The AI never answers or obeys what you say,
  it only writes it down.
- **History** of past dictations (optional, stored only on your PC).

## How it works

**Dictation** (speak and the text is typed for you):

```
hold hotkey → record → speech-to-text → detect app → AI cleanup / translation → paste
```

**Translating selected text** (no speaking needed):

```
select text → press Ctrl+C twice → detect language → AI translation → popup
```

1. Select any text: a sentence on a web page, an email, a PDF, a chat message.
2. Press `Ctrl+C` twice quickly (within half a second).
3. A popup appears next to your mouse with the translation. Turkish text becomes
   English; any other text becomes Turkish.
4. Click **🔊** to hear the translation read aloud, **Copy** to put it on the
   clipboard, or **Replace selection** to paste it over the selected text (where the
   text can be edited). Click outside the popup or press `Esc` to close it.
   The first 🔊 for each language downloads its voice once (about 65 MB).

**Reading selected text aloud** (no translation):

```
select text → 🔊 button appears → click it → the text is read aloud
```

Drag across text or double-click a word in any app and a small 🔊 button appears
next to the mouse for a few seconds. Click it to hear the text (a Turkish voice for
Turkish text, an English voice otherwise); click ■ to stop. Your clipboard is left
as it was. Turn the button off in Settings → Voice.

The translation features use the AI chosen in Settings → Cleanup (Ollama or cloud), so translation also works offline with Ollama.

| Step | Local option | Cloud option |
| --- | --- | --- |
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper `large-v3-turbo` on a CUDA-compatible graphics card, `small` on CPU) | Any OpenAI-compatible transcription API ([Groq](https://console.groq.com) by default) |
| Cleanup and translation | [Ollama](https://ollama.com) with a Gemma model | Any OpenAI-compatible chat API (Groq by default) |

## Requirements

- **Windows 10 or 11** (64-bit) and a microphone.
- **Python 3.10–3.13.** Python 3.11 is tested. Install it with:
  `winget install Python.Python.3.11`
- **Git**, to download the code: `winget install Git.Git`
- **For local AI cleanup and translation:** [Ollama](https://ollama.com).
- **Optional:** a CUDA-compatible graphics card for fast local speech recognition
  (other graphics cards are not used; speech recognition then runs on the processor), or a free
  [Groq API key](https://console.groq.com/keys) for the cloud options.

### Which setup suits your PC

| Your PC | Speech recognition | Cleanup / translation | Rough speed per dictation |
| --- | --- | --- | --- |
| CUDA-compatible GPU, 16 GB+ video memory | Local `large-v3-turbo` | Ollama `gemma3:12b` | about 1 s |
| CUDA-compatible GPU, 8–12 GB | Local `large-v3-turbo` | Ollama `gemma3:4b` | 1–2 s |
| No CUDA-compatible GPU, 16 GB+ RAM | Local `small` (CPU) or Cloud | Ollama `gemma3:4b`, or Cloud | 2–10 s local, about 1 s cloud |
| Any PC with internet | Cloud | Cloud | about 1 s |

`gemma3:12b` gives the best Turkish; smaller models are faster but less careful with
Turkish grammar and translation.

## Installation

### 1. Download TexTurEng

Open PowerShell and run:

```powershell
git clone https://github.com/bulentbaslar/TexTurEng.git C:\Textureng
cd C:\Textureng
```

(Or download the ZIP from the green **Code** button on GitHub and extract it to
`C:\Textureng`.)

### 2. Run the setup script

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
```

It creates a private Python environment in the folder, installs the packages (with
GPU support only when a CUDA-compatible graphics card is found), runs the self-tests and puts a
**TexTurEng** shortcut on your desktop. It ends with `SETUP OK`.

### 3. Install Ollama and a model (for local cleanup and translation)

```powershell
winget install Ollama.Ollama
ollama pull gemma3:12b
```

Use `gemma3:4b` instead on a PC without a strong CUDA-compatible GPU. Ollama starts with
Windows and runs in the background. Skip this step if you will use the cloud options.

### 4. Start TexTurEng

Double-click the desktop shortcut (or `Start Textureng.bat`). A microphone icon appears
in the system tray.

- **First start on a PC without a CUDA-compatible graphics card:** a setup window asks whether speech
  recognition and cleanup should run in the cloud or on the PC, and for an API key if
  you choose cloud.
- **First start with a CUDA-compatible graphics card:** everything runs locally. The Whisper speech model
  (about 1.6 GB) downloads once on first start.

### Installing with Claude Code

The repository includes a `CLAUDE.md` with step-by-step instructions for
[Claude Code](https://claude.com/claude-code). Open the folder in Claude Code and ask:
*"Install TexTurEng on this PC and check the settings."*

## Using TexTurEng

| Action | Keys |
| --- | --- |
| Dictate | Hold `Ctrl+Win`, speak, release. A red listening box appears in the middle of the screen; its waves follow your voice |
| Dictate and translate | Hold `Ctrl+Win+Alt`, or press `Alt` while holding `Ctrl+Win`. The listening box turns orange |
| Translate selected text | Select text in any app and press `Ctrl+C` twice quickly. A popup shows the translation, with **Copy** and **Replace selection** |
| Hands-free | `Ctrl+Win+Space` to start, the same keys to stop |
| Cancel | `Esc` while recording |

Right-click the tray icon for:

- **Speech engine:** local or cloud.
- **Cleanup:** local (Ollama), cloud or off.
- **Translate mode:** translate every dictation without holding `Alt`.
- **Pause, History, Settings, About.**

**Settings** (all changeable at any time):

- **General:** hotkeys, microphone, language (auto / English / Turkish), translation
  direction (the other language, always English, or always Turkish), start with Windows.
- **Speech:** engine, local model, cloud address, model and API key.
- **Cleanup:** on/off, local or cloud, Ollama model.
- **Voice:** natural or Windows voice, the English and Turkish voice, speed,
  reading every translation aloud automatically, and the 🔊 button for selected text.
- **App styles:** which programs count as email, chat, code or document, and how each
  style should write.
- **Dictionary:** names and terms to spell exactly.

Spoken commands: "new line" / "yeni satır" and "new paragraph" / "yeni paragraf".

## Privacy

- **Local mode:** your voice and text never leave your PC.
- **Cloud mode:** audio (speech recognition) and text (cleanup) are sent to the service
  you configure.
- **Your data:** API keys are stored in Windows Credential Manager, never in files.
  Settings, history and the log are in `%APPDATA%\Textureng`.

## Troubleshooting

| Problem | What to do |
| --- | --- |
| Text is pasted with "um"s and a tray warning about Ollama | Start Ollama from the Start menu, and check the model in Settings > Cleanup is one that `ollama list` shows |
| Nothing is transcribed | Pick the right microphone in Settings > General |
| Dictation is slow | Check the timing in `%APPDATA%\Textureng\textureng.log` (`stt` = speech, `cleanup` = AI), then use a smaller model or the cloud option for the slow step |
| Text doesn't appear in one program | That program probably runs as administrator; Windows doesn't allow pasting into it from a normal app |
| `ctrl+win` clashes with another tool | Change the hotkeys in Settings > General |

## For developers

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m textureng --wav tests\assets\english.wav --profile email
.venv\Scripts\python.exe -m textureng --wav tests\assets\english.wav --translate auto
```

`installer\build.ps1` builds a standalone installer with PyInstaller and Inno Setup.
Prebuilt installers are not code-signed, so Windows SmartScreen or Smart App Control may
block them; installing from source as above avoids that.

## Credits

Built with [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
[Ollama](https://ollama.com), Google's Gemma models,
[PySide6](https://doc.qt.io/qtforpython-6/), [pynput](https://github.com/moses-palmer/pynput)
and [sounddevice](https://python-sounddevice.readthedocs.io/). TexTurEng is an
independent project and is not affiliated with any of them.

**Read-aloud voices.** Installing from source uses [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
(Apache-2.0), which includes [espeak-ng](https://github.com/espeak-ng/espeak-ng) (GPL-3.0),
to run [Piper](https://github.com/rhasspy/piper) voices. The voices are downloaded on
first use and keep their own licences: the default English voice (LJ) is trained on
public-domain recordings; for the default Turkish voice (Fahrettin) no licence for its
recordings is published, so treat it as suitable for personal use. For commercial use
choose the Turkish voice Fettah (CC0 recordings) in Settings → Voice; hover over a voice
to see its licence. The prebuilt installer leaves sherpa-onnx out and reads aloud with
the voices built into Windows (for Turkish, add a Turkish voice in Windows Settings →
Time & language → Speech).

## License

[MIT](LICENSE) © 2026 Bulent Baslar
