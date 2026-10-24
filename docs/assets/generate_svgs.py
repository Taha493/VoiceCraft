"""Generate the animated README graphics (SMIL animations play in GitHub's image viewer).

    python3 docs/assets/generate_svgs.py   →  hero.svg, pipeline.svg
"""

import math
from pathlib import Path

HERE = Path(__file__).parent
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"


def bars(x0: float, cy: float, n: int, gap: float, width: float, max_h: float, seed: float, color: str, dur: float = 1.1) -> str:
    """Speech-like waveform: each bar loops through a few heights, staggered across the row."""
    out = []
    for i in range(n):
        hs = []
        for k in range(5):
            env = 0.3 + 0.7 * abs(math.sin(i * 0.37 + k * 1.3 + seed) * math.cos(i * 0.11 + k * 0.7))
            hs.append(max(6.0, max_h * env))
        hs.append(hs[0])
        x = x0 + i * gap
        h_vals = ";".join(f"{h:.1f}" for h in hs)
        y_vals = ";".join(f"{cy - h / 2:.1f}" for h in hs)
        begin = f"{-(i % 7) * 0.13:.2f}s"
        out.append(
            f'<rect x="{x:.1f}" y="{cy - hs[0] / 2:.1f}" width="{width}" height="{hs[0]:.1f}" rx="{width / 2}" fill="{color}">'
            f'<animate attributeName="height" values="{h_vals}" dur="{dur}s" begin="{begin}" repeatCount="indefinite"/>'
            f'<animate attributeName="y" values="{y_vals}" dur="{dur}s" begin="{begin}" repeatCount="indefinite"/></rect>'
        )
    return "\n    ".join(out)


def logo(x: float, y: float, size: float) -> str:
    s = size / 32
    return f'''<g transform="translate({x} {y}) scale({s})">
    <rect width="32" height="32" rx="8" fill="url(#violet)"/>
    <g stroke="#fff" stroke-width="2.6" stroke-linecap="round">
      <path d="M8 13v6"><animate attributeName="d" values="M8 13v6;M8 11v10;M8 13v6" dur="1.2s" repeatCount="indefinite"/></path>
      <path d="M12.7 9v14"><animate attributeName="d" values="M12.7 9v14;M12.7 12v8;M12.7 9v14" dur="1.2s" begin="-0.3s" repeatCount="indefinite"/></path>
      <path d="M17.3 11.5v9"><animate attributeName="d" values="M17.3 11.5v9;M17.3 8v16;M17.3 11.5v9" dur="1.2s" begin="-0.6s" repeatCount="indefinite"/></path>
      <path d="M22 14v4"><animate attributeName="d" values="M22 14v4;M22 12v8;M22 14v4" dur="1.2s" begin="-0.9s" repeatCount="indefinite"/></path>
    </g>
    <circle cx="25.2" cy="16" r="1.3" fill="#fff"/>
  </g>'''


DEFS = '''<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b0b14"/><stop offset="1" stop-color="#140c28"/></linearGradient>
    <linearGradient id="violet" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#6d28d9"/></linearGradient>
    <linearGradient id="title" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#ffffff"/><stop offset="0.55" stop-color="#c4b5fd"/><stop offset="1" stop-color="#22d3ee"/></linearGradient>
    <linearGradient id="frame" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#312e81"/><stop offset="0.6" stop-color="#7c3aed"/><stop offset="1" stop-color="#0e7490"/></linearGradient>
    <linearGradient id="wave" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#e9d5ff"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
    <radialGradient id="glowA"><stop offset="0" stop-color="#7c3aed" stop-opacity=".55"/><stop offset="1" stop-color="#7c3aed" stop-opacity="0"/></radialGradient>
    <radialGradient id="glowB"><stop offset="0" stop-color="#0e7490" stop-opacity=".45"/><stop offset="1" stop-color="#0e7490" stop-opacity="0"/></radialGradient>
    <clipPath id="card"><rect width="1280" height="420" rx="24"/></clipPath>
  </defs>'''


