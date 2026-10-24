"""Turn on-screen caption text into something a TTS engine pronounces well.

Captions in product videos are full of symbols, versions, acronyms and file names. The engines'
own G2P (espeak-ng / misaki) handles plain numbers and words; this layer handles the rest, then
the user lexicon overrides any word.
"""

from __future__ import annotations

import re
import unicodedata

from .lexicon import Lexicon

# Acronyms normally said as a word rather than letter by letter.
SPOKEN_AS_WORD = {
    "NASA", "SAAS", "PAAS", "IAAS", "JSON", "YAML", "GIF", "JPEG", "PNG", "SCSS", "SASS", "LAN", "WAN",
    "RAM", "ROM", "CAPTCHA", "SIM", "PIN", "LASER", "RADAR", "SCUBA", "NATO", "UNESCO", "OAUTH",
    "WASM", "CRUD", "REST", "DEMO", "FAQ", "ASAP", "OK", "TODO", "NEW", "NOW", "FREE", "WOW", "AND", "THE",
}

_SYMBOLS = {
    "&": " and ", "@": " at ", "+": " plus ", "=": " equals ", "→": ", ", "⟶": ", ", "->": ", ", "=>": ", ",
    "←": ", ", "↑": " up ", "↓": " down ", "×": " times ", "•": ", ", "·": ", ", "|": ", ", "/": " slash ",
    "~": " about ", "≈": " about ", "≥": " at least ", "≤": " at most ", "°": " degrees ", "…": "...",
    "—": ", ", "–": " to ", "™": "", "®": "", "©": "",
}
_SCALE = {"k": "thousand", "K": "thousand", "m": "million", "M": "million", "b": "billion", "B": "billion", "bn": "billion"}
_CURRENCY = {"$": "dollars", "€": "euros", "£": "pounds", "¥": "yen", "₹": "rupees"}
_TLDS = "com|org|net|io|ai|dev|app|co|so|sh|xyz|gg|me"
_FILE_EXT = {"js": "J S", "ts": "T S", "jsx": "J S X", "tsx": "T S X", "py": "pie", "md": "M D", "css": "C S S", "html": "H T M L"}


def _strip_emoji(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Co") or ch in _SYMBOLS)


def _money(m: re.Match) -> str:
    cur, num, scale = m.group(1), m.group(2), m.group(3) or ""
    words = f"{num} {_SCALE.get(scale, '')}".strip()
    return f"{words} {_CURRENCY[cur]}"


def _version(m: re.Match) -> str:
    parts = m.group(2).split(".")
    return "version " + " point ".join(parts)


def _acronym(m: re.Match) -> str:
    """Acronyms stay in capitals: misaki and espeak both read them letter by letter, with natural
    stress. Spacing the letters out ("A I") made a sentence-initial "A" read as the article
    "uh" ("uh I tools"). Only acronyms that are said as words are turned into words."""
    word = m.group(0)
    core = word[:-1] if word.endswith("s") and word[:-1].isupper() else word
    if core in SPOKEN_AS_WORD:
        return word.capitalize() if len(word) > 1 else word
    return word


def normalize(text: str, lexicon: Lexicon | None = None) -> str:
    t = unicodedata.normalize("NFKC", text)
    t = _strip_emoji(t)
    t = re.sub(r"https?://", "", t)
    t = re.sub(r"\bwww\.", "", t)

    if lexicon:
        t = lexicon.apply(t)

    # Domains and file names before generic punctuation handling.
    t = re.sub(rf"\b([A-Za-z0-9-]+)\.({_TLDS})\b", lambda m: f"{m.group(1)} dot {m.group(2)}", t)
    t = re.sub(r"\b([A-Za-z][\w-]*)\.(jsx?|tsx?|py|md|css|html)\b", lambda m: f"{m.group(1)} {_FILE_EXT[m.group(2).lower()]}", t)

    # Money, scales, multipliers, percents, versions.
    t = re.sub(r"([$€£¥₹])\s?(\d+(?:[.,]\d+)?)\s?(bn|[kKmMbB])?\b", _money, t)
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s?(bn|[kKmMbB])\b(?!\w)", lambda m: f"{m.group(1)} {_SCALE[m.group(2)]}", t)
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s?[xX]\b", r"\1 times", t)
    t = re.sub(r"(\d)\s?%", r"\1 percent", t)
    t = re.sub(r"\b([vV])(\d+(?:\.\d+)+|\d+)\b", _version, t)
    t = re.sub(r"(\d),(\d{3})\b", r"\1\2", t)  # 10,000 → 10000 (avoid "ten, zero zero zero")
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: f"{int(m.group(1))} {m.group(2) if m.group(2) != '00' else ''}".strip(), t)
    t = re.sub(r"\b(\d+)\s?/\s?(\d+)\b", r"\1 of \2", t)  # "Step 1/3"
    t = re.sub(r"\b([A-Za-z]{2,})/([A-Za-z]{2,})\b", r"\1 or \2", t)  # "and/or", "client/server"
    t = re.sub(r"#(\d+)", r"number \1", t)
    t = re.sub(r"#(\w+)", r"hashtag \1", t)

    for sym, rep in sorted(_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        t = t.replace(sym, rep)

    # Acronyms said as words (NASA, JSON) are written as words; the rest stay as capitals.
    t = re.sub(r"\b[A-Z]{2,5}s?\b", _acronym, t)
    # camelCase / PascalCase product names are fine for the engines; snake_case is not.
    t = re.sub(r"(\w)_(\w)", r"\1 \2", t)

    t = re.sub(r"[\"“”‘’`*_^<>\[\]{}]", "", t)
    t = re.sub(r"\s*,\s*(,\s*)+", ", ", t)
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    t = re.sub(r"^[,.;:\s]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t and t[-1] not in ".!?":
        t += "."
    return t


def is_speakable(text: str) -> bool:
    letters = sum(ch.isalpha() for ch in text)
    return letters >= 2 and letters / max(1, len(text.replace(" ", ""))) >= 0.5
