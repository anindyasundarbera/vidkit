# hello-world — narration

The spoken lines are the **bold** ones. Bracketed lines are stage directions and
are never spoken or captioned. The `mm:ss` ranges are the intended timing; the
build re-times every caption from the **measured** audio durations, so a stale
range here can never desynchronise the render.

## Scene 0 — Title · 0:00–0:06

[Title card.]

**vidkit turns a plain spec into a narrated, captioned video. Here is the smallest complete build.**

## Scene 1 — What a spec is · 0:06–0:17

[Stat cards summarising the toolkit.]

**A spec is a file. It names the project, the scenes, each shot, and the guardrails the finished cut has to satisfy. It contains no code.**

## Scene 2 — What a provider is · 0:17–0:31

[Prose panel.]

**A provider is a module beside the spec. It supplies the numbers each panel is drawn from. This one counts the vidkit source tree, so every figure you are about to see is measured, not invented.**

## Scene 3 — The shape of the code · 0:31–0:42

[Line chart then bar chart of module sizes.]

**These are the modules that make up vidkit, sorted by size. They are counted, not estimated — the bar chart is the same data the line chart draws.**

## Scene 4 — The pipeline · 0:42–0:56

[A cell per stage.]

**The build is nine stages. Data, panels, stills, capture, narration, clips, concat, render, verify. Each stage writes what the next one reads, and any failure stops the build rather than shipping a dishonest cut.**

## Scene 5 — Verification · 0:56–1:09

[Environment and provenance facts.]

**After the render, verify reopens the video and checks it. Runtime inside the window, no banned phrases, captions readable, audio present. The result is written to verify json, and a failure exits non zero.**

## Scene 6 — Running it · 1:09–1:20

[Terminal panel.]

**This is the whole workflow. Install, then doctor, plan, build. The build prints a report and leaves the mp4, the captions, and the verification beside it.**

## Scene 7 — That is vidkit · 1:20–1:27

[End card.]

**That is all of it. Change the spec, run the build again, and the video follows the file.**
