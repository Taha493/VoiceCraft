"""User-editable pronunciation lexicon: whole-word replacements applied before synthesis.

Stored as JSON at ~/.local/share/voicecraft/lexicon.json: {"GitHub": "Git Hub", "SQL": "sequel"}.
Keys match whole words; keys containing an uppercase letter match case-sensitively.

Write acronyms in capitals ("Fast API"), not as spaced letters ("Fast A P I"): the pronunciation
engines read capitals letter by letter, while a lone "A" is read as the article "uh".
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .. import config

DEFAULTS = {
    "GitHub": "Git Hub",
    "GitLab": "Git Lab",
    "SQL": "sequel",
    "PostgreSQL": "Postgres QL",
    "MySQL": "My SQL",
    "GUI": "gooey",
    "npm": "NPM",
    "pnpm": "PNPM",
    "Vite": "veet",
    "Vercel": "Ver-sell",
    "Kubernetes": "Koober-netties",
    "k8s": "Kubernetes",
    "nginx": "engine X",
    "FastAPI": "Fast API",
    "macOS": "mac OS",
    "iOS": "eye OS",
    "UI/UX": "UI and UX",
    "OAuth": "oh auth",
    "Kokoro": "Ko-ko-ro",
    "README": "read me",
    "e.g.": "for example",
    "i.e.": "that is",
    "etc.": "et cetera",
    "vs.": "versus",
    "vs": "versus",
}


class Lexicon:
    def __init__(self, entries: dict[str, str]):
        self.entries = dict(entries)
        self._compiled = []
        for key in sorted(self.entries, key=len, reverse=True):
            flags = 0 if any(ch.isupper() for ch in key) else re.IGNORECASE
            left = r"(?<![\w])" if key[0].isalnum() else ""
            right = r"(?![\w])" if key[-1].isalnum() else ""
            self._compiled.append((re.compile(left + re.escape(key) + right, flags), self.entries[key]))

    @property
    def version(self) -> str:
        return hashlib.sha1(json.dumps(self.entries, sort_keys=True).encode()).hexdigest()[:10]

    def apply(self, text: str) -> str:
        for pattern, rep in self._compiled:
            text = pattern.sub(rep, text)
        return text


def load_user_entries(path: Path | None = None) -> dict[str, str]:
    p = path or config.lexicon_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return {str(k): str(v) for k, v in data.items() if str(k).strip()}
    except (ValueError, AttributeError):
        return {}


def save_user_entries(entries: dict[str, str], path: Path | None = None) -> None:
    p = path or config.lexicon_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entries, indent=2, ensure_ascii=False))


def load_lexicon(path: Path | None = None) -> Lexicon:
    return Lexicon({**DEFAULTS, **load_user_entries(path)})
