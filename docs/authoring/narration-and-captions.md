# Narration and captions

Narration drives everything: it is spoken, measured, and turned into captions. Because
**audio is the master clock** ([`concepts.md`](../foundations/concepts.md)), fixing the script fixes the
timing.

## The script file

`narration.source` points at a Markdown file. The parser (`narration.parse_scene_script`)
reads scene blocks:

```markdown
## Scene 0 — Title card · 0:00–0:10

[Title card on screen: "One river, two kinds of evidence."]

**One location on the Yamuna. Two completely different kinds of evidence.**
**And one question: what does the evidence actually support?**

## Scene 1 — Scope · 0:10–0:32

[point at the mode indicator]

**We're not touring features. This is one investigation of one place.**
```

**Grammar**
- A scene header must match: `## Scene <n> — <title> · <mm:ss>–<mm:ss>`
  (`–` or `-` between the times).
- **Spoken text = the lines that are entirely `**bold**`.**
- `[bracketed]` lines, prose, and headings are **ignored** (they are stage directions/notes).
- Multiple bold lines in a scene are joined with a space.
- Scenes with no spoken line are skipped.

**Rules**
- Every scene in the spec must resolve to non-empty text (from `source` or `narration.inline`).
- The header timings are **informational**. Real timing comes from measured audio; use the
  header times only to keep the script readable.
- A scene is matched by its **number**, not its order in the file.

## Inline narration

For short videos, skip the file:

```yaml
narration:
  inline:
    0: "One river, two kinds of evidence."
    1: "Read live from an upstream API, scoped to a dataset tag."
```

`inline[n]` always overrides the `source` block for scene `n`.

## How captions are built

`narration.build_srt(scene_texts, scene_spans)`:

1. Splits each scene's text into cues at sentence boundaries, then breaks long clauses at
   `; : , —`, then word-wraps.
2. Times cues **proportionally within the scene's measured span**.
3. **Asserts fidelity:** the concatenated caption text must equal the script text
   token-for-token (lowercased, punctuation-insensitive). A dropped word raises `SpecError`.
4. **Asserts readability:** every cue is ≤ **2 lines** of ≤ **42 characters**. A too-long
   unbreakable token raises.

The result is written to `OUT/narration.srt` and burned in during `render`.

## Word count and timing

- Speech rate is roughly `length_scale × 2.5` words/sec for Piper; at `length_scale: 1.08`
  it is ≈ 2.8 words/sec (≈ 168 wpm).
- Total runtime ≈ `total_words / 2.8` seconds. Check it against `project.min/max_seconds`
  before rendering — `vidkit plan` prints this estimate.

## Writing effective narration

- **One idea per sentence.** Each sentence becomes roughly one caption cue.
- **Avoid very long unbreakable tokens** (long URLs, chemical names) — they force a cue past
  42 chars. Keep them out of the spoken text; put them on a panel instead.
- **Read it aloud** at your target pace; if it drags, lower `length_scale`.
- **State the boundaries explicitly** when the subject needs it (e.g. "synthetic data",
  "association, not causation"). You can then enforce them with `guard.required`.

## Guarding the script

`guard.banned` / `guard.required` (case-insensitive) scan the union of scene text and caption
text. Use them to make a promise mechanical:

```yaml
guard:
  banned: ["caused", "proves a", "legal limit"]
  required: ["synthetic", "causation"]
```

- `banned` catches unsafe phrasing anywhere in the script.
- `required` ensures a mandatory disclosure is actually present.

See [`verification.md`](../verification/verification.md).

### Any window you mention is a claim

Narration and captions are also read for statements **about time**, and checked against the
spec's `timeframe:` (R-F7). "The last 28 days", "9 September 2026 to 6 October 2026", and
"the last 28 days to 2026-10-06" are all understood and all compared with the declared window.

If the spec's window is relative and pins no `as_of`, narration may state its **day count**
but not its dates — a date there is refused at load, because the window would mean something
different tomorrow. → [Stories and timeframes](./stories-and-timeframes.md)

## Tuning the voice

| Knob | Effect |
|---|---|
| `voice.length_scale` | > 1 slower, < 1 faster (timing follows automatically) |
| `voice.sentence_silence` | pause between sentences |
| `voice.model` | which Piper voice |
| `voice.engine: none` | silent cut; durations estimated from word count |

To change the pace:

```bash
# regenerate narration at a calmer pace, then rebuild
# (edit voice.length_scale in the spec, then:)
vidkit build SPEC --only narration,clips,concat,render
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `no spoken (**bold**) lines found` | no bold lines in the script | bold the spoken lines |
| `no '## Scene N … · mm:ss–mm:ss' headers` | header format wrong | match the grammar exactly |
| `caption cue N is not readable` | an unbreakable token > 42 chars | shorten it or move it to a panel |
| `caption fidelity check failed` | text mismatch (rare, bug) | report it; do not disable `strict` |
| Runtime outside window | words vs. pace | adjust `length_scale` or trim text |
| `TTS failed … estimating duration` | voice model missing/broken | fix `voice.model` |
| `narration states the window … but the spec's timeframe … pins no as_of` | dates written while the window floats | add `as_of:` to the spec, or state only the day count |
| `narration states a … window … but the spec declares no timeframe` | the script mentions a window the spec never declared | add `timeframe:` to the spec, or drop the dates |

## See also

- [`verification.md`](../verification/verification.md) — the checks that read this text
- [`spec-reference.md`](spec-reference.md) — `voice`, `narration`, `guard`
- [`stories-and-timeframes.md`](stories-and-timeframes.md) — the window contract and what narration may state
