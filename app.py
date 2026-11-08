#!/usr/bin/env python3
"""
Provenance Guard — the web service.

    python app.py

Then, in another terminal:

    curl -X POST http://127.0.0.1:5000/ping \
      -H "Content-Type: application/json" \
      -d '{"message": "hello"}'

That's the example route. It works right now, before you've written anything.
**Leave it alone** — it's your control. When something breaks later, check that
`/ping` still answers: if it does, the problem is in your handler; if it
doesn't, it's the service itself.

Routes:

    POST /ping        the worked example. Already works. Don't edit it
    POST /submit      text + creator_id in -> guess, confidence, label out
    POST /appeal      content_id + reasoning in -> status moves to under_review
    GET  /content/<id>  one item's current status (stretch)
    GET  /log         the audit log. Already works
    GET  /health      is the service up, and is the model loaded
"""

import uuid

from flask import Flask, jsonify, request

import audit
import config
import detector
import scoring
import stylometry

app = Flask(__name__)


# ── Rate limiting — UNIT 8 ────────────────────────────────────────────────────
# Off until you turn it on. In unit 8, Milestone 1:
#
#   1. Set RATE_LIMITING_ENABLED = True in config.py (or AI201_RATE_LIMITS=1)
#   2. Choose your numbers there
#   3. Uncomment the @limiter.limit(...) line on /submit below
#
# The order doesn't matter. While limiting is off, that decorator is a no-op
# that quietly does nothing, so uncommenting it early costs you nothing — but
# it also means no 429 until you've done step 1.
#
# The storage backend is preconfigured, which stops Flask-Limiter printing a
# warning on every start. In-memory is right for one laptop and wrong for
# anything real — a restart forgets every count.

class _LimiterOff:
    """
    Stands in for the real limiter while rate limiting is off.

    It makes @limiter.limit(...) a decorator that returns the route
    untouched, so uncommenting the line before you flip the setting is
    harmless instead of a crash on startup.
    """

    def limit(self, *args, **kwargs):
        return lambda view: view


limiter = _LimiterOff()
if config.RATE_LIMITING_ENABLED:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    def rate_limit_key():
        """
        Who a request counts against.

        Falling back to the caller's address is the easy version. Unit 8's
        stretch asks about per-creator limits instead — and the difference
        matters: one script can look like a thousand callers, and one household
        can look like one.
        """
        payload = request.get_json(silent=True)
        # A body that parses as JSON but isn't an object — a bare list or
        # string — has no .get. Without this guard the key function raises
        # BEFORE the route runs, and a malformed request becomes a 500 that
        # looks like your handler crashed when your handler never ran.
        if not isinstance(payload, dict):
            return get_remote_address()
        creator = payload.get("creator_id")
        return creator if isinstance(creator, str) and creator.strip() else get_remote_address()

    limiter = Limiter(
        key_func=rate_limit_key,
        app=app,
        storage_uri=config.RATE_LIMIT_STORAGE,
        default_limits=[],
    )

    @app.errorhandler(429)
    def rate_limited(exc):
        """
        A rejected request still leaves a trace.

        ⚠️ An attack that shows up only as an absence is one you'll never find.
        """
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        audit.log_rejection(
            creator_id=payload.get("creator_id", "unknown"),
            reason="rate_limited",
            limit=str(exc.description),
        )
        return jsonify({
            "error": "rate_limited",
            "message": "Too many submissions. Try again shortly.",
            "limit": str(exc.description),
        }), 429


# ── The worked example. Already works. Don't edit. ────────────────────────────

@app.post("/ping")
def ping():
    """
    Everything a route needs, in six lines.

    JSON arrives as a dict. You pull things out of it. You return a dict and
    the framework turns it into a response. That's the whole idea.
    """
    payload = request.get_json(silent=True) or {}
    return jsonify({
        "ok": True,
        "you_sent": payload.get("message"),
        "service": "provenance-guard",
    })


