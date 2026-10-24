from voicecraft.captions.tracker import Observation, build_captions, continues, text_key

DT = 0.25


def obs(seq: list[tuple[float, str]], score: float = 0.98) -> list[Observation]:
    return [Observation(t, txt, score if txt else 0.0) for t, txt in seq]


def timeline(*spans: tuple[float, float, str], end: float = 10.0) -> list[Observation]:
    out = []
    t = 0.0
    while t < end:
        txt = next((s for a, b, s in spans if a <= t < b), "")
        out.append(Observation(round(t, 3), txt, 0.98 if txt else 0.0))
        t += DT
    return out


def test_two_captions_with_gap():
    caps = build_captions(timeline((1.0, 3.0, "Hello there."), (4.0, 6.0, "Second line.")), DT, 10.0)
    assert [c.text for c in caps] == ["Hello there.", "Second line."]
    assert abs(caps[0].start - 1.0) <= DT and abs(caps[0].end - 3.0) <= DT
    assert abs(caps[1].start - 4.0) <= DT
    assert not any(c.flagged for c in caps)


def test_back_to_back_captions_split_without_blank():
    caps = build_captions(timeline((1.0, 3.0, "Meet VoiceCraft."), (3.0, 5.0, "Built for creators.")), DT, 10.0)
    assert [c.text for c in caps] == ["Meet VoiceCraft.", "Built for creators."]


def test_typewriter_reveal_becomes_one_caption_with_full_text():
    words = "It reads your captions and speaks them".split()
    seq = [(1.0 + i * DT, " ".join(words[: i + 1])) for i in range(len(words))]
    seq += [(1.0 + (len(words) + k) * DT, " ".join(words)) for k in range(6)]
    caps = build_captions(obs(seq), DT, 10.0)
    assert len(caps) == 1
    assert caps[0].text == " ".join(words)
    assert caps[0].start <= 1.0


def test_single_sample_dropout_is_bridged():
    seq = timeline((1.0, 4.0, "Stable caption"))
    seq = [o if abs(o.t - 2.5) > 1e-6 else Observation(o.t, "", 0.0) for o in seq]
    caps = build_captions(seq, DT, 10.0)
    assert len(caps) == 1


def test_ocr_noise_variant_does_not_win():
    seq = obs([(1.0, "Everything runs locally"), (1.25, "Everythinq runs locally"), (1.5, "Everything runs locally"), (1.75, "Everything runs locally")])
    caps = build_captions(seq, DT, 10.0)
    assert len(caps) == 1 and caps[0].text == "Everything runs locally"


def test_single_low_confidence_flash_is_dropped():
    seq = [Observation(1.0, "zz flash", 0.6)]
    assert build_captions(seq, DT, 10.0) == []


def test_single_confident_reading_is_kept_but_flagged():
    caps = build_captions([Observation(1.0, "Quick caption", 0.97)], DT, 10.0)
    assert len(caps) == 1 and caps[0].flagged


def test_junk_is_dropped():
    assert build_captions(obs([(1.0, "|||"), (1.25, "|||")]), DT, 10.0) == []


def test_continues_rules():
    assert continues(text_key("It reads"), text_key("It reads your captions"))
    assert not continues(text_key("Meet VoiceCraft"), text_key("Built for creators"))


def test_merge_bands_interleaves_and_joins_simultaneous_lines():
    from voicecraft.captions.detect import merge_bands
    from voicecraft.schema import Caption

    top = [Caption(id="a", start=1.0, end=3.0, text="CaptionDock"), Caption(id="b", start=5.0, end=7.0, text="Catch up.")]
    bottom = [Caption(id="x", start=1.2, end=3.5, text="Captions that stay on top."), Caption(id="y", start=3.6, end=4.8, text="Scroll back.")]
    merged = merge_bands([top, bottom])
    assert [c.text for c in merged] == ["CaptionDock. Captions that stay on top.", "Scroll back.", "Catch up."]
    assert merged[0].end == 3.5 and [c.id for c in merged] == ["c1", "c2", "c3"]


def test_text_walls_are_not_caption_bands():
    from voicecraft.captions.ocr import TextLine
    from voicecraft.captions.region import _Band, _drop_text_walls

    def band(cy, h=0.04):
        return _Band([(0, TextLine("t", 1.0, (0.1, cy - h / 2, 0.9, cy + h / 2)))])

    caption_top, wall, caption_bottom = [band(0.14, 0.05)], [band(0.32 + 0.06 * i) for i in range(6)], [band(0.87)]
    kept = _drop_text_walls(caption_top + wall + caption_bottom)
    assert [round(b.cy, 2) for b in kept] == [0.14, 0.87]
    # A caption wrapped onto two lines is kept.
    assert len(_drop_text_walls([band(0.80), band(0.86)])) == 2


def test_fixed_header_near_size_threshold_is_static():
    from voicecraft.captions.ocr import TextLine
    from voicecraft.captions.region import _Band, _always_there

    # Header visible in all 18 frames, but measured "large" in only 3 of them.
    found = [(i, TextLine("VoiceCraft", 0.99, (0.03, 0.045, 0.12, 0.071))) for i in range(18)]
    band = _Band([(i, ln) for i, ln in found if i in (3, 4, 17)])
    assert _always_there(band, found, 18)
    # A title card shown in 3 frames is not.
    assert not _always_there(band, [(i, ln) for i, ln in found if i in (3, 4, 17)], 18)


def test_ocr_ai_misread_is_corrected():
    from voicecraft.captions.tracker import fix_ocr_confusions

    assert fix_ocr_confusions("Need a custom Al tool like this?") == "Need a custom AI tool like this?"
    assert fix_ocr_confusions("Al-powered demos") == "AI-powered demos"
    assert fix_ocr_confusions("Also Algebra and Alan") == "Also Algebra and Alan"
