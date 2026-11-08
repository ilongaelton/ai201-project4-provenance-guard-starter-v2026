"""
Signal two: the style signal.

Signal one reads the text for meaning. This one measures it *as text* — the
shape of it, without understanding a word.

Three measures are stubbed below because the brief names those three. They are
stubs, not implementations: what they compute is yours, and so is how you
combine them.

    sentence_length_spread   do sentences vary in length, or march in step?
    type_token_ratio         how much of the vocabulary repeats?
    punctuation_density      how much punctuation, and how varied?

Why these might differ between human and AI writing: generated prose tends
toward even, mid-length sentences and a narrower band of vocabulary, because
that's what "most likely next word" produces on average. Human writing is
lumpier — a three-word sentence next to a forty-word one.

⚠️ **The blind spot, which you have to name in Milestone 1.**

This signal cannot read. It has no idea what the text says. Anything that
changes the shape without changing the substance moves it — adding typos,
breaking up sentences, pasting in a quotation. That is a very cheap thing for
someone to do on purpose, and unit 8's attack set will do it to you.

Build each function on its own and call it from a terminal before you wire
anything together:

    python stylometry.py "some text to look at"
"""

import math
import re
import statistics

import config


def sentences(text: str) -> list[str]:
    """Split into sentences. Rough and good enough — given to you."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def words(text: str) -> list[str]:
    """Split into lowercase words, punctuation stripped. Given to you."""
    return re.findall(r"[a-z0-9']+", text.lower())


# ── The three measures ───────────────────────────────────────────────────────
#
# Each raw measure is on its own scale. `style_signal` maps each one onto 0–1
# (higher = more AI-like) with a logistic curve centred on a midpoint, then
# takes a weighted average. Midpoints and weights live in config.py.
#
#   measure                  raw scale            direction
#   sentence_length_spread   0 … ~1.5 (CV)        HIGH = more human
#   type_token_ratio         0 … 1   (MATTR)      HIGH = more human
#   punctuation_density      0 … ~0.3 per word    HIGH = more human

MATTR_WINDOW = 50   # words per window for the moving-average type-token ratio

# Punctuation that varies between writers. Full stops are left out on purpose:
# every sentence has one, so they say more about sentence count than style.
EXPRESSIVE_PUNCTUATION = set(",;:!?()\"'—–-…“”‘’")


def sentence_length_spread(text: str) -> float:
    """
    Coefficient of variation of sentence length, in words (stdev / mean).

    Returns:
        0.0 upwards. Typical prose lands 0.2–0.9. **Higher = more human** —
        people mix three-word sentences with forty-word ones; generated text
        tends to march in step.

    Edge case: with fewer than two sentences there is no spread to measure, so
    this returns 0.0 — and `style_signal` treats that measure as "no evidence"
    (neutral) rather than as maximally AI-like.
    """
    lengths = [len(words(s)) for s in sentences(text)]
    lengths = [n for n in lengths if n > 0]
    if len(lengths) < 2:
        return 0.0
    mean = statistics.mean(lengths)
    return statistics.stdev(lengths) / mean if mean else 0.0


def type_token_ratio(text: str) -> float:
    """
    Moving-average type-token ratio (MATTR) over 50-word windows.

    Returns:
        0–1. **Higher = more varied vocabulary = more human.**

    A plain unique/total ratio falls as text gets longer, so a short human
    note and a long AI essay would be compared unfairly. Averaging the ratio
    over fixed-size windows removes most of that length effect. Texts shorter
    than one window fall back to the plain ratio.
    """
    toks = words(text)
    if not toks:
        return 0.0
    if len(toks) <= MATTR_WINDOW:
        return len(set(toks)) / len(toks)
    ratios = [
        len(set(toks[i:i + MATTR_WINDOW])) / MATTR_WINDOW
        for i in range(len(toks) - MATTR_WINDOW + 1)
    ]
    return statistics.mean(ratios)


def punctuation_density(text: str) -> float:
    """
    Expressive punctuation marks per word, scaled by how many kinds are used.

    Counts commas, semicolons, colons, dashes, brackets, quotes, ! and ? — not
    full stops. The count per word is multiplied by a variety factor
    (distinct kinds / 4, capped at 1), so a text that is all commas scores
    lower than one that also reaches for a dash, a bracket and a question.

    Returns:
        0.0 upwards; typical prose 0.03–0.25. **Higher = more human.**
    """
    toks = words(text)
    if not toks:
        return 0.0
    marks = [c for c in text if c in EXPRESSIVE_PUNCTUATION]
    variety = min(len(set(marks)) / 4, 1.0)
    return (len(marks) / len(toks)) * variety


# ── Combining them ───────────────────────────────────────────────────────────

def _ai_ness(value: float, midpoint: float, scale: float) -> float:
    """Map a 'higher = more human' measure onto 0–1 where higher = more AI."""
    z = (value - midpoint) / scale
    z = max(min(z, 30.0), -30.0)
    return 1.0 / (1.0 + math.exp(z))


def style_parts(text: str) -> dict:
    """Each measure raw and as a 0–1 AI-ness score. Handy for debugging."""
    spread = sentence_length_spread(text)
    ttr = type_token_ratio(text)
    punct = punctuation_density(text)

    n_sentences = len(sentences(text))
    spread_ai = 0.5 if n_sentences < 2 else _ai_ness(spread, *config.STYLE_SPREAD_CURVE)
    ttr_ai = _ai_ness(ttr, *config.STYLE_TTR_CURVE)
    punct_ai = _ai_ness(punct, *config.STYLE_PUNCT_CURVE)

    return {
        "sentence_length_spread": round(spread, 4),
        "type_token_ratio": round(ttr, 4),
        "punctuation_density": round(punct, 4),
        "spread_ai": round(spread_ai, 4),
        "ttr_ai": round(ttr_ai, 4),
        "punct_ai": round(punct_ai, 4),
    }


def style_signal(text: str) -> float:
    """
    The style signal as a 0–1 score. **Higher means more likely AI.**

    Each measure is flipped (all three point "higher = more human" raw) and
    squashed onto 0–1 by a logistic curve, then combined as a weighted average
    using STYLE_WEIGHTS in config.py. Sentence spread carries the most weight
    because it is the measure least affected by topic and vocabulary level.
    """
    p = style_parts(text)
    w_spread, w_ttr, w_punct = config.STYLE_WEIGHTS
    score = (
        w_spread * p["spread_ai"] + w_ttr * p["ttr_ai"] + w_punct * p["punct_ai"]
    ) / (w_spread + w_ttr + w_punct)
    return round(min(max(score, 0.0), 1.0), 4)


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or (
        "The system works well. It handles most cases correctly and provides "
        "good results. Users generally find it easy to use and understand."
    )

    print(f"{len(sentences(text))} sentences, {len(words(text))} words\n")
    print(f"sentence_length_spread   {sentence_length_spread(text)}")
    print(f"type_token_ratio         {type_token_ratio(text)}")
    print(f"punctuation_density      {punctuation_density(text)}")
    print(f"style_signal             {style_signal(text)}   (higher = more likely AI)")
    print()
    for k, v in style_parts(text).items():
        if k.endswith("_ai"):
            print(f"  {k:<10} {v}   (this measure alone, higher = more AI)")