def hero() -> str:
    captions = ["Meet VoiceCraft.", "It reads the captions on screen,", "and gives them a natural voice."]
    cap_svg = []
    for i, text in enumerate(captions):
        cap_svg.append(
            f'''<g opacity="0">
      <rect x="{913 - (len(text) * 10.6 + 36) / 2:.0f}" y="262" width="{len(text) * 10.6 + 36:.0f}" height="42" rx="10" fill="#08080f" fill-opacity=".85"/>
      <text x="913" y="290" text-anchor="middle" font-family="{FONT}" font-size="21" font-weight="600" fill="#fff">{text}</text>
      <animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;0.04;0.29;0.33;1" dur="9s" begin="{i * 3}s" repeatCount="indefinite"/>
    </g>''')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="420" viewBox="0 0 1280 420" role="img" aria-label="VoiceCraft: local AI voice-overs for silent videos">
  {DEFS}
  <g clip-path="url(#card)">
  <rect width="1280" height="420" fill="url(#bg)"/>
  <circle cx="160" cy="40" r="360" fill="url(#glowA)"><animate attributeName="cx" values="160;260;160" dur="12s" repeatCount="indefinite"/></circle>
  <circle cx="1200" cy="420" r="380" fill="url(#glowB)"><animate attributeName="cy" values="420;360;420" dur="10s" repeatCount="indefinite"/></circle>

  {logo(72, 78, 64)}
  <text x="154" y="126" font-family="{FONT}" font-size="54" font-weight="800" letter-spacing="-1.5" fill="url(#title)">VoiceCraft</text>
  <text x="74" y="196" font-family="{FONT}" font-size="25" font-weight="600" fill="#f1f1f7">Give silent videos a natural voice.</text>
  <text x="74" y="232" font-family="{FONT}" font-size="19" fill="#a3a3bb">Reads the captions, speaks every line, syncs and mixes.</text>
  <text x="74" y="260" font-family="{FONT}" font-size="19" fill="#a3a3bb">Runs 100% on your own computer, no cloud and no API keys.</text>
  <g font-family="{FONT}" font-size="15" fill="#d4d4e4">
    <rect x="74" y="300" width="132" height="34" rx="17" fill="#ffffff" fill-opacity=".06" stroke="#34344a"/><text x="140" y="322" text-anchor="middle">Kokoro TTS</text>
    <rect x="216" y="300" width="110" height="34" rx="17" fill="#ffffff" fill-opacity=".06" stroke="#34344a"/><text x="271" y="322" text-anchor="middle">RapidOCR</text>
    <rect x="336" y="300" width="96" height="34" rx="17" fill="#ffffff" fill-opacity=".06" stroke="#34344a"/><text x="384" y="322" text-anchor="middle">FFmpeg</text>
    <rect x="442" y="300" width="150" height="34" rx="17" fill="#34d399" fill-opacity=".12" stroke="#34d399" stroke-opacity=".5"/><text x="517" y="322" text-anchor="middle" fill="#6ee7b7">100% offline</text>
  </g>

  <g>
    <rect x="690" y="48" width="446" height="270" rx="18" fill="url(#frame)" stroke="#ffffff" stroke-opacity=".12"/>
    <circle cx="780" cy="140" r="46" fill="#fff" fill-opacity=".14"><animate attributeName="cy" values="140;118;140" dur="5s" repeatCount="indefinite"/></circle>
    <rect x="980" y="88" width="96" height="96" rx="22" fill="#fff" fill-opacity=".16"><animateTransform attributeName="transform" type="rotate" values="0 1028 136;360 1028 136" dur="14s" repeatCount="indefinite"/></rect>
    <g transform="translate(1092 64)"><circle r="15" cx="15" cy="15" fill="#08080f" fill-opacity=".75"/>
      <path d="M9 12h3l4-3v12l-4-3H9z" fill="#c4b5fd"/><path d="M19 11.5a5 5 0 0 1 0 7" stroke="#c4b5fd" stroke-width="1.6" fill="none" stroke-linecap="round"><animate attributeName="opacity" values="1;.2;1" dur="1s" repeatCount="indefinite"/></path></g>
    {"".join(cap_svg)}
    <rect x="690" y="332" width="446" height="62" rx="14" fill="#12121c" stroke="#2a2a3d"/>
    {bars(712, 363, 44, 9.6, 5, 42, 0.0, "url(#wave)")}
  </g>
  </g>
