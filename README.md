# Provenance Guard

> ### 👋 Start here
>
> **New to this repo? Read [RUNNING.md](RUNNING.md) first.**
>
> Once `python test.py` passes, in one terminal:
>
> ```bash
> python app.py
> ```
>
> and in another:
>
> ```bash
> curl -X POST http://127.0.0.1:5000/ping \
>   -H "Content-Type: application/json" \
>   -d '{"message": "hello"}'
> ```
>
> That's a web service. Something sent it text and it sent something back.
> Everything this unit is filling in the middle.
>
> **The rest of this file is your submission.** Fill it in as you go.

---

<!-- ─────────────────────────────────────────────────────────────────────────
     Unit 7 asks for the first five sections. Unit 8 adds the five below.

     Everything is pasted as TEXT. A pasted curl response gets full credit;
     a picture of your terminal gets none.
     ───────────────────────────────────────────────────────────────────────── -->

<!-- ═══════════════════════ UNIT 7 — THE BUILD ═══════════════════════ -->

## What This Does

Provenance Guard takes a piece of writing and tells the reader, in plain words, whether it looks human-written, AI-written, or too close to call. The writer can appeal the result. A submission goes through these steps:

1. **Arrives at `POST /submit`** (`app.py::submit`) as JSON with `text` and `creator_id`.
2. **Gets validated.** The route checks the input before any model runs. A body that isn't JSON, a missing or empty `text`, a missing `creator_id`, fewer than 20 words or more than 20,000 characters gets a 4xx with a plain-English message. The refusal is logged as a `rejected` entry so it still leaves a trace.
3. **Signal one, the model signal** (`detector.py::model_signal`). GPT-2 runs locally and measures how predictable the text is (perplexity), returning 0–1 where higher means more AI-like.
4. **Signal two, the style signal** (`stylometry.py::style_signal`). This looks only at the shape of the text: how much sentence length varies, how much vocabulary repeats, and how much varied punctuation it uses. It also returns 0–1 where higher means more AI-like.
5. **The two are combined into one confidence score** (`scoring.py::combine_signals`). It takes a 60/40 weighted average, and when the two signals disagree it pulls the score back toward 0.5.
6. **The score becomes a label** (`scoring.py::score_to_label`). The score falls into one of three bands, and each band has a full-sentence label written for the writer.
7. **The decision is logged and returned.** `audit.py` appends the content id, creator id, guess, both signal scores, the combined score, the label and `status: "decided"` to `logs/audit.jsonl`. The response carries the same fields plus a `content_id`.

If the writer disagrees, they send that `content_id` and their reasoning to **`POST /appeal`**. The appeal is appended to the log next to the original decision and the item's status moves to `under_review`. `GET /content/<id>` (stretch) shows an item's current status.

**Stretch feature:** `GET /content/<id>` returns one item's current status (`decided` or `under_review`), its scores, and any appeals.

---

## Signals and Scoring

### Signal one — the model signal

`detector.py::model_signal`

**What it measures:** How predictable the text is to GPT-2, which runs locally. The signal is perplexity (how surprised the model is by each next word), mapped onto 0–1 with a logistic curve so that low perplexity gives a high AI score.

**Why that might differ between human and AI writing:** A language model writes by repeatedly picking a likely next word, so text a model produced tends to be text a model finds easy to predict. People make odder word choices and take more abrupt turns.

**What it can't see:** Authorship. It rewards common words in short, ordinary sentences, and plenty of people write that way: second-language writers, younger writers, anyone writing plainly on purpose. My plain, ESL-style test paragraph had a perplexity of 15, close to the 6–12 of my clearest AI samples. The reverse also fails: rare words and ornate prose read as human whoever wrote them.

**Calibration change:** I moved the logistic midpoint from the starter's perplexity 45 to **30**, and the steepness from 1.6 to **2.0**. At 45, every human sample I tried except two scored above 0.5 on this signal. That's because GPT-2 perplexity on short paragraphs runs low: 24–42 for most of my human samples. At 30, Twain (perplexity 42) reads as human, and no human sample moved toward AI.

### Signal two — the style signal

`stylometry.py::style_signal`

**What it measures:** The shape of the text, without reading it. It uses three measures, each mapped to 0–1 AI-ness by a logistic curve and then combined as a weighted average:

| Measure | What it computes | Curve (midpoint, scale) | Weight |
|---|---|---|---|
| Sentence-length spread | stdev ÷ mean of words per sentence | 0.35, 0.10 | **0.6** |
| Word variety | moving-average type-token ratio over 50-word windows (MATTR), so length matters less | 0.85, 0.05 | 0.2 |
| Punctuation | commas, semicolons, dashes, brackets, quotes, ! and ? per word, × variety of kinds used (full stops excluded) | 0.05, 0.02 | 0.2 |

All three raw measures point "higher = more human" and get flipped. A single-sentence submission has no spread, so that measure counts as neutral (0.5), not as AI-like.

**Why that might differ between human and AI writing:** Generated prose tends toward even, mid-length sentences. Human writing is lumpier, with a three-word sentence next to a forty-word one.

**What it can't see:** Meaning. Anything that changes the shape without changing the substance moves it: chopping or merging sentences, adding a quotation, sprinkling in dashes. It is also cheap to game on purpose. It shares signal one's blind spot too, because a careful writer who keeps sentences short and even looks machine-like on both.

**What calibration showed:** Across 14 test paragraphs (6 AI-style, 8 human), **only sentence spread separated the two groups**. AI samples fell at 0.19–0.43 and most human samples at 0.36–0.73. Word variety did not separate them at all: AI samples were at 0.88–0.95, human ones at 0.68–0.95, and AI text was often *more* varied. Punctuation overlapped completely (AI 0.026–0.127, human 0.011–0.097). That's why spread carries 0.6 of the weight. I kept the other two at low weight rather than dropping them, and I record this as a finding: two of my three style measures barely discriminate.

### The combining rule

**The rule:** A weighted average that favours the model signal. When the two signals disagree by more than 0.35, the result is pulled halfway back toward 0.5, because two methods contradicting each other means "unsure", not a confident verdict carried by the louder one.

```
avg = 0.6 × model_score + 0.4 × style_score
if |model_score − style_score| > 0.35:
    score = 0.5 + (avg − 0.5) × 0.5
else:
    score = avg
```

