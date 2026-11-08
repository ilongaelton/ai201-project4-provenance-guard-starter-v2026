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

<!-- ═══════════════════════ UNIT 8 — THE TEST ═══════════════════════ -->

---

## Rate Limiting

**My limits:** ___ per minute, ___ per day

**Why those numbers and not others:**
<!-- Think about two people: a real writer submitting their own work a few
     times an hour, and a script sending a thousand variations to map your
     thresholds. Your numbers have to be liveable for the first and hostile to
     the second. -->

**What a caller counts as:** <!-- per address, or per creator_id? They fail
differently — one script can look like a thousand callers, and one household
can look like one. -->

**The run of status codes when I pushed past it:**

<!-- python run_attacks.py --flood 15 -->

```

```

---

## Attack Run — Before

<!-- Every attack with its outcome and a held-or-broke mark.
     `run_attacks.py --label before` produces the table. -->



**Ten audit log entries from the run**

<!-- Choose entries that show the interesting failures, not the ten easiest. -->

```json

```

**The single worst outcome** — the one I'd least want to explain to a writer
whose work got caught by it:



---

## Run Log and Verdicts

<!-- Your five criteria across three trials. `run_eval.py --label before`. -->

| Criterion | Target | Run 1 | Run 2 | Run 3 | Verdict |
|---|---|---|---|---|---|
| 1.  |  |  |  |  |  |
| 2.  |  |  |  |  |  |
| 3.  |  |  |  |  |  |
| 4.  |  |  |  |  |  |
| 5.  |  |  |  |  |  |

**Real output from one trial**, pasted as text, naming the file and function
that produced it:

```json

```

**Diagnoses**

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

**What I changed:**

**Which diagnosis pointed at it:**

### Attack Run — After

<!-- Same format. `run_attacks.py --label after` -->



**Did it help, and how do I know:**

<!-- Widening the unsure band usually fixes one problem and creates another.
     Reporting that trade honestly is worth full credit. -->



---

## What's Still Broken

<!-- For each attack still getting through and each criterion still missed:
     what you'd do, and why you stopped. -->



**The trade I'd make if this ran for real:**

<!-- Two sentences. Fewer wrong accusations means more AI text getting through.
     Say which way you'd go and WHO PAYS FOR IT. -->



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
