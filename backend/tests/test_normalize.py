import pytest

from voicecraft.text.lexicon import Lexicon, load_lexicon
from voicecraft.text.normalize import is_speakable, normalize


@pytest.fixture(scope="module")
def lx():
    return load_lexicon(path=None)


@pytest.mark.parametrize(
    "src, expected",
    [
        ("Ship 10x faster", "Ship 10 times faster."),
        ("Now with v2.0", "Now with version 2 point 0."),
        ("Raised $5M", "Raised 5 million dollars."),
        ("99% uptime", "99 percent uptime."),
        ("10,000 users", "10000 users."),
        ("Step 1/3", "Step 1 of 3."),
        ("No API keys", "No API keys."),
        ("AI tools can now", "AI tools can now."),
        ("Built with React.js", "Built with React J S."),
        ("Visit voicecraft.dev", "Visit voicecraft dot dev."),
        ("Launch 🚀 today!", "Launch today!"),
        ("Fast → simple", "Fast, simple."),
        ("Read the FAQ", "Read the Faq."),
        ("Built with FastAPI", "Built with Fast API."),
    ],
)
def test_normalize(src, expected, lx):
    assert normalize(src, lx) == expected


def test_lexicon_whole_words_and_case():
    lx = Lexicon({"GitHub": "Git Hub", "sql": "sequel"})
    assert normalize("Push to GitHub", lx) == "Push to Git Hub."
    assert normalize("Use SQL daily", lx) == "Use sequel daily."
    assert normalize("GitHubber", lx) == "GitHubber."


def test_user_entries_override_defaults(tmp_path):
    p = tmp_path / "lexicon.json"
    p.write_text('{"Vite": "vight"}')
    assert normalize("Built with Vite", load_lexicon(p)) == "Built with vight."


def test_is_speakable():
    assert is_speakable("Hello world")
    assert not is_speakable("|| --")
    assert not is_speakable("12 34")


@pytest.mark.parametrize("sentence", ["AI tools can now create videos.", "Then a natural AI voice.", "Tools and AI."])
def test_acronym_is_spoken_as_letters_anywhere_in_a_sentence(sentence, lx):
    """Regression: "A I tools" at the start of a sentence was read as the article ("uh I tools")."""
    misaki = pytest.importorskip("misaki.en")
    from misaki import espeak

    g2p = misaki.G2P(trf=False, british=False, fallback=espeak.EspeakFallback(british=False))
    phonemes = g2p(normalize(sentence, lx))[0]
    assert "ˈAˌI" in phonemes  # letter names "ay-eye", never the article "ɐ"