**The numbers:** `WEIGHT_MODEL_SIGNAL = 0.6`, `WEIGHT_STYLE_SIGNAL = 0.4`, `DISAGREEMENT_GAP = 0.35`, `DISAGREEMENT_SHRINK = 0.5`, all in `config.py`. The model signal gets more weight because it separated my samples further apart and is harder to move on purpose than sentence shapes.

One property of this rule: **a split can never produce the AI label.** After a split, reaching 0.70 needs an average of at least 0.90, and that isn't possible with a gap over 0.35. Both signals have to agree before anyone is told their work looks AI-written.

**Where it lives:** `scoring.py::combine_signals`

**A case where my two signals split, and what my rule does with it:** On a generic AI paragraph about exercise, the model signal was **0.909** (perplexity 9) but the style signal was only **0.477**, because its sentence lengths happened to vary (spread 0.35). The gap of 0.43 is over 0.35, so the average of 0.736 is pulled back to **0.618, "unsure"**. Without the rule it would have been labelled AI. That is correct for this text, but the same rule protects a human writer whose prose happens to be predictable. I chose to let this AI text through as "unsure" rather than accuse on one signal alone.

**Calibration summary (combined score):** The six AI samples averaged **0.64** (range 0.50–0.84). The seven human samples, not counting the ESL-style one, averaged **0.37** (range 0.08–0.57). The ESL-style human paragraph scored **0.835 and was labelled AI**. Both signals agree it's machine-like, so the disagreement rule can't help it. This is the false positive I traced in Milestone 1, and I couldn't remove it by tuning: any setting that clears it also makes the AI label almost unreachable. The appeal path is what stands between that writer and a wrong accusation (see Sample Run).

---

## Label Variants

| Label | Score range | The exact text a reader sees |
|---|---|---|
| high-confidence human | 0.00 – 0.40 | We think this was probably written by a person. Our automated check found no strong signs of AI writing. |
| unsure | above 0.40, below 0.70 | We can't tell whether this was written by a person or with an AI tool. This is not an accusation: plenty of genuine writing lands here, and no action has been taken. If you'd like a person to look at it, you can ask for a review. |
| high-confidence AI | 0.70 – 1.00 | This looks like it was likely produced with an AI writing tool. Our automated check is fairly confident, but it can be wrong. If you wrote this yourself, you can ask for a person to review it. |

`scoring.py::score_to_label` checks `>= 0.70` first, then `<= 0.40`, and everything else is "unsure", so every score from 0 to 1 maps to exactly one label. The bands are deliberately asymmetric. The AI band starts 0.20 above the midpoint and the human band only 0.10 below it, because accusing a real writer costs more than missing some AI text. All three were reached through the live route: work email → human (0.08), casual note → unsure (0.48), generic AI paragraph → AI (0.78).

> **Updated in unit 8:** `AI_THRESHOLD` is now **0.75**, so "unsure" is 0.40–0.75 and "high-confidence AI" is 0.75–1.00. The ranges above are as they were in unit 7. See The Improvement for why this changed and what it cost.

**Why I worded the "unsure" one this way:** Someone reading it may well have written every word, so it says outright that it is *not* an accusation and that nothing has happened to their work. It says "plenty of genuine writing lands here" so the writer doesn't read it as a polite way of saying "AI". It offers a review as an option, not a demand. The AI label also says "it can be wrong" and points to the appeal, because my own calibration showed it is wrong for plain human writing.

---

## Sample Run

This is the false-positive case from Milestone 1: a plain, second-language-style paragraph that a person wrote, labelled AI, then appealed.

**A submission**

```bash
$ curl -X POST http://127.0.0.1:5000/submit \
  -H "Content-Type: application/json" \
  -d '{"text": "I work in a restaurant in the city. Every day I start at eight in the morning. First I clean the tables and then I help in the kitchen. The work is hard but I like my team. My manager is a good person and she helps me learn English. On weekends I go to the park with my family. I want to study computer science in the future.", "creator_id": "writer_042"}'
```

```json
{
    "confidence": 0.8352,
    "content_id": "86488e813d39",
    "creator_id": "writer_042",
    "guess": "ai",
    "label": "This looks like it was likely produced with an AI writing tool. Our automated check is fairly confident, but it can be wrong. If you wrote this yourself, you can ask for a person to review it.",
    "model_score": 0.7991,
    "status": "decided",
    "style_score": 0.8894
}
```

**An appeal**

```bash
$ curl -X POST http://127.0.0.1:5000/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "86488e813d39", "reasoning": "I wrote this myself for my English class. I use short sentences because English is my second language."}'
```

```json
{
    "content_id": "86488e813d39",
    "message": "Thanks. Your appeal has been recorded and a person will review this item. Until then it is marked as under review, not as AI-written.",
    "original_confidence": 0.8352,
    "original_guess": "ai",
    "status": "under_review"
}
```

A second appeal on the same id returns `409 {"error": "already_under_review", ...}`. An unknown id returns `404 {"error": "unknown_content_id", ...}`.

**What the log shows afterwards**

```bash
$ curl "http://127.0.0.1:5000/log?limit=2"
```

```json
{
    "count": 2,
    "entries": [
        {
            "combined_score": 0.8352,
            "content_id": "86488e813d39",
            "creator_id": "writer_042",
            "guess": "ai",
            "label": "This looks like it was likely produced with an AI writing tool. Our automated check is fairly confident, but it can be wrong. If you wrote this yourself, you can ask for a person to review it.",
            "model_score": 0.7991,
            "status": "decided",
            "style_score": 0.8894,
            "text_length": 325,
            "timestamp": "2026-11-08T17:10:53+00:00"
        },
        {
            "content_id": "86488e813d39",
            "creator_id": "writer_042",
            "event": "appeal",
            "reasoning": "I wrote this myself for my English class. I use short sentences because English is my second language.",
            "status": "under_review",
            "timestamp": "2026-11-08T17:11:00+00:00"
        }
    ]
}
```

The original decision is untouched. The appeal is appended after it with `status: "under_review"`.

**Current status (stretch: `GET /content/<id>`)**

```bash
$ curl http://127.0.0.1:5000/content/86488e813d39
```

```json
{
    "appeals": [
        {
            "reasoning": "I wrote this myself for my English class. I use short sentences because English is my second language.",
            "timestamp": "2026-11-08T17:11:00+00:00"
        }
    ],
    "confidence": 0.8352,
    "content_id": "86488e813d39",
    "creator_id": "writer_042",
    "guess": "ai",
    "label": "This looks like it was likely produced with an AI writing tool. Our automated check is fairly confident, but it can be wrong. If you wrote this yourself, you can ask for a person to review it.",
    "model_score": 0.7991,
    "status": "under_review",
    "style_score": 0.8894,
    "submitted_at": "2026-11-08T17:10:53+00:00"
}
```