@app.get("/health")
def health():
    """Is the service up, and has the model been downloaded yet?"""
    import detector

    loaded = detector._model is not None
    return jsonify({
        "ok": True,
        "detector_model": config.DETECTOR_MODEL,
        "detector_loaded": loaded,
        "rate_limiting": config.RATE_LIMITING_ENABLED,
        "log_entries": len(audit.read_entries()),
    })


# ── The service ────────────────────────────────────────────────────────────

@app.post("/submit")
# @limiter.limit(f"{config.RATE_LIMIT_PER_MINUTE}/minute;{config.RATE_LIMIT_PER_DAY}/day")
def submit():
    """
    Take a piece of text, decide about it, log the decision, answer.

    Expects JSON:
        {"text": "...", "creator_id": "..."}

    Returns 200 with:
        {"content_id", "creator_id", "guess", "confidence", "label",
         "model_score", "style_score", "status"}

    `confidence` is the combined 0-1 score from scoring.combine_signals:
    how strongly the evidence points to AI (0 = confidently human,
    1 = confidently AI).

    Bad input never reaches the signals. It gets a 4xx with an `error` code
    and a plain-English `message`, and a `rejected` entry in the audit log:

        400 invalid_json       body isn't a JSON object
        400 missing_text       no `text`, or it isn't a string
        400 empty_text         `text` is only whitespace
        400 missing_creator    no `creator_id`, or it isn't a non-empty string
        413 text_too_long      more than MAX_CHARS characters
        422 text_too_short     fewer than MIN_WORDS words
        503 detector_unavailable   the model couldn't be loaded
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _reject("unknown", "invalid_json",
                       'Send a JSON object like {"text": "...", "creator_id": "..."}.', 400)

    creator_id = payload.get("creator_id")
    has_creator = isinstance(creator_id, str) and bool(creator_id.strip())
    creator_for_log = creator_id if has_creator else "unknown"
    text = payload.get("text")

    if not isinstance(text, str):
        return _reject(creator_for_log, "missing_text",
                       "The request needs a `text` field containing the writing to check.", 400)
    if not text.strip():
        return _reject(creator_for_log, "empty_text",
                       "The `text` field is empty. There's nothing to check.", 400)
    if not has_creator:
        return _reject("unknown", "missing_creator",
                       "The request needs a `creator_id` field saying who wrote this.", 400)
    if len(text) > config.MAX_CHARS:
        return _reject(creator_id, "text_too_long",
                       f"That's {len(text):,} characters. The limit is {config.MAX_CHARS:,}. "
                       f"Try submitting it in parts.", 413, text_length=len(text))

    n_words = len(stylometry.words(text))
    if n_words < config.MIN_WORDS:
        return _reject(creator_id, "text_too_short",
                       f"That's {n_words} words. We need at least {config.MIN_WORDS} "
                       f"to say anything useful about it.", 422, text_length=len(text))

    try:
        model_score = detector.model_signal(text)
    except detector.DetectorUnavailable as exc:
        return _reject(creator_id, "detector_unavailable",
                       "The checker isn't available right now. Please try again later.",
                       503, detail=str(exc)[:200])
    except ValueError:
        return _reject(creator_id, "text_too_short",
                       "That text is too short to check. A few sentences at least.", 422)

    style_score = stylometry.style_signal(text)
    combined = scoring.combine_signals(model_score, style_score)
    guess, label = scoring.score_to_label(combined)

    content_id = uuid.uuid4().hex[:12]
    audit.log_decision(
        content_id=content_id,
        creator_id=creator_id,
        guess=guess,
        model_score=model_score,
        style_score=style_score,
        combined_score=combined,
        label=label,
        status="decided",
        text_length=len(text),
    )

    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        "guess": guess,
        "confidence": combined,
        "label": label,
        "model_score": model_score,
        "style_score": style_score,
        "status": "decided",
    })


def _reject(creator_id, reason, message, status_code, **extra):
    """Refuse a request, and leave a trace of it in the audit log."""
    audit.log_rejection(creator_id=creator_id, reason=reason, http_status=status_code, **extra)
    return jsonify({"error": reason, "message": message}), status_code


def _current_state(content_id):
    """(decision entry, latest status) for a content_id, or (None, None)."""
    entries = audit.entries_for(content_id)
    decision = next((e for e in entries if e.get("event") is None and e.get("guess")), None)
    if decision is None:
        return None, None
    return decision, entries[-1].get("status", decision.get("status"))


@app.post("/appeal")
def appeal():
    """
    A writer says we got it wrong.

    Expects JSON:
        {"content_id": "...", "reasoning": "..."}

    Records the appeal next to the original decision in the audit log, moves
    the item to `under_review`, and confirms. No automatic re-checking.

        400 invalid_json / missing_content_id / missing_reasoning
        404 unknown_content_id     no decision with that id
        409 already_under_review   this item already has an open appeal
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_json",
                        "message": 'Send a JSON object like {"content_id": "...", "reasoning": "..."}.'}), 400

    content_id = payload.get("content_id")
    reasoning = payload.get("reasoning")

    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "missing_content_id",
                        "message": "The request needs the `content_id` you got back when you submitted."}), 400
    if not isinstance(reasoning, str) or not reasoning.strip():
        return jsonify({"error": "missing_reasoning",
                        "message": "Tell us in a sentence or two why you think the result is wrong."}), 400

    content_id = content_id.strip()
    decision, status = _current_state(content_id)
    if decision is None:
        return jsonify({"error": "unknown_content_id",
                        "message": f"We couldn't find a submission with id '{content_id}'. "
                                   f"Check it matches the content_id from your submission."}), 404
    if status == "under_review":
        return jsonify({"error": "already_under_review",
                        "content_id": content_id,
                        "status": status,
                        "message": "This item is already waiting for a person to review it."}), 409

    audit.log_appeal(content_id=content_id,
                     creator_id=decision.get("creator_id", "unknown"),
                     reasoning=reasoning.strip()[:5000])

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "original_guess": decision.get("guess"),
        "original_confidence": decision.get("combined_score"),
        "message": "Thanks. Your appeal has been recorded and a person will review "
                   "this item. Until then it is marked as under review, not as AI-written.",
    })


