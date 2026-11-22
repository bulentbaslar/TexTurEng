# Security policy

## Supported versions

Only the latest release of TexTurEng receives security fixes. Please update to the
[latest release](https://github.com/bulentbaslar/TexTurEng/releases/latest) before
reporting a problem.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Instead, report it
privately through GitHub:

1. Go to the [Security tab](https://github.com/bulentbaslar/TexTurEng/security) of this repository.
2. Click **Report a vulnerability**.
3. Describe the problem, the steps to reproduce it, and which version you used.

You will get a reply as soon as possible. Once a fix is released, the report can be
made public with credit to you, if you wish.

## How TexTurEng handles your data

- **Local mode:** speech recognition (Whisper) and cleanup (Ollama) run on your PC;
  your voice and text do not leave it.
- **Cloud mode:** audio and text are sent to the service you configure (Groq by
  default) over HTTPS.
- **API keys** are stored in Windows Credential Manager, never in files or in this
  repository.
- **Settings, history and the log** are stored only on your PC, in
  `%APPDATA%\Textureng`. The log does not contain your dictated text.
- TexTurEng listens to the keyboard and mouse only to detect its own shortcuts and text
  selections; it does not record or send keystrokes.

## Installer

The prebuilt installer is not code-signed. Each release lists the SHA-256 checksum of
`Textureng-Setup.exe`; compare it before running the installer, or install from source
as described in the README.
