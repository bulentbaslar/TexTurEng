"""Launcher without a console window. Used by the shortcut, "Start with Windows"
and as the entry point of the packaged Textureng.exe (shown as TexTurEng)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from textureng.__main__ import main

sys.exit(main())
