"""
Settings for Provenance Guard.

Everything you're likely to change lives here, at the top, on purpose.

You'll edit the thresholds in Milestone 5 and the rate limits in unit 8.
"""

import os
from pathlib import Path

ROOT = Path(__file__).parent


# ─── The service ─────────────────────────────────────────────────────────────

# `127.0.0.1` is loopback — only your own machine can reach it, which is what
# you want all through units 7 and 8. A host somewhere else has to accept
# traffic from outside the box, and that means `0.0.0.0`. Setting the env var
# is how you get it; the default keeps your local `curl` commands unchanged.
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5000"))

# Flask's debug mode gives anyone who can reach the service an interactive
# Python prompt inside your process. Fine on loopback, a gift to strangers
# anywhere else — so it turns itself off the moment HOST isn't loopback.
DEBUG = os.getenv("AI201_DEBUG", "1") == "1" and HOST in ("127.0.0.1", "localhost")


# ─── The local model ─────────────────────────────────────────────────────────
# Your first signal runs a language model ON YOUR OWN MACHINE. No account, no
# key, no card. It downloads about 550 MB the first time — do that before
# class, not during it.
#
# What it measures: how *predictable* your text is to a language model. Text a
# model finds easy to predict tends to be text a model wrote.
#
# The first call is the slow one — ten to twenty seconds while the model loads,
# longer on an older laptop. After that it stays in memory and a submission
# takes a second or two. That cost is part of what you're learning: this is
# what running a model inline in a request actually looks like.

DETECTOR_MODEL = os.getenv("AI201_DETECTOR_MODEL", "gpt2")

# Longer text gives a steadier reading but takes longer. 400 tokens is roughly
# 300 words, which is enough for the signal to mean something.
DETECTOR_MAX_TOKENS = 400


# ─── Scoring (Milestone 4) ───────────────────────────────────────────────────
# The combining rule lives in scoring.py::combine_signals. In words:
#
#   1. Weighted average: 0.6 × model signal + 0.4 × style signal.
#      The model signal gets more weight because it separates clearly-AI and
#      clearly-human text further apart on the calibration inputs; the style
#      signal is easy to move on purpose (typos, chopped sentences).
#   2. Disagreement rule: if the two signals are more than DISAGREEMENT_GAP
#      apart, the average is pulled halfway back toward 0.5. Two methods that
#      contradict each other is uncertainty, and it should read as "unsure",
#      not as a confident verdict carried by whichever signal is louder.

WEIGHT_MODEL_SIGNAL = 0.6
WEIGHT_STYLE_SIGNAL = 0.4

DISAGREEMENT_GAP = 0.35       # |model − style| above this counts as a split
DISAGREEMENT_SHRINK = 0.5     # how much of the distance from 0.5 survives a split

# ─── The style signal's internals (stylometry.py) ────────────────────────────
# Each raw measure is mapped to 0–1 AI-ness by a logistic curve:
#   (midpoint, scale) — at the midpoint the measure scores 0.5; `scale` sets how
#   quickly it moves either side. All three raw measures point "higher = human".

STYLE_SPREAD_CURVE = (0.35, 0.10)   # sentence-length coefficient of variation
STYLE_TTR_CURVE = (0.85, 0.05)      # moving-average type-token ratio
STYLE_PUNCT_CURVE = (0.05, 0.02)    # expressive punctuation per word × variety

# Relative weight of (spread, word variety, punctuation) inside the style signal.
STYLE_WEIGHTS = (0.6, 0.2, 0.2)


# ─── Thresholds (Milestone 5) ────────────────────────────────────────────────
# Where one label becomes another. Scores run 0.0 (confidently human) to 1.0
# (confidently AI).
#
#   score < HUMAN_THRESHOLD          -> high-confidence human
#   between the two                  -> unsure
#   score > AI_THRESHOLD             -> high-confidence AI
#
# ⚠️ This is where your false-positive decision from Milestone 1 actually gets
# made. Widening the unsure band means fewer wrong accusations and more AI text
# getting through. There is no setting that avoids the trade — only settings
# that decide who pays for it.

HUMAN_THRESHOLD = 0.40
AI_THRESHOLD = 0.75   # unit 8 improvement: was 0.70. FP05 (human technical docs)
                      # scored 0.7425 with both signals agreeing; see README → The Improvement

# Asymmetric on purpose: the AI band starts 0.20 above the midpoint, the human
# band only 0.10 below it. Accusing a real writer costs more than missing some
# AI text, so it takes more evidence to say "AI" than to say "person".

# Input limits for POST /submit.
MIN_WORDS = 20          # below this neither signal means anything
MAX_CHARS = 20000       # ~3,500 words; beyond this is refused, not truncated

# ⚠️ One thing that catches people out in Milestone 5. A weighted average can
# only land between its two inputs — so while `style_signal` is still the stub
# returning 0.5, the combined score can never leave 0.25–0.75 no matter what
# the model signal says, and the human label needs a model score below 0.20 to
# be reachable at all.
#
# If a label you can't reach is the problem, the fix is upstream of the
# thresholds: a style signal that actually varies. `scoring.label_ranges()`
# prints the bands; the reachable range is a different question.


# ─── Rate limiting (UNIT 8) ──────────────────────────────────────────────────
# Off in unit 7. You turn it on and choose the numbers in unit 8, Milestone 1.
#
# Think about two people: a real writer submitting their own work a few times
# an hour, and a script sending a thousand variations to map your thresholds.
# Your README has to say why your numbers and not others.

RATE_LIMITING_ENABLED = True

# Counted per creator_id (falls back to the caller's address when there isn't
# one). 6 a minute leaves room for a writer resubmitting after a few quick
# edits; 60 a day is far more than anyone checks their own work. A script
# mapping the thresholds with ~1,000 variations gets 60 a day per creator_id,
# so one identity would take over two weeks.
RATE_LIMIT_PER_MINUTE = 6
RATE_LIMIT_PER_DAY = 60

# Flask-Limiter warns loudly without this. In-memory is right for one laptop
# and wrong for anything real — a restart forgets every count, and two copies
# of the service wouldn't share limits.
RATE_LIMIT_STORAGE = "memory://"


# ─── Paths ───────────────────────────────────────────────────────────────────

LOG_DIR = ROOT / "logs"
AUDIT_LOG = LOG_DIR / "audit.jsonl"
RESULTS_DIR = ROOT / "results"