**Bad input.** Each of these gets a 4xx and a `rejected` entry in the log, never a 500:

| Request | Response |
|---|---|
| `{"text": "", "creator_id": "x"}` | `400 empty_text` |
| `{"creator_id": "x"}` or `"text": null` | `400 missing_text` |
| `{"text": "..."}` with no creator_id | `400 missing_creator` |
| body not a JSON object / not JSON | `400 invalid_json` |
| `"text": "too short here"` (under 20 words) | `422 text_too_short` |
| `"text": "word " * 50000` (over 20,000 chars) | `413 text_too_long` |

---

## How I Used AI

I used Claude Code (an AI coding assistant) for the implementation. I gave it the project brief and it wrote the style signal, the scoring, the routes and the calibration scripts. These are the two moments where what came back had to change.

**Moment 1: calibrating the style signal**

- *What I asked for:* A style signal built from the three measures in the brief (sentence-length spread, word variety, punctuation density), each mapped onto 0–1 and combined, then run on the four Milestone 4 calibration inputs.
- *What came back:* A first version with guessed midpoints. Word variety and punctuation each had 25% of the weight, and both assumed "higher = more human". On the first run, the plain ESL-style human paragraph scored 0.834 (AI), and the style signal read almost everything as AI-like.
- *What I changed:* We widened the test set to 14 paragraphs (6 AI-style, 8 human) and printed every measure side by side. Word variety turned out *higher* on AI text, the opposite of the brief's hint, and punctuation overlapped completely. Sentence spread was the only measure that separated the groups. So spread went up to 0.6 of the style weight, the other two were centred so they barely move the score, and this is written up as a finding, not hidden. The ESL false positive survived every setting, so it's documented as a known failure, and it's the case the Sample Run appeals.

**Moment 2: the detector's midpoint and the combining rule**

- *What I asked for:* A combining rule for `scoring.py::combine_signals`, plus a check of whether the starter's detector settings fit my test texts.
- *What came back:* With the starter's perplexity midpoint of 45, every human sample except two scored above 0.5 on the model signal. A plain weighted average would also have labelled a generic AI paragraph "AI" on the model signal alone (model 0.909, style 0.477).
- *What I changed:* We compared midpoints of 45, 30 and 25 on the same 14 samples and chose 30 (steepness 2.0). At 30, Twain moved to "human" and nothing moved toward AI. We kept the disagreement rule (a gap over 0.35 pulls the score halfway to 0.5), knowing it lets that AI paragraph through as "unsure". That's deliberate: the same rule stops a single signal from accusing a human writer. The thresholds were left asymmetric (0.40 / 0.70) for the same reason.

**Unit 8: testing with Claude Code**

Claude Code turned on the rate limiter, wrote `scenarios.py`, extended `run_eval.py` (appeal sequences, response timing, a check that each refusal reached the log), and ran the flood test, the attack set and the criteria before and after. It also drafted the held/broke marks, the diagnoses and this write-up. Three moments where what came back had to change:

- **My own writing.** Criterion 1 needs ten pieces of my writing, and I didn't supply them. Claude declined to write ten pieces and present them as mine. Instead it used ten public-domain passages from Project Gutenberg, picked by a fixed rule before scoring, and recorded the substitution under criterion 1 in `criteria.md`. Criterion 1's MET is weaker than it looks because of this.
- **A claim that didn't survive the data.** The first draft of the criterion 3 diagnosis said the two lowest style scores in the run both came from texts with a short fragment. Checking the numbers showed three human passages scored lower than the second one, so the sentence was rewritten to the claim the data does support.
- **The fix.** The attack diagnoses pointed mostly at signal two, so fixing it was the obvious move. An offline what-if on the before-run data showed that fix would have accused six human writers, so the change became the threshold instead. Separately, the first "after" attack run hit a stale server still running the old threshold. FP05 still coming back `ai` gave it away, and the run was redone (see The Improvement).

The diagnoses above were drafted by Claude from the logged scores and the attack texts.

<!-- ═══════════════════════ UNIT 8 — THE TEST ═══════════════════════ -->

---

## Rate Limiting

**My limits:** 6 per minute, 60 per day (`config.py`: `RATE_LIMIT_PER_MINUTE`, `RATE_LIMIT_PER_DAY`; decorator on `app.py::submit`)

**Why those numbers and not others:**

- **A real writer** checks a piece, edits it, and checks again. Even a fast "fix a sentence, resubmit" loop rarely goes past three or four in a minute, so 6 leaves headroom. 60 a day covers someone checking every draft of several pieces. Nobody needs 200.
- **A script mapping my thresholds** needs hundreds to thousands of variations to find where 0.40 and 0.70 sit. At 60 a day per identity, 1,000 probes take 17 days. At the starter's 10/200 it would take 5. Going lower than 6/minute starts to catch a writer who pastes, spots a typo and resubmits straight away, so I stopped at 6.
- What it doesn't stop: a script that makes up a new `creator_id` for every request. See below.

**What a caller counts as:** The `creator_id` in the body (`app.py::rate_limit_key`), falling back to the IP address when there isn't a usable one. Per-creator means one household sharing an address doesn't share a budget. The cost is that `creator_id` is self-reported, so one script inventing a thousand ids looks like a thousand writers and is never limited. A real deployment would key on an authenticated account and keep a per-address ceiling as a backstop.

**The run of status codes when I pushed past it:**

<!-- python run_attacks.py --flood 15 -->

```
$ python run_attacks.py --flood 15
200 200 200 200 200 200 429 429 429 429 429 429 429 429 429

9 of 15 were rate limited.
Wrote results\flood_2026-11-12_1426.md
```

Each 429 left a trace in `logs/audit.jsonl`:

```json
{"timestamp": "2026-11-12T19:26:49+00:00", "creator_id": "flood_tester", "event": "rejected", "status": "rejected", "reason": "rate_limited", "limit": "6 per 1 minute"}
```

---

## Attack Run — Before

`python run_attacks.py --set attack_set --label before`, giving `results/attack_run_2026-11-13_0051_before.md`, with nothing changed since the criteria runs. Full JSON for every attack is in that file; the audit log for the run is in `results/audit_extract_before.json`.