</svg>
'''


ICONS = {
    "film": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 7.5h4M3 12h18M3 16.5h4M17 7.5h4M17 16.5h4"/>',
    "scan": '<path d="M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 9h10M7 13h10M7 17h6"/>',
    "mic": '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/>',
    "sync": '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2"/><path d="M9 2h6"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "check": '<circle cx="12" cy="12" r="10"/><path d="m8 12 3 3 5-6"/>',
}


def pipeline() -> str:
    steps = [
        ("film", "Silent video", "captions burned in", "#a3a3bb"),
        ("scan", "Read", "OCR finds captions", "#a78bfa"),
        ("mic", "Speak", "natural local voice", "#c4b5fd"),
        ("sync", "Sync", "line starts with caption", "#34d399"),
        ("music", "Mix", "music, ducking, −16 LUFS", "#22d3ee"),
        ("check", "Narrated MP4", "ready to share", "#6ee7b7"),
    ]
    w, h, gap, y0 = 172, 150, 34, 40
    x0 = (1280 - (len(steps) * w + (len(steps) - 1) * gap)) / 2
    period = 0.7 * len(steps) + 1.2
    nodes, links = [], []
    for i, (icon, title, sub, color) in enumerate(steps):
        x = x0 + i * (w + gap)
        begin = f"{i * 0.7:.1f}s"
        nodes.append(f'''<g>
    <rect x="{x}" y="{y0}" width="{w}" height="{h}" rx="18" fill="#12121c" stroke="#2a2a3d"/>
    <rect x="{x}" y="{y0}" width="{w}" height="{h}" rx="18" fill="none" stroke="{color}" stroke-width="2" opacity="0">
      <animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;0.06;0.2;0.32;1" dur="{period:.1f}s" begin="{begin}" repeatCount="indefinite"/></rect>
    <g transform="translate({x + w / 2 - 22} {y0 + 22})">
      <rect width="44" height="44" rx="12" fill="{color}" fill-opacity=".14"/>
      <g transform="translate(10 10)" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <g transform="scale(1)">{ICONS[icon]}</g>
        <animateTransform attributeName="transform" type="translate" values="10 10;10 7;10 10;10 10" keyTimes="0;0.08;0.16;1" dur="{period:.1f}s" begin="{begin}" repeatCount="indefinite"/>
      </g>
    </g>
    <text x="{x + w / 2}" y="{y0 + 100}" text-anchor="middle" font-family="{FONT}" font-size="18" font-weight="700" fill="#f1f1f7">{title}</text>
    <text x="{x + w / 2}" y="{y0 + 124}" text-anchor="middle" font-family="{FONT}" font-size="13" fill="#a3a3bb">{sub}</text>
  </g>''')
        if i < len(steps) - 1:
            lx = x + w + 4
            links.append(
                f'<path d="M{lx} {y0 + h / 2} h{gap - 8}" stroke="#7c3aed" stroke-width="3" stroke-linecap="round" stroke-dasharray="4 7">'
                f'<animate attributeName="stroke-dashoffset" values="22;0" dur="0.8s" repeatCount="indefinite"/></path>'
                f'<path d="M{lx + gap - 12} {y0 + h / 2 - 5} l6 5 l-6 5" stroke="#a78bfa" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
            )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="230" viewBox="0 0 1280 230" role="img" aria-label="Pipeline: silent video, read captions, speak, sync, mix, narrated MP4">
  <defs><clipPath id="c"><rect width="1280" height="230" rx="24"/></clipPath>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b0b14"/><stop offset="1" stop-color="#140c28"/></linearGradient></defs>
  <g clip-path="url(#c)"><rect width="1280" height="230" fill="url(#bg)"/>
  {"".join(links)}
  {"".join(nodes)}
  </g>
</svg>
'''


if __name__ == "__main__":
    (HERE / "hero.svg").write_text(hero())
    (HERE / "pipeline.svg").write_text(pipeline())
    print("wrote hero.svg, pipeline.svg")