@app.get("/content/<content_id>")
def get_content(content_id):
    """One item's current status and its history (stretch feature)."""
    decision, status = _current_state(content_id)
    if decision is None:
        return jsonify({"error": "unknown_content_id",
                        "message": f"No submission with id '{content_id}'."}), 404
    appeals = [e for e in audit.entries_for(content_id) if e.get("event") == "appeal"]
    return jsonify({
        "content_id": content_id,
        "creator_id": decision.get("creator_id"),
        "status": status,
        "guess": decision.get("guess"),
        "confidence": decision.get("combined_score"),
        "label": decision.get("label"),
        "model_score": decision.get("model_score"),
        "style_score": decision.get("style_score"),
        "submitted_at": decision.get("timestamp"),
        "appeals": [{"timestamp": a.get("timestamp"), "reasoning": a.get("reasoning")}
                    for a in appeals],
    })


# ── Already works ─────────────────────────────────────────────────────────────

@app.get("/log")
def get_log():
    """
    The audit log, most recent last.

        curl "http://127.0.0.1:5000/log?limit=10"

    You need this in unit 8 to paste entries into your README, and you need it
    now to see whether your logging is actually working.
    """
    limit = request.args.get("limit", type=int)
    entries = audit.read_entries(limit=limit)
    return jsonify({"count": len(entries), "entries": entries})


def main():
    print(f"Provenance Guard on http://{config.HOST}:{config.PORT}")
    print(f"  detector model:  {config.DETECTOR_MODEL}")
    print(f"  rate limiting:   {'ON' if config.RATE_LIMITING_ENABLED else 'off (unit 8)'}")
    print(f"  audit log:       {config.AUDIT_LOG}")
    print()
    print("Check it's alive:")
    print(f'  curl -X POST http://{config.HOST}:{config.PORT}/ping \\')
    print('    -H "Content-Type: application/json" \\')
    print("    -d '{\"message\": \"hello\"}'")
    print()
    # debug=True hands out an interactive debugger, so it's local-only — see config.py
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)


if __name__ == "__main__":
    main()