**How I marked them.** An attack **BROKE** if it got what it was going for:
- **evasion:** AI text that came back anything other than `ai`. "Unsure" counts as broke, because that label says "no action has been taken".
- **false_positive:** human text labelled `ai`.
- **prompt_injection:** AI text not labelled `ai`; or, for PI04 and PI05, hostile label text or a corrupted log line.
- **malformed:** a 5xx, a crash, or no answer.
- **flood:** no 429 at all.

Everything else **HELD**.

| ID | Targeting | Status | Guess | Score | Model | Style | Verdict |
|---|---|---|---|---|---|---|---|
| EV01 | signal two: typos raise word variety | 200 | unsure | 0.408 | 0.055 | 0.708 | **BROKE** |
| EV02 | signal two: broken-up sentences raise length spread | 200 | human | 0.340 | 0.417 | 0.223 | **BROKE** |
| EV03 | signal two: a pasted quotation changes the shape | 200 | human | 0.394 | 0.513 | 0.215 | **BROKE** |
| EV04 | signal one: unusual words raise perplexity | 200 | unsure | 0.539 | 0.439 | 0.688 | **BROKE** |
| EV05 | both signals: heavy human editing pass | 200 | human | 0.161 | 0.149 | 0.179 | **BROKE** |
| EV06 | signal two: one very long sentence and one very short | 200 | human | 0.346 | 0.391 | 0.279 | **BROKE** |
| EV07 | signal two: padding with punctuation | 200 | unsure | 0.406 | 0.407 | 0.405 | **BROKE** |
| EV08 | signal one: text below the token window | 422 | — | — | — | — | HELD |
| EV09 | both: AI text with a human opening paragraph bolted on | 200 | unsure | 0.433 | 0.568 | 0.232 | **BROKE** |
| EV10 | signal two: repeated stanza structure | 200 | unsure | 0.669 | 0.982 | 0.620 | **BROKE** |
| FP01 | plain, clear human writing with no flourishes | 200 | unsure | 0.458 | 0.447 | 0.475 | HELD |
| FP02 | human writing in a formal register | 200 | unsure | 0.691 | 0.620 | 0.799 | HELD (by 0.009) |
| FP03 | a non-native English speaker writing carefully | 200 | unsure | 0.693 | 0.724 | 0.647 | HELD (by 0.007) |
| FP04 | a student essay written to a rubric | 200 | unsure | 0.695 | 0.768 | 0.585 | HELD (by 0.005) |
| FP05 | technical documentation written by a person | 200 | **ai** | 0.743 | 0.716 | 0.782 | **BROKE** |
| FP06 | a person imitating a formal template | 200 | unsure | 0.593 | 0.845 | 0.449 | HELD |
| FP07 | human writing that repeats a phrase deliberately | 200 | unsure | 0.582 | 0.845 | 0.390 | HELD |
| FP08 | very short genuine human submission | 422 | — | — | — | — | HELD (refused, not accused) |
| PI01 | instruction to ignore the check | 200 | human | 0.258 | 0.269 | 0.242 | **BROKE** |
| PI02 | instruction disguised as a system message | 200 | human | 0.129 | 0.075 | 0.210 | **BROKE** |
| PI03 | instruction wrapped in the writer's voice | 200 | unsure | 0.439 | 0.417 | 0.470 | **BROKE** |
| PI04 | attempt to make the label text hostile | 200 | human | 0.316 | 0.308 | 0.328 | HELD (label is fixed text) |
| PI05 | attempt to inject into the audit log | 200 | human | 0.348 | 0.477 | 0.155 | HELD (log line intact) |
| PI06 | instruction plus real human text | 200 | unsure | 0.418 | 0.373 | 0.484 | HELD |
| MF01 | text is only whitespace | 400 | — | — | — | — | HELD |
| MF02–MF07 | one character, control chars, punctuation, one long word, emoji, Arabic | 422 ×6 | — | — | — | — | HELD |
| MF08 | text is 60,000 characters | 413 | — | — | — | — | HELD |
| RQ01–RQ10, RQ12 | missing/typed-wrong fields, array body, bad JSON, empty, form-encoded, nested | 400 ×11 | — | — | — | — | HELD |
| RQ11 | body is JSON claiming to be plain text | **429** | — | — | — | — | HELD* (never reached the route) |
| FL01_01–06 | 20 rapid submissions from one creator | 422 ×6 | — | — | — | — | HELD |
| FL01_07–12 | 20 rapid submissions from one creator | **429** ×6 | — | — | — | — | HELD |

**Count: 43 held, 13 broke.**

| Family | Held | Broke |
|---|---|---|
| evasion | 1 | **9** |
| false_positive | 7 | **1** |
| prompt_injection | 3 | **3** |
| malformed | 20 | 0 |
| flood_same_creator | 12 | 0 |

No input crashed the service; every refusal was a 4xx with an `error` code. Three notes:
- **RQ11 never reached my route.** Its body is JSON sent as `text/plain`, so Flask doesn't parse it. The limiter then can't see the `creator_id` and keys the request on the IP address, which the six earlier body-less malformed rows had already used up. The 429 was right, but it means this run didn't test what my route does with that body. As a side effect, the 429's log entry says `creator_id: "unknown"` even though the body named `attacker_RQ11`.
- **FL01:** the flood rows are 9 words, so the first six got 422 (too short), and the limiter cut in at the 7th. Refused requests still count against the limit, which is what you want.
- **FP08** ("Went for a run. Legs hurt. Worth it.") wasn't accused, but a real writer was refused. `MIN_WORDS = 20` buys reliability at that cost.

**Eleven audit log entries from the run** (from `logs/audit.jsonl`; `label` shortened where marked …). Two are rate-limit rejections and one is a 413:

```json
{"timestamp": "2026-11-13T05:51:50+00:00", "content_id": "d3567b65254e", "creator_id": "attacker_FP05", "guess": "ai", "model_score": 0.7163, "style_score": 0.7818, "combined_score": 0.7425, "label": "This looks like it was likely produced with an AI writing tool. Our automated check is fairly confident, but it can be wrong. If you wrote this yourself, you can ask for a person to review it.", "status": "decided", "text_length": 393}
{"timestamp": "2026-11-13T05:51:49+00:00", "content_id": "8788e19cfca3", "creator_id": "attacker_FP03", "guess": "unsure", "model_score": 0.7235, "style_score": 0.6471, "combined_score": 0.6929, "label": "We can't tell whether this was written by a person or with an AI tool. This is not an accusation…", "status": "decided", "text_length": 418}
{"timestamp": "2026-11-13T05:51:45+00:00", "content_id": "349521fddf83", "creator_id": "attacker_EV01", "guess": "unsure", "model_score": 0.0546, "style_score": 0.7081, "combined_score": 0.408, "label": "We can't tell whether this was written by a person or with an AI tool. This is not an accusation…", "status": "decided", "text_length": 657}
{"timestamp": "2026-11-13T05:51:45+00:00", "content_id": "e5a75c183554", "creator_id": "attacker_EV02", "guess": "human", "model_score": 0.4173, "style_score": 0.2229, "combined_score": 0.3395, "label": "We think this was probably written by a person. Our automated check found no strong signs of AI writing.", "status": "decided", "text_length": 708}
{"timestamp": "2026-11-13T05:51:48+00:00", "content_id": "9017ebdcd376", "creator_id": "attacker_EV10", "guess": "unsure", "model_score": 0.9821, "style_score": 0.6198, "combined_score": 0.6686, "label": "We can't tell whether this was written by a person or with an AI tool. This is not an accusation…", "status": "decided", "text_length": 544}
{"timestamp": "2026-11-13T05:51:52+00:00", "content_id": "a88ebbc8c94c", "creator_id": "attacker_PI02", "guess": "human", "model_score": 0.0752, "style_score": 0.2096, "combined_score": 0.129, "label": "We think this was probably written by a person. Our automated check found no strong signs of AI writing.", "status": "decided", "text_length": 322}
{"timestamp": "2026-11-13T05:51:53+00:00", "content_id": "1e0c6ffd463c", "creator_id": "attacker_PI05", "guess": "human", "model_score": 0.4773, "style_score": 0.1551, "combined_score": 0.3484, "label": "We think this was probably written by a person. Our automated check found no strong signs of AI writing.", "status": "decided", "text_length": 213}
{"timestamp": "2026-11-13T05:51:46+00:00", "content_id": "175ac26087e6", "creator_id": "attacker_EV05", "guess": "human", "model_score": 0.1485, "style_score": 0.1793, "combined_score": 0.1608, "label": "We think this was probably written by a person. Our automated check found no strong signs of AI writing.", "status": "decided", "text_length": 460}
{"timestamp": "2026-11-13T05:51:53+00:00", "creator_id": "attacker_MF08", "event": "rejected", "status": "rejected", "reason": "text_too_long", "http_status": 413, "text_length": 57640}
{"timestamp": "2026-11-13T05:51:54+00:00", "creator_id": "attacker_flood", "event": "rejected", "status": "rejected", "reason": "rate_limited", "limit": "6 per 1 minute"}
{"timestamp": "2026-11-13T05:51:54+00:00", "creator_id": "unknown", "event": "rejected", "status": "rejected", "reason": "rate_limited", "limit": "6 per 1 minute"}
```

Why these: FP05 is the one accusation. FP03 is a non-native writer 0.007 from being accused. EV01 shows typos wrecking signal one. EV02 shows fragments wrecking signal two. EV10 is a 0.98 model score rescued by the disagreement rule. PI02 is an injection that "worked" without anything obeying it. PI05 shows the log line survived an injection attempt. EV05 is AI text edited until it's arguably no longer AI text. The last three are refusals, and the final one is RQ11's 429 logged as `unknown`.

**The single worst outcome:** **FP05**, a person's technical documentation ("To configure the service, edit the settings file…"), labelled **AI at 0.7425**. It's the only real writer this run accused. The writer did exactly what good documentation asks for: short, imperative sentences of even length, common words, no flourishes. Both of my signals read that as machine-like (model 0.716, style 0.782), so they agreed, the disagreement rule never engaged, and nothing stood between them and the AI label. I couldn't explain to that writer what they should have done differently, because the honest answer is "write worse documentation". FP02, FP03 and FP04 (formal report, non-native speaker, rubric essay) were within 0.01 of the same fate.


---

## Run Log and Verdicts

<!-- Your five criteria across three trials. `run_eval.py --label before`. -->

**Before** — `results/run_2026-11-12_1438_before.md`, produced by `run_eval.py::main` against `app.py::submit` (`scoring.py::combine_signals`, `scoring.py::score_to_label`). Inputs are in `scenarios.py`.

| Criterion | Target | Run 1 | Run 2 | Run 3 | Verdict |
|---|---|---|---|---|---|
| 1. Human writing flagged as AI | ≤ 1 of 10 labelled AI | 0/10 | 0/10 | 0/10 | MET* |
| 2. AI vs human score gap | AI mean − human mean ≥ 0.30 | 0.48 | 0.48 | 0.48 | MET |
| 3. Labels reachable and correctly placed | all 3 labels seen, ≥ 2 of 3 per group | 2 / **1** / 2 | 2 / **1** / 2 | 2 / **1** / 2 | **MISSED** |
| 4. Appeals change status and are logged | 5/5 real, 3/3 fake → 404 + no entry | 5/5, 3/3 | 5/5, 3/3 | 5/5, 3/3 | MET |
| 5. Bad input → 4xx, logged, < 5 s | 6 of 6 | 6/6 | 6/6 | 6/6 | MET |

All three trials are identical, score for score. Neither signal is random (GPT-2 perplexity is deterministic, the style signal is arithmetic), so that's the expected result, not a skipped step.

**How I decided each verdict:**

1. **MET\*, with a weak test behind it.** 0 of 10 were labelled AI in every trial, and three landed in "unsure" (0.40, 0.44, 0.45). The asterisk: the ten texts are **not my own writing**. They're published human passages from Project Gutenberg, a substitution recorded under criterion 1 in `criteria.md`. Literary prose is the easy case for this detector. The plainest passage (Sherwood Anderson: short, flat sentences) scored highest, at 0.4547 with both signals at about 0.45. That's the same direction as the ESL false positive in the Sample Run. I wouldn't call this criterion settled until it's run on everyday writing.
2. **MET.** AI mean 0.787, human mean 0.305, gap 0.48 against a target of 0.30, in all three trials. Means hide overlap, though: one AI text ("Reading books…") scored 0.631, inside the unsure band.
3. **MISSED.** All three labels appeared, and the human and AI groups each got 2 of 3 right. The borderline group got **1 of 3** "unsure" in every trial. The target needs ≥ 2 in every group. Argued the other way: those borderline texts are AI drafts, so calling them "human" is arguably a missed detection rather than a mislabelled borderline. That isn't more generous, though. It's still a miss.
4. **MET.** 5 of 5 appeals returned 200 and `under_review`, and the log shows `decided` then `appeal` for each id. 3 of 3 made-up ids returned 404 and wrote 0 log entries.
5. **MET.** 6 of 6 returned a 4xx with an `error` code and left a `rejected` log entry. Slowest response: 0.03 s. The 50,000-word body is refused at `MAX_CHARS` before the model runs.

