"""
Turning two numbers into one, and one number into something a person can read.

Two functions live here.

`combine_signals` is where your false-positive decision from Milestone 1
actually gets made. Everything above it — the labels, the appeal path — is
downstream of a number this function produced.

`score_to_label` is where you stop writing for a machine and start writing for
a person. A score of 0.62 means nothing to a writer.

⚠️ Your README's **Signals and Scoring** section has to name the file and
function holding your combining rule. The grader checks your code against what
you claim, so that line should read `scoring.py::combine_signals`.
"""

import config


LABEL_AI = (
    "This looks like it was likely produced with an AI writing tool. Our "
    "automated check is fairly confident, but it can be wrong. If you wrote "
    "this yourself, you can ask for a person to review it."
)

LABEL_HUMAN = (
    "We think this was probably written by a person. Our automated check "
    "found no strong signs of AI writing."
)

LABEL_UNSURE = (
    "We can't tell whether this was written by a person or with an AI tool. "
    "This is not an accusation: plenty of genuine writing lands here, and no "
    "action has been taken. If you'd like a person to look at it, you can "
    "ask for a review."
)


def combine_signals(model_score: float, style_score: float) -> float:
    """
    Combine two 0–1 signals into one 0–1 score (higher = more likely AI).

    The rule, with its numbers in config.py:

      1. avg = 0.6 × model_score + 0.4 × style_score
      2. If |model_score − style_score| > 0.35, the signals disagree, and the
         score is pulled halfway back toward 0.5:
             score = 0.5 + (avg − 0.5) × 0.5
         Two methods contradicting each other is uncertainty, so it should read
         as "unsure" rather than letting the louder signal decide alone.

    Example: model 0.85, style 0.20 → avg 0.59 → split (gap 0.65) → 0.545,
    which is "unsure" instead of a near-AI verdict.
    """
    avg = (
        config.WEIGHT_MODEL_SIGNAL * model_score
        + config.WEIGHT_STYLE_SIGNAL * style_score
    ) / (config.WEIGHT_MODEL_SIGNAL + config.WEIGHT_STYLE_SIGNAL)

    if abs(model_score - style_score) > config.DISAGREEMENT_GAP:
        avg = 0.5 + (avg - 0.5) * config.DISAGREEMENT_SHRINK

    return round(min(max(avg, 0.0), 1.0), 4)


def score_to_label(score: float) -> tuple[str, str]:
    """
    Turn a score into (guess, label_text).

        score >= AI_THRESHOLD (0.70)      -> "ai"
        score <= HUMAN_THRESHOLD (0.40)   -> "human"
        anything in between               -> "unsure"

    Every float from 0 to 1 hits exactly one branch, so there is no gap.
    """
    if score >= config.AI_THRESHOLD:
        return "ai", LABEL_AI
    if score <= config.HUMAN_THRESHOLD:
        return "human", LABEL_HUMAN
    return "unsure", LABEL_UNSURE


def label_ranges() -> list[tuple[str, str]]:
    """
    The score range each label covers. Your README needs these beside the
    label text — given to you so the numbers can't drift apart from config.py.
    """
    return [
        ("high-confidence human", f"0.00 – {config.HUMAN_THRESHOLD:.2f}"),
        ("unsure", f"{config.HUMAN_THRESHOLD:.2f} – {config.AI_THRESHOLD:.2f}"),
        ("high-confidence AI", f"{config.AI_THRESHOLD:.2f} – 1.00"),
    ]
