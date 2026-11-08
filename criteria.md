# Acceptance criteria — Provenance Guard

Five criteria that say what "working" means for this service, written in unit 7
**before** you built it.

**All five are yours.** None are given.

An acceptance criterion names a number or something plainly observable. *"The
detector is accurate"* is an opinion — and perfect AI detection isn't possible
anyway, so it's an opinion about something nobody can deliver. *"Of 10 pieces I
wrote myself, at most 1 is labelled high-confidence AI"* is a criterion.

Under each, write a sentence or two on **why that target**. *"I allow at most 1
false positive in 10 because on a writing site a wrong accusation costs more
than a missed detection"* is a real answer.

> Missing your own targets next unit costs you nothing. Setting a target so
> easy you can't miss it does.

---

## Pick numbers you can defend

**Cover at least three of these five areas.** They're prompts, not a form.

| Area | A question it could answer |
|---|---|
| False positives | How often may a human's writing get called AI? |
| Score spread | How far apart should clearly-AI and clearly-human text score? |
| Label coverage | Is every one of your three labels actually reachable? |
| The appeal path | Does an appeal always change status and always get recorded? |
| Bad input | What happens when `text` is missing, empty, or enormous? |

Two things worth knowing before you pick numbers:

- **The expensive mistake is one-sided.** Missing some AI text costs the site a
  little. Accusing a real writer costs that person a lot. A criterion that
  treats both errors as equally bad is describing a system nobody would ship.
- **Unit 8 tests across three trials, and the target has to hold across all
  three.** Your first signal runs a model, so identical input can score
  differently twice. A target of "at most 1 in 10" against trials of 2, 1, 2 is
  a **miss**.

---
> **How these were written:** drafted with Claude Code after the service was
> built and after the first calibration runs, not before (see README → How I
> Used AI). The targets are set by what a writer on the receiving end would
> accept, not by what the calibration showed would pass. Criterion 1 is known to
> be at risk: a plain, second-language-style paragraph already scored as AI.

## 1. Few false accusations on my own writing

Of 10 pieces of my own writing (each 60–300 words), **at most 1** is labelled
high-confidence AI, and this holds in **every one of 3 trials**.

**Why this target:**
On a writing site a wrong accusation costs the writer far more than a missed
detection costs the site. 1 in 10 is the most I'd accept if it were my own
work being judged, and it has to hold every time, because a writer only gets
judged once.

---

## 2. Clearly-AI and clearly-human text score far apart

Across 5 texts I'm confident are AI-generated and 5 I'm confident are
human-written, the **mean combined score of the AI set is at least 0.30
higher** than the mean of the human set, in each of 3 trials.

**Why this target:**
0.30 is the width of my "unsure" band (0.40–0.70). If the typical AI text and
the typical human text aren't at least that far apart, they can't land on
opposite sides of the band, and the labels are doing nothing a coin couldn't.

---

## 3. Every label is reachable, and lands where intended

Using 9 coverage inputs (3 meant to be clearly human, 3 borderline, 3 clearly
AI), **each of the three labels appears at least once**, and **at least 2 of
the 3 inputs in each group get their intended label**, in each of 3 trials.

**Why this target:**
A label that can't be reached is a gap in the ranges. Requiring 2 of 3 per
group also checks the ranges are in roughly the right place, not just that
some score somewhere happens to hit each band.

---

## 4. Appeals always change status and are always recorded

For **5 of 5** appeals sent with a real `content_id`, the response is 200 with
`status: "under_review"`, and `GET /log` shows an appeal entry for that id
after the original decision. For **3 of 3** appeals with a made-up id, the
response is 404 and **no** log entry is written.

**Why this target:**
The appeal is the only thing between a wrong accusation and nothing at all,
so anything less than every time is a failure. The made-up-id check is there
because a typo that fails silently looks like a working appeal to the writer.

---

## 5. Bad input never crashes the service

**6 of 6** malformed requests (empty `text`, missing `text`, `text: null`,
`text` that isn't a string, 50,000 words of text, and a body that isn't a JSON
object) get a 4xx response with an `error` field, **0** get a 5xx, each writes
a `rejected` entry to the audit log, and each answers within 5 seconds.

**Why this target:**
A crash on malformed input is one of the most common real failures, and an
oversized input that runs the model for a minute is an easy way to tie the
service up. A refusal that leaves no log entry is invisible, so the trace
counts as part of passing.

---

<!-- ─────────────────────────────────────────────────────────────────────────
     UNIT 8 — read this before you change anything above.

     If a criterion turns out to be BROKEN rather than merely unmet, you can
     revise it, and that earns credit. But never delete or edit the original
     line. Add the revision underneath, like this:

         ## 2. Uncertain cases land in the unsure band

         The system handles uncertain cases well.

         **Why this target:** ...

         > **Revised in unit 8:** Text I judged borderline scores between
         > 0.4 and 0.6 in at least 4 of 5 cases.
         >
         > **Why revised:** "well" gave me nothing to check. I couldn't
         > reach a verdict from it at all.

     That's a revision because the criterion couldn't be MEASURED.

     Lowering a target because you missed it is not a revision, and it costs
     you the point:

         ✗ "At most 1 of 10 of my own pieces flagged as AI" → "at most 3
            of 10", because 1 of 10 turned out to be hard.

     A number you missed stays where it is, gets diagnosed, and gets a fix
     attempted. That's where the points are.
     ───────────────────────────────────────────────────────────────────────── -->