**Real output from trial 1** (`run_eval.py::send_submit` / `run_eval.py::run_appeals`; `label` text shortened):

```json
// Criterion 1: highest-scoring human passage (Anderson, Winesburg, Ohio)
{"status": 200, "content_id": "3136afe00612", "guess": "unsure", "confidence": 0.4547, "model_score": 0.4535, "style_score": 0.4566, "label": "We can't tell whether this was written by a person or with a…", "elapsed_s": 0.51, "log_entry": {"status": "decided", "content_id": "3136afe00612", "guess": "unsure", "combined_score": 0.4547}, "sent": "The two Kings, Edward the father, and Tom the son, were not popular in"}

// Criterion 2: lowest AI text, and the first human text
{"status": 200, "content_id": "06aa53499c57", "guess": "unsure", "confidence": 0.6311, "model_score": 0.5881, "style_score": 0.6955, "sent": "Reading books provides numerous benefits for people of all ages. It ex"}
{"status": 200, "content_id": "8993abcb81ce", "guess": "human", "confidence": 0.3083, "model_score": 0.2571, "style_score": 0.3852, "sent": "We sculled up to Walton, a rather large place for a riverside town. As"}

// Criterion 3: the three borderline inputs (wanted: unsure)
{"status": 200, "content_id": "a10e45723012", "guess": "unsure", "confidence": 0.4038, "model_score": 0.4838, "style_score": 0.2838, "sent": "Remote work has changed a lot about how teams operate. Some people lov"}
{"status": 200, "content_id": "206f00a7ecc6", "guess": "human",  "confidence": 0.2484, "model_score": 0.3425, "style_score": 0.1073, "sent": "Learning a new language takes patience. Lots of it. Most learners star"}
{"status": 200, "content_id": "7f76b3e32c76", "guess": "human",  "confidence": 0.3916, "model_score": 0.449,  "style_score": 0.3055, "sent": "Gardening is often described as relaxing, and for many people it is. B"}

// Criterion 4: one real appeal, one made-up id
{"kind": "real_id", "content_id": "143e23ef0569", "submit_status": 200, "status": 200, "appeal_status_field": "under_review", "log_events_for_id": ["decided", "appeal"]}
{"kind": "fake_id", "content_id": "000000000000", "status": 404, "error": "unknown_content_id", "log_entries_written": 0}

// Criterion 5: the 50,000-word body and the non-object body
{"status": 413, "error": "text_too_long", "elapsed_s": 0.02, "log_entry": {"event": "rejected", "status": "rejected", "reason": "text_too_long"}}
{"status": 400, "error": "invalid_json", "elapsed_s": 0.02, "log_entry": {"event": "rejected", "status": "rejected", "reason": "invalid_json"}, "sent": "[\"this\", \"is\", \"not\", \"an\", \"object\"]"}
```

**Diagnoses**

**Criterion 3 (MISSED): the stage is signal two, and the mechanism is that one fragment sentence reads as "human".** The three borderline inputs are AI drafts I roughed up by putting a two-to-four-word sentence ("Lots of it.", "Some people love it.") next to a 35–40-word one. My style signal gives sentence-length spread 0.6 of its weight, because calibration showed it's the only one of its three measures that separates the groups. A single fragment beside a long sentence sends the spread way up, so the style score drops to 0.11–0.31. The model signal also fell just under 0.5 (0.34–0.48), because the edits made the text a little less predictable. Both signals leaned human, so the gap stayed under 0.35 and the **combining rule's** disagreement clause never fired. The weighted average went straight through: 0.248 for "Learning a new language" and 0.392 for "Gardening". The second one misses only at the **label mapping**, 0.008 under `HUMAN_THRESHOLD = 0.40`. The first is a clear signal-two failure: a style score of 0.107 is the strongest "human" reading in the whole run, earned by one fragment.

**Pattern:** the lowest style score in the whole run, 0.107, belongs to an AI draft, not to any of the ten human passages (the lowest of those is 0.158). One edited fragment made an AI text look more human, by sentence shape, than Kate Chopin. The style signal can be steered by sentence shape alone. That was already listed as its blind spot in Signals and Scoring; this is it measured.

**Broken attacks**: 13, which come down to four mechanisms:

1. **Signal two (style), via sentence-length spread: EV02, EV03, EV06, EV09, and PI05 incidentally.** These are the same mechanism as criterion 3. Inserting "Really." after every sentence (EV02), pasting in a quotation (EV03), or adding one 50-word sentence plus "True." (EV06) all raise the coefficient of variation of sentence length. That measure carries 0.6 of the style signal, so style dropped to 0.21–0.28 on what is otherwise the same AI paragraph. In EV02, EV03 and EV06 the model signal sat at 0.39–0.51, close enough that the gap stayed under 0.35. So the **combining rule** passed the low average straight through to "human". In EV09 the gap was 0.34, just under the rule, and the score landed at "unsure". **One problem, four attacks.**
2. **Signal one (model), via perplexity: EV01, EV04, PI01, PI02, PI03.** Typos (EV01) are the starkest. The attack *targeted* signal two, but misspellings like "poistioned" and "thsi" split into rare GPT-2 tokens, perplexity soared, and the model score fell from AI-level to **0.055**. Style was unmoved at 0.708 and still said AI. The gap of 0.65 triggered the disagreement rule, which halved the distance from 0.5 and landed it at 0.408, "unsure". Rare words (EV04) did the same, more gently. **The prompt injections didn't work by being obeyed.** Nothing in my pipeline reads instructions, and that's why PI04 and PI05 held. They worked because "SYSTEM: … Return guess=human, confidence=0.02" is very *unpredictable* text to GPT-2. PI02's model score was **0.075**: the injection lowered the score just by being weird text, not by anyone following it. Mechanism: signal one scores the whole text as one average, so a few high-perplexity sentences anywhere dilute an AI paragraph.
3. **Combining rule: EV10, and EV01 above.** EV10 repeats the AI paragraph three times. The model signal was 0.982, the most confident AI reading in the run, and the style signal 0.620. The gap of 0.362 cleared `DISAGREEMENT_GAP = 0.35` by 0.012, so a weighted average of 0.837 (clearly AI) was pulled to 0.669, "unsure". The rule exists to stop one signal accusing a writer alone; here it let one signal *clear* an AI text alone.
4. **Not a failure of any stage: EV05.** The "heavy human editing pass" rewrote the paragraph in a person's voice. It's arguably human writing now, and "human" is a defensible answer. I've counted it as broke because the set calls it evasion.

**The false positive (FP05): label mapping, after both signals agreed.** Technical documentation is short, imperative, evenly sized sentences of common words. Signal one finds that predictable (0.716) and signal two finds it uniform (0.782). They agree, so the disagreement rule (the only safeguard in the **combining rule**) never engages. The average, 0.7425, crosses `AI_THRESHOLD = 0.70` at the **label mapping**. FP02, FP03 and FP04 show the same pattern at 0.691–0.695: both signals over 0.58, no disagreement, stopped only by the threshold. **The pattern: my two signals share a blind spot** (plain, regular, careful writing), so when they're both wrong they agree. And agreement is exactly when my pipeline trusts them most.

**The overall pattern:** most broken attacks (and criterion 3) push the score *down*, mainly through signal two's sentence-spread measure. The one accusation pushes the score *up*, through the shared blind spot. These pull in opposite directions, which decides the fix (next section).

<!-- For each miss AND each broken attack: the stage and the mechanism.

     Your service has five stages: the route, signal one, signal two, the
     combining rule, and the label mapping.

     Not a diagnosis:  "The evasion attacks got through."
     A diagnosis:      "Four evasion inputs got through. All four had typos
                        added to AI-generated text. My second signal measures
                        word variety, and typos raise word variety — so it read
                        them as more human. My combining rule weights that
                        signal at 0.6, so it dragged the whole score down."

     Look for a pattern. Five failures on one signal is one problem, not five. -->



---

## The Improvement

**What I changed:** One line in `config.py`: `AI_THRESHOLD` from **0.70 to 0.75**. The high-confidence-AI band is now 0.75–1.00, and the unsure band is wider at the top (0.40–0.75). No signal, weight or other setting moved (commit `f0dcc3a`).

**Which diagnosis pointed at it:** The worst outcome, FP05, and the three near-misses (FP02–04). In all four, both signals agree, so the combining rule has nothing to resolve, and the **label mapping** is the only stage left that can stop an accusation. FP05 scored 0.7425, and the next-highest human text in the run scored 0.695.

**What I considered and rejected:** Most broken attacks point at signal two (sentence-length spread). Before touching the service I tested an offline fix on the before-run data. I recomputed the style signal with the single shortest and longest sentence trimmed from the spread measure, reusing the recorded model scores, which are deterministic. It fixed criterion 3's borderline group (3/3) and nudged EV03, EV06 and EV09 upward. It also turned **six** human texts into AI accusations: FP02, FP03, FP04, FP05, FP06 and FP07. The sentence-spread measure is the main thing keeping plain human writing out of the AI band. Weakening it trades a few missed AI texts for several accused writers, which is the expensive mistake. So I fixed the accusation instead.

### Attack Run — After

`python run_attacks.py --set attack_set --label after`, giving `results/attack_run_2026-11-13_0056_after.md`. Only rows whose result could change are listed; all 32 malformed and flood rows returned exactly the same status codes as before (RQ11 was again a 429).

| ID | Targeting | Before | Before verdict | After | After verdict |
|---|---|---|---|---|---|
| EV01 | typos | unsure 0.408 | BROKE | unsure 0.408 | BROKE |
| EV02 | broken-up sentences | human 0.340 | BROKE | human 0.340 | BROKE |
| EV03 | pasted quotation | human 0.394 | BROKE | human 0.394 | BROKE |
| EV04 | unusual words | unsure 0.539 | BROKE | unsure 0.539 | BROKE |
| EV05 | heavy human edit | human 0.161 | BROKE | human 0.161 | BROKE |
| EV06 | one long + one short sentence | human 0.346 | BROKE | human 0.346 | BROKE |
| EV07 | punctuation padding | unsure 0.406 | BROKE | unsure 0.406 | BROKE |
| EV08 | below the token window | 422 | HELD | 422 | HELD |
| EV09 | human opening bolted on | unsure 0.433 | BROKE | unsure 0.433 | BROKE |
| EV10 | repeated stanza | unsure 0.669 | BROKE | unsure 0.669 | BROKE |
| FP01 | plain human writing | unsure 0.458 | HELD | unsure 0.458 | HELD |
| FP02 | formal register | unsure 0.691 | HELD | unsure 0.691 | HELD |
| FP03 | non-native speaker | unsure 0.693 | HELD | unsure 0.693 | HELD |
| FP04 | rubric essay | unsure 0.695 | HELD | unsure 0.695 | HELD |
| **FP05** | **technical documentation** | **ai 0.743** | **BROKE** | **unsure 0.743** | **HELD** |
| FP06 | formal template | unsure 0.593 | HELD | unsure 0.593 | HELD |
| FP07 | deliberate repetition | unsure 0.582 | HELD | unsure 0.582 | HELD |
| FP08 | very short human text | 422 | HELD | 422 | HELD |
| PI01 | ignore the check | human 0.258 | BROKE | human 0.258 | BROKE |
| PI02 | fake system message | human 0.129 | BROKE | human 0.129 | BROKE |
| PI03 | instruction in writer's voice | unsure 0.439 | BROKE | unsure 0.439 | BROKE |
| PI04 | hostile label | human 0.316 | HELD | human 0.316 | HELD |
| PI05 | audit-log injection | human 0.348 | HELD | human 0.348 | HELD |
| PI06 | instruction + human text | unsure 0.418 | HELD | unsure 0.418 | HELD |

| Family | Before: held / broke | After: held / broke |
|---|---|---|
| evasion | 1 / 9 | 1 / 9 |
| false_positive | 7 / **1** | 8 / **0** |
| prompt_injection | 3 / 3 | 3 / 3 |
| malformed | 20 / 0 | 20 / 0 |
| flood_same_creator | 12 / 0 | 12 / 0 |
| **Total** | **43 / 13** | **44 / 12** |

**Run log — after.** `python run_eval.py --label after`, giving `results/run_2026-11-13_0057_after.md`:

| Criterion | Target | Run 1 | Run 2 | Run 3 | Verdict |
|---|---|---|---|---|---|
| 1. Human writing flagged as AI | ≤ 1 of 10 | 0/10 | 0/10 | 0/10 | MET* (unchanged) |
| 2. AI vs human score gap | ≥ 0.30 | 0.48 | 0.48 | 0.48 | MET (unchanged) |
| 3. Labels reachable and correctly placed | ≥ 2 of 3 per group | 2 / **1** / **1** | 2 / **1** / **1** | 2 / **1** / **1** | **MISSED (worse)** |
| 4. Appeals change status and are logged | 5/5, 3/3 | 5/5, 3/3 | 5/5, 3/3 | 5/5, 3/3 | MET (unchanged) |
| 5. Bad input → 4xx, logged, < 5 s | 6 of 6 | 6/6 | 6/6 | 6/6 | MET (unchanged) |

Scores are identical to the before run to four decimal places, because the change is downstream of both signals. Only labels moved. Criterion 3's AI group dropped from 2/3 to 1/3: "Technology has had a profound impact on modern education" scored 0.748, which was AI at 0.70 and is "unsure" at 0.75.

**Did it help, and how do I know:** **Yes on what it was aimed at, and it cost something.** The only accusation in the attack run is gone (FP05: AI, now unsure), and false positives went from 1 to 0 with no score changing. The cost: two AI texts that used to be caught are now "unsure", the 0.733 AI text in criterion 2's set and the 0.748 text in criterion 3. Criterion 3 went from missed to more missed. No evasion was helped or hurt, because every one already scored under 0.70. The fix also has no safety margin left: FP05 at 0.7425 is now 0.0075 under the new line, the same thin margin FP02–04 had under the old one. This moved the line past the one writer I saw; it didn't make the detector better at telling them apart.

> **A measurement mistake, caught and redone:** my first "after" attack run hit a stale copy of the service still running the old 0.70 threshold. Windows let a second process bind port 5000 without an error. FP05 still came back `ai`, which is how I noticed. I stopped every process, confirmed a single listener started after the change, deleted that results file and re-ran. That stale run's entries are still in `logs/audit.jsonl` (timestamps 2026-11-13T05:55), since the log is append-only. The "before" runs are unaffected: they hit the process started after the rate-limit commit, which was running the committed before-code.

---

## What's Still Broken

- **Sentence-shape evasions (EV02, EV03, EV06, EV09) and criterion 3's borderline group.** Signal two's spread measure is trivially steered by fragments. *What I'd do:* stop asking one measure to do both jobs. Keep spread as the guard against false positives, but make the AI-ward evidence come from something a fragment can't fake, such as per-sentence perplexity variance from signal one ("burstiness"), which a padded "Really." doesn't change much. *Why I stopped:* the one fix I tested on this signal created six accusations (see The Improvement), and a replacement measure needs its own calibration run.
- **Perplexity dilution (EV01 typos, EV04, PI01–PI03).** Signal one averages over the whole text, so a few weird tokens or a pasted instruction pull an AI paragraph toward human. *What I'd do:* score sentences separately and use a high percentile rather than the mean, so a clean AI body still shows through a noisy sentence or two. Typos could be spell-normalised before scoring. *Why I stopped:* both are signal changes, and this unit allows one change.
- **EV10, the disagreement rule cutting both ways.** A 0.98 model reading was rescued by a 0.36 gap. *What I'd do:* only apply the shrink when it moves a score *away* from an accusation, never when it moves an AI verdict to "unsure". That keeps the rule's purpose (no single-signal accusations) without its side effect. *Why I stopped:* that's a combining-rule change, and I'd already used my one change.
- **The shared blind spot behind FP02–FP05.** The fix moved the line past these texts without separating them. Plain, careful, regular human writing still scores 0.69–0.74, and a slightly plainer document will cross 0.75. *What I'd do:* nothing more with thresholds. This needs a signal that measures something other than predictability and regularity. Until then, the appeal path is the real protection, and the label says so.
- **Criterion 3: still missed, now worse (borderline 1/3, AI 1/3).** Cause: signal two for the borderline texts (above) and my threshold change for the AI one. I'm leaving the target where it is.
- **Criterion 1 is under-tested.** It ran on published literary prose, not my own everyday writing (see `criteria.md`). Given FP01–FP05, I'd expect plain writing to land much higher than these passages did.
- **RQ11 and the rate limiter.** A body the route can't parse is keyed by IP, and its 429 is logged with `creator_id: "unknown"`. *What I'd do:* read the raw body with `force=True` in the key function and the 429 handler, so the creator is known even when the content type lies.
- **Rate limiting can be dodged by inventing a `creator_id` per request** (see Rate Limiting). The fix is authentication, which is out of scope here.

**The trade I'd make if this ran for real:** I'd keep erring toward fewer accusations, even at the cost of letting more AI text through as "unsure", which this change already does: two AI texts escaped to save one writer. The people who pay are honest writers on the platform, whose work now competes with more undetected AI text, and the moderators who have to review a larger "unsure" pile. I think that's the right group to carry the cost, because an accused writer pays alone and personally for a mistake the system made.

<!-- ═════════════════════════════════════════════════════════════════════

     SUBMISSION CHECKLIST — unit 7

       [ ] criteria.md has five numbered criteria, each naming a target
       [ ] Each has a reason underneath
       [ ] POST /submit returns content_id, guess, confidence, label,
           model_score and style_score
       [ ] Two signals that measure DIFFERENT things, each with a named blind spot
       [ ] Three label variants, all reachable, written out in full
       [ ] POST /appeal changes status and writes to the log
       [ ] Signals and Scoring names scoring.py::combine_signals
       [ ] Sample Run: a submission AND an appeal, as pasted text
       [ ] At least four new commits
       [ ] Repository URL submitted — WRITE IT DOWN

     SUBMISSION CHECKLIST — unit 8

       [ ] Rate limiting on /submit, with your numbers justified
       [ ] The pasted run of status codes showing 429
       [ ] Audit log with all nine fields, recording rejections too
       [ ] The attack set run IN FULL, every input with an outcome
       [ ] Ten audit log entries pasted as text
       [ ] Five criteria across three trials
       [ ] A diagnosis for every miss and every broken attack — stage AND mechanism
       [ ] One improvement, with Attack Run — After
       [ ] What's Still Broken, including the production trade
       [ ] At least four new commits
       [ ] The SAME repository URL as last unit

     Do not delete and recreate this repository.
     ═════════════════════════════════════════════════════════════════════ -->

---

📖 **How to run this project: [RUNNING.md](RUNNING.md)**
