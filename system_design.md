# Attune Web — System Design

Status: reflects the local working tree as of 2026-08-12 (not yet deployed -
see "Known Issues" §9 for what's landed locally vs. still pending a
container/Amplify redeploy). Update this file whenever the architecture
materially changes.

## 1. Two independently deployed halves

**Frontend** — Svelte 5 (`web/src/`), built with Vite, deployed to AWS
Amplify. Auto-builds on push to `origin` (`Gbeckler8/TuneBuddy` fork).

**Backend** — FastAPI (`web/api/analyze_api.py`), packaged via the root
`Dockerfile`, deployed to a container platform (App Runner/ECS) via ECR.
Deploys independently of the frontend — a frontend-only change never
touches the container and vice versa.

```
Browser (Svelte/Amplify)                    Backend container (FastAPI/App Runner)
┌─────────────────────────┐                 ┌──────────────────────────────────┐
│ upload score ──────────►│── POST /notedata ─►│ parse score (ScoreData.load)   │
│ (cached client-side,    │◄── note_data,       │ NO resize/stabilize            │
│  keyed by file hash)    │    bpm, musicxml     │                                │
│                          │                                                       │
│ upload/record audio     │  (client-side only, no request)                       │
│ click Analyze ─────────►│── POST /analyze ───►│ Recording pipeline:            │
│                          │                     │  detect_pitches                │
│                          │                     │   ├─ per-frame volume (PitchDetector, no separate step)│
│                          │                     │   └─ recompute_vibrato(note_aware=False) — provisional│
│                          │                     │  → detect_notes                │
│                          │                     │   └─ recompute_vibrato(note_aware=True) — final, note-bounded│
│                          │                     │  → resize_score → detect_mistakes│
│                          │                     │  → stabilize_score_alignment   │
│                          │◄── alignment.pairs   │  → reindex_mistakes            │
│                          │    + user note_data  │  → update_alignment_distances  │
│                          │    + pitch_data       │  → trim_end                    │
│                          │      (incl. volume)   │ (stateless — nothing persists  │
│                          │    + vibrato          │  after the response)            │
│ aggregate per-note       │ (client-side: meanVolume/volumeRangeDb, colors.js)     │
│ volume, classify mistakes│ (client-side JS, mistakes.js)                          │
│                          │                                                       │
│ pitch/timing tolerance   │ (pure client-side reclassification against the same    │
│  moved                   │  pairs - no request, no re-alignment; see §4)          │
└─────────────────────────┘                 └──────────────────────────────────┘
```

## 2. Core principle: one algorithm implementation, two frontends

`algorithms/` and `app_logic/` (pitch detection, note detection, alignment,
mistake detection, `ScoreData`, `Recording`, `JsonHandler`) are the exact
same classes desktop uses, imported unmodified by `analyze_api.py`. The
`Dockerfile` explicitly excludes `ui/` (PyQt widgets) and `resources/` but
includes `algorithms/` + `app_logic/` verbatim — this is why PyQt6 is a
runtime dependency of a headless API (a hard import in `PitchDetector`/
`NoteDetector`, even though no window ever opens). Real cost, but it buys
zero algorithm drift between desktop and web.

Docker build note: must build `--platform linux/amd64` — PyQt6 has no
published `linux/arm64` wheel.

## 3. Backend: stateless per request

No database, no session store, nothing held between requests. Each
`/analyze` call runs the full pipeline and returns one JSON payload; when
the request ends, the server forgets everything.

### Endpoints

- **`GET /health`** — liveness check.
- **`POST /notedata`** — parse an uploaded score only (no audio needed).
  Returns `note_data` per instrument channel, `bpm`/`bpm_og`, `musicxml_b64`
  (feeds the Verovio score viewer), `measure_onsets_og` (anchors
  `ScoreTimeMap`), `instruments`, `metronome_channel`, `transpose_offset`.
  **Does not run `resize_score` or `stabilize_score_alignment`** — this is
  the raw, un-corrected parse. Cached client-side keyed by score file hash
  (`noteDataCache.js`). Fired automatically the moment a score is selected —
  no button click needed.
- **`POST /analyze`** — score + audio, full pipeline (see diagram above).
  Only fires from an explicit "Analyze" button click
  (`TransportBar.svelte:68`, `session.runAnalyze()`) — never automatically
  on upload. Response includes `alignment.pairs` and the user's own
  `note_data`, but — see Known Issues — **not** the corrected score-side
  note timings that `stabilize_score_alignment()` computed.

  A third endpoint, `POST /realign`, existed until 2026-08-12 to re-pair
  notes at a new `pitch_tolerance` without a full re-upload. Removed once
  confirmed to be a no-op against the current alignment cost model — see §4.

### CORS

`allow_origin_regex` covers any localhost/127.0.0.1 port (Vite's port isn't
fixed); `allow_origins` allow-lists the deployed Amplify origin explicitly.

### 3a. Vibrato and volume

Neither is a distinct pipeline stage. Volume is a per-frame byproduct of
`PitchDetector.detect_pitches()` (no separate detection); it rides along
inside `pitch_data.pitches` and is aggregated into a per-note "quiet→loud"
fraction entirely client-side (`meanVolume`/`volumeRangeDb`/`volumeFrac` in
`colors.js`). Vibrato has a real server-side detector
(`VibratoDetector.detect`), run twice per `/analyze` call — once
provisionally on the raw pitch track inside `detect_pitches()`
(`recompute_vibrato(note_aware=False)`, `Recording.py:271`), once finally
bounded by note spans inside `detect_notes()`
(`recompute_vibrato(note_aware=True)`, `Recording.py:325`), which replaces
the provisional pass. Serialized as a payload-only `vibrato` key
(`analyze_api.py` adds it directly, not via `to_cache_payload()`) —
deliberately excluded from the shared desktop/web cache format, since it's
cheap to recompute from the pitch track rather than worth persisting in
either app.

## 4. Mistake classification: fully client-side

The alignment DP (which user note pairs with which score note) is
server-side and runs exactly once, inside `/analyze`. Turning that fixed
pairing into "is this a mistake" is a pure threshold check (`mistakes.js`),
ported to run in the browser so the tolerance sliders feel instant.

- **Timing tolerance** (`sessionState.svelte.js`, `setTimingTolerance`) —
  purely local, no network call, ever.
- **Pitch tolerance** (`sessionState.svelte.js`, `setPitchTolerance`) — also
  purely local as of 2026-08-12. Used to debounce a call to a `/realign`
  endpoint; removed once confirmed to be a no-op (see below).

**Why pitch tolerance doesn't need a server round-trip:** `MistakeDetector`'s
DP cost functions (`get_substitution_cost` etc.) are driven by
`alignment_gamma_pitch`/`alignment_gamma_time` (fixed config constants),
**not** `pitch_tolerance` — confirmed by reading
`MistakeDetector.string_edit`/`get_substitution_cost`, and empirically: three
`/realign` calls at pitch tolerances of 0.1, 0.5, and 3.0 semitones against
identical note data produced byte-identical pairs every time.
`pitch_tolerance` only affects `build_mistakes()`'s post-hoc labeling of an
already-decided pair as a mistake or not — the same threshold check
`classifyPitchMistakes` already runs in JS.

**This wasn't always true.** `/realign` was built 2026-07-12 against an
older `MistakeDetector` where substitution cost genuinely was tolerance-gated
(`0.0 if d < self.TOLERANCE else min(d, 10)`), so re-running alignment at a
new tolerance really could change the pairs back then. Commit `c8ab97b`
(2026-07-23, "refined mistake correction flow") replaced that with the
current continuous gamma-weighted model in both `MistakeDetector.py` and
`MistakeChecker.py`, silently removing `/realign`'s reason to exist. Full
history in `web/docs/api-design.md`'s (removed) `POST /realign` section.

## 5. `MistakeDetector` vs `MistakeChecker`

Two distinct classes, both attached to `Recording` (`self.mistake_detector`,
`self.mistake_checker`):

| | `MistakeDetector` | `MistakeChecker` |
|---|---|---|
| Job | Sequence-alignment DP (deletion/substitution/insertion) between user and score notes | Repairs note-segmentation errors (bad onset splits/merges) when doing so lowers total alignment cost |
| Entry point | `Recording.detect_mistakes()` | Only inside `Recording.stabilize_score_alignment()`'s loop |
| Depends on `pitch_tolerance`? | Only for post-hoc mistake labeling, not the DP path | No — driven by `alignment_gamma_pitch`/`gamma_time` (via `MistakeDetector`'s cost functions) and segmentation config (`min_note_pitch_frames`, `min_note_seconds`, `min_silence_duration_ms`) |

`stabilize_score_alignment()` (`Recording.py:602-647`) is the convergence
loop: `resize_score_to_aligned_onsets()` → `detect_mistakes()`
(`MistakeDetector`) → `mistake_checker.check_mistakes()` → repeat until the
note/pairing state stops changing, guarded against oscillation by a
seen-state set.

## 6. Score viewer

Both desktop and web embed the same `viewer.js` (Verovio WASM) — desktop
loads it via `file://` in a `QWebEngineView`, web syncs it into
`web-resources/` (`npm run sync-verovio`) and loads it in an iframe.

Driven imperatively via pub/sub (`notifier.js`), not reactive `$effect`s —
changed this session after reactive effects proved unreliable crossing the
iframe boundary. Mirrors desktop's `WallClock → move_views()` push model.
`makeNotifier`'s `notify()` isolates listener failures with a per-listener
try/catch so one throwing listener can't block the rest.

## 7. Playback

Desktop's `MidiPlayer` hand-schedules note on/off against
`time.perf_counter()`. Web instead builds a minimal Standard MIDI File
(`smf.js`) from note data and hands it to `js-synthesizer`'s built-in player
(fluidsynth compiled to WASM) — trades desktop's per-message mute control
for rebuild-and-reload-on-mute-change, in exchange for tick-accurate
scheduling and seeking for free.

## 8. Deliberately not ported

Desktop's **Practice tab** (live mic input, real-time pitch-matching, no
recording needed) was scoped out from the start
(`App.svelte:5-7`). Only **Perform** (record/upload a complete take, then
batch-analyze) made it to web — Practice's live feedback loop needs a
fundamentally different architecture (persistent WebSocket streaming,
server-held per-connection state) than the stateless REST design everything
else here is built around.

## 9. Known Issues / Planned Changes

### 9a. Adaptive-timing bug (fixed 2026-08-12)

`stabilize_score_alignment()` genuinely corrects the score's tempo to match
a recording (confirmed via local reproduction: BPM moved 120 → 100.0 → 113.3
for `major.mxl` + `flute_scale_bad.m4a`, and matched-pair onset deltas
dropped to <0.4s after the full pipeline). But this correction never reached
the client: `/analyze`'s payload only returned score-level metadata
(`_score_to_payload` — `bpm`, `title`, etc.), never a corrected per-note
score `note_data` array. The client's `scoreNotesActive` (used by
`classifyTimingMistakes`) was always sourced from `/notedata`'s
pre-stabilization cache, since that was the only score note-timing data
that ever reached the browser. Reproduced the screenshot's near-uniform
"Late by ~1.8-2.1s" pattern locally by pairing user notes against the
*original* unstabilized 120bpm score onsets instead of the corrected ones —
same shape.

**Fix:** `/analyze`'s response now includes `timing_updated_note_data`, a
per-channel dict of corrected score `note_data` (same array shape
`/notedata` already returns, built via `JsonHandler._note_data_to_payload`)
captured *after* the full pipeline runs (`analyze_api.py`, added right after
`vibrato`, following the same "web-API-only, not part of
`to_cache_payload()`" pattern - desktop has no equivalent stale-cache
problem, so this field would just pollute every future `.json.xz` for no
reason if it lived in the shared serialization method instead). All
channels included, not just the analyzed one - the tempo correction is a
single score-wide change (`Recording.change_tempo`), so it applies
uniformly regardless of which channel was actually aligned against the
recording.

Client-side, `scoreNotesActive` now prefers this field
(`correctedScoreNotesForActiveInstrument()`) over the `/notedata` cache
whenever it exists for the active channel, falling back to the cache
otherwise (`sessionState.svelte.js`) - the same "prefer the freshest
computed value, fall back to the base cache" shape `currentPairs` already
used for `analysisResult?.alignment?.pairs`. The cache itself is never
written to - it's keyed by score content hash and reused across
potentially different recordings of the same score (confirmed this is the
*primary* workflow, not an edge case: `pickAudio()` never touches
`scoreFile`/`noteData`, so re-analyzing a new take against an
already-loaded score is a one-click action). The cache still matters for
two things `analysisResult` doesn't cover: the pre-analysis pitch-overlay
preview (§9b) and `App.svelte`'s `onNoteClicked` note-click-to-seek, both
of which read `scoreNotesActive` before any analysis exists and have
nothing else to fall back to.

**Verified end-to-end** through the actual running app (not just the
pipeline in isolation): analyzing `major.mxl` + `flute_scale_bad.m4a`
produced a Timing Mistakes table of 4 real, varied mistakes (one large
early-onset outlier at the very start of the take, two duration issues, one
genuine late note at +0.42s) - nothing resembling the original bug's
near-uniform +1.8 to +2.16s "Late" entries across nearly every note.

### 9b. Pitch overlay pre-analysis rendering (implemented 2026-08-12)

`NoteOverlay.svelte` previously only mounted once `session.analysisResult`
existed. Its rendering logic was already empty-safe for every prop that
could be missing pre-analysis (`pairs`, `userNotes`, `pitchMistakes`,
`pitchFrames` all degrade to harmless no-render paths — confirmed by
reading the full 585-line file), so no changes were needed inside
`NoteOverlay.svelte` itself — only in how `App.svelte` mounts it.

**Change made**, all in `App.svelte:218-240`:
1. `{#if session.analysisResult && session.scoreNotesActive}` →
   `{#if session.scoreNotesActive}` — score data is already available the
   moment `/notedata` resolves, no analysis required.
2. Guarded four `session.analysisResult.X` prop expressions with `?.`
   (`note_data`, `pitch_data`, `vibrato`, `config`) — the review that found
   the original `note_data` gap turned up three more of the same shape once
   the actual edit was made; all four would throw on a null `analysisResult`
   without the top-level `?.`.
3. Updated the placeholder copy (now only shown pre-score-upload) from
   "Upload a score and a recording, then click Analyze..." to "Upload a
   score to see the pitch overlay here."

Verified locally: uploading a score alone (no recording) renders the
MIDI-key rainbow background plus white score-note target bars immediately,
with `analysisResult` still null — no console errors beyond pre-existing,
unrelated fluidsynth WASM init noise.

### 9c. `/realign` endpoint removed (2026-08-12)

Confirmed a no-op (see §4) and removed entirely rather than left as dead
weight. Changes:

- `web/api/analyze_api.py`: deleted `RealignRequest` and the `/realign`
  route; dropped the now-unused `MistakeDetector`/`BaseModel` imports.
- `web/src/realign.js`: deleted outright (both exports, `realign()` and
  `debounce()`, lost their only caller).
- `web/src/sessionState.svelte.js`: dropped `realignedPairs`/`realigning`/
  `realignError` state, `debouncedRealign`, and their getters; simplified
  `currentPairs` to `analysisResult?.alignment?.pairs ?? null`;
  `setPitchTolerance` is now a plain synchronous assignment.
- `web/src/ResultsView.svelte`: removed the now-permanently-dead
  "Realigning..."/error status block and its now-unused CSS.
- Docs: `web/docs/api-design.md`'s `POST /realign` section rewritten as a
  historical "removed — here's why" note rather than deleted, since the
  underlying lesson (a refactor to code an endpoint calls into can silently
  invalidate the endpoint's premise, with nothing to catch it) is worth
  keeping; `web/README.md`'s file-tree references removed.

Net effect: the pitch-tolerance slider went from "debounced network call
that always returned the same answer" to a plain synchronous local
reclassification — same visible behavior, one fewer moving part.

## 10. Deployment mechanics

- Amplify auto-build depends on the GitHub connection type — the newer
  "Amplify GitHub App" integration is required for reliable webhook
  triggers; the older OAuth/token connection (`repositoryCloneMethod:
  "TOKEN"`) is less reliable. Manual redeploy fallback:
  `aws amplify start-job --app-id dz0hpijjgdav5 --branch-name main --job-type RELEASE`.
- Git remotes: `origin` = `Gbeckler8/TuneBuddy` (what Amplify watches),
  `upstream` = `hyuncat/Attune` (source repo). Local `main` must track
  `origin`, not `upstream`.
- Backend is **ECS** (an "Express service," not App Runner — §1/§3's "App
  Runner/ECS" hedge is resolved). Cluster `default`, service
  `attune_api-4ea0`, ECR repo
  `921135845455.dkr.ecr.us-east-1.amazonaws.com/attune_api`. No CI/CD - a
  redeploy is manual every time:
  ```
  docker build --platform linux/amd64 -t attune-api .
  aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 921135845455.dkr.ecr.us-east-1.amazonaws.com
  docker tag attune-api:latest 921135845455.dkr.ecr.us-east-1.amazonaws.com/attune_api:latest
  docker push 921135845455.dkr.ecr.us-east-1.amazonaws.com/attune_api:latest
  aws ecs update-service --cluster default --service attune_api-4ea0 --force-new-deployment --region us-east-1
  ```
  A cold rollout took ~9 minutes end-to-end in practice (new task pull +
  boot + ALB health check before the old task drains) - not a hang, just
  the PyQt6-import-at-startup cost plus health-check polling interval.
  Verify a redeploy landed by re-running `/analyze` against a known
  fixture (e.g. `flute_scale_bad.m4a`) and checking the timing-mistake
  count/shape matches §9a's "4 varied mistakes," not the old near-uniform
  late-note pattern - confirmed working 2026-08-20.
- The frontend's backend URL is `VITE_API_URL` (Amplify build env var;
  falls back to `http://localhost:8000` in dev - `sessionState.svelte.js:16`).
  Recreating the ECS cluster/service (e.g. to rename it - cluster names are
  immutable once created) changes the ALB DNS name and requires updating
  this env var + an Amplify rebuild, or the deployed frontend silently
  points at a dead backend.

## 11. GuitarHero pitch overlay: canvas/SVG split (planned)

### 11a. Problem

`NoteOverlay.svelte` renders the entire take into one fixed-size (800x280)
inline SVG, mapping the full `[minTime,maxTime]`/`[minPitch,maxPitch]` range
onto that box every time (`NoteOverlay.svelte:156-174`). Desktop's
equivalent (`ui/guitarhero/GuitarHero.py`, `pyqtgraph`) is a real pannable/
zoomable viewport with a scrolling playback window (`move_plot`,
`timeline_offset` - `GuitarHero.py:168-192`); web has no viewport concept at
all - the whole take is always visible, scaled to fit. Closing that gap
means adding pan/zoom and a scrolling-window-follows-playhead behavior, and
doing it naively (SVG DOM scaling with take length + per-tick coordinate
recompute on every pan/zoom frame) would reintroduce exactly the kind of
perf problem `pyqtgraph`'s GPU-backed scenegraph never has: thousands of
`<circle>` pitch dots is real DOM/memory overhead regardless of viewport,
and recomputing every dot's `cx`/`cy` on every drag/zoom frame (vs. Desktop's
cheap GPU transform) can blow the 60fps frame budget during exactly the
interactions - drag, scrub - that most need to feel responsive.

**Validated against real data (2026-08-20), not just worst-case reasoning.**
Decompressed `.flute_scale_bad.json.xz` (pulled from `git show HEAD:...` -
deleted in the working tree but still in history) and counted
`pitch_data.pitches`: 4,094 frames over 10.915s = **~375 frames/sec**
(2.67ms hop). That's denser than the 50-100Hz assumed earlier when this
design was first discussed in the abstract. Extrapolated to realistic take
lengths:

| Recording length | Pitch dots (SVG `<circle>` elements if unsplit) |
|---|---|
| 10s (`flute_scale_bad` itself) | 4,094 |
| 3 min | ~67,500 |
| 4 min | ~90,000 |
| 5 min | ~112,500 |

A 3-5 minute take is **60K-110K+ DOM nodes** under the current pure-SVG
approach, not "a few thousand" - the short demo fixtures (all ~10s) mask
this entirely, which is why it wasn't obvious without decompressing real
pitch data. This is well past the point where "maybe plain SVG + a viewport
is good enough, skip canvas" is a reasonable call - at this density, canvas
for the pitch-dot layer isn't premature optimization, it's addressing a
measured problem. (Contrast with §11c's typed-array reversal, where the
optimization *was* premature - the difference is this one has a number
behind it and that one didn't.)

### 11b. Design: split rendering, one shared viewport

Two layers, stacked in a common absolutely-positioned container, same
width/height:

- **Canvas layer** (new `PitchCanvas.svelte`) - the high point-count data:
  MIDI background stripes/gridlines (Desktop's `MidiBackground.py`
  equivalent), pitch dots, playhead line. Owns one `<canvas>`, redraws
  imperatively via `requestAnimationFrame` (not Svelte-diffed) whenever
  `viewport` or pitch data changes. Canvas has no retained-DOM cost, so a
  full redraw of a viewport's worth of dots is cheap by construction - this
  is what avoids the expensive-recompute failure mode without needing
  `pyqtgraph`'s GPU transform trick.
- **SVG/DOM layer** (trimmed `NoteOverlay.svelte`) - the low element-count,
  interactive data: note bars, alignment/match lines, mistake highlight
  boxes, click/hover hit-testing, the `NotePopupGH`-equivalent popup,
  keyboard note-stepping, color-mode dropdown. Tens of elements, not
  thousands - plain reactive Svelte recomputing pixel positions every tick
  is fine here, no special-casing needed.
- **Shared `viewport` state** (new `.svelte.js` module) -
  `{t0, t1, pitchMin, pitchMax, width, height}`, the single source of truth
  for the time<->pixel mapping. Both layers import the same transform
  function from it; if they ever computed their own transforms independently
  they'd drift out of pixel alignment (a note box not lining up with its
  pitch dots). Driven by `playback.svelte.js`'s tick the same way Desktop's
  `WallClock` drives `move_plot` - mirrors the imperative-push pattern
  already adopted for the score viewer (§6, commit `90a9080`).

### 11c. Mitigations designed in from the start

- Redraws throttled to `requestAnimationFrame`, decoupled from the 10Hz
  playback poll (`playback.svelte.js:27`) - dragging/zooming redraws at
  display refresh rate; playback-driven redraws piggyback on the same rAF
  loop instead of firing their own writes per tick.
- MIDI background pre-rendered once as an offscreen bitmap and blitted,
  mirroring Desktop's `pg.ImageItem` - removes it from the per-frame cost
  entirely.
- Device-pixel-ratio-aware canvas sizing for retina sharpness.
- Pitch data stays a plain array of `{time, pitch, volume}` objects, matching
  the JSON `/analyze` already returns - reconsidered from an earlier draft
  that specced `Float32Array`s. Rejected as premature: the canvas layer
  already removes the actual bottleneck (retained-DOM cost), which is
  independent of how the point data is stored, so iterating plain objects in
  a `requestAnimationFrame` callback isn't expected to be the thing that
  costs a frame budget - canvas draw calls will dominate first. Typed arrays
  would also cost real readability (`data[i*3+1]` vs. `points[i].pitch`) and
  require a conversion step from the API's JSON shape, for a benefit
  (cheap-append for a live feed) that's speculative against work not yet
  scoped (§11d). Revisit only if live-streaming work actually happens and
  profiling then shows object-array iteration is a real cost - not before.
- **Level-of-detail (implemented 2026-08-20, `PitchCanvas.svelte`'s
  `visiblePoints()`)**: not just a nice-to-have - a synthetic benchmark
  (same point count/color/draw pattern as real `draw()`, run in-browser)
  measured actual per-redraw cost scaling with take length: 10s (~4K pts)
  ~2ms, 3min (~67.5K pts) ~23-27ms, 5min (~112.5K pts) ~42-66ms with one
  132ms spike. That 3-5min range is 1.5-4x over a 16.67ms/60fps budget -
  and critically, `TransportBar.svelte`'s scrub slider already fires
  `oninput`->`playback.seek()` continuously while dragging (rAF-coalesced
  by `scheduleDraw`'s guard, but still up to ~60 redraws/sec), so this was
  reachable through an *already-shipped* interaction the moment someone
  analyzes a real multi-minute take, not a hypothetical future pan/zoom
  concern. Below `LOD_DENSITY_THRESHOLD` (2 points/pixel-column) it's a
  no-op - identical behavior/output to before for short or zoomed-in views.
  Above it, points are bucketed by pixel column and only the most-severe
  point per bucket is kept (furthest off-pitch in pitch mode, loudest in
  volume mode - biases toward not hiding mistakes when zoomed out, at the
  cost of a zoomed-out view no longer being a literal 1:1 picture of every
  frame). Re-ran the same synthetic benchmark post-fix: draw cost flattens
  to ~2-3ms across the entire 10s-5min range, bounded by canvas width
  (~800 draw calls) instead of take length. Verified visually against a
  real `/analyze` run (`major.mxl` + `flute_scale_bad.m4a`) that the
  bucketed output still looks correct - the pitch trace's shape and
  green/yellow/red coloring are unchanged from the pre-LOD render.
- No canvas-level hit-testing planned - dot-level hover isn't current
  behavior (only note-level hover is), so the canvas layer stays purely
  presentational and doesn't need to reimplement what the DOM's event
  system already gives the SVG layer for free.

### 11d. Compatibility with a future live/realtime pitch feed

Not being built now (`JSPitchDetector.js` is prepared but unwired scaffolding
- see §8's Practice-tab scope-out), but the viewport design above is
specifically so this doesn't require a rendering rewrite later: a live feed
becomes another source appending into the same array the canvas layer
already reads, with `viewport` tracking the recording head instead of a
scrubber position. The one thing that would force a redo is if the canvas
layer's *redraw strategy* recomputed full-resolution point positions from
scratch on every frame regardless of what changed - fine for post-hoc
scrubbing at a fixed data size, but worth re-profiling once a live feed is
actually appending at pitch-detection sample rate (50-100Hz); if array
iteration turns out to matter at that point, that's the moment to consider
typed arrays - informed by a real workload instead of a guess now.

### 11e. Status

Implemented and verified 2026-08-20:
- `web/src/viewportState.svelte.js` - the shared viewport state module (§11b).
- `web/src/pitchColorRamp.js` - `alignHue`/`hsl` extracted so `NoteOverlay`
  and `PitchCanvas` draw from one color ramp instead of two copies.
- `web/src/PitchCanvas.svelte` - the canvas layer (MIDI background, pitch
  dots with LOD bucketing, playhead), including the `ResizeObserver` that
  measures real container pixels and drives `viewport.setSize(...)` for
  both layers.
- `web/src/NoteOverlay.svelte` trimmed to the SVG/DOM layer (note bars,
  match lines, hit-testing, popup, legend), reading `viewport.width/height`
  for its `viewBox` instead of a fixed constant.

Verified: renders correctly pre-analysis (note bars only) and post-analysis
(dots + note bars) against a real `/analyze` run; pixel-aligned across both
layers at actual measured container width; LOD-bucketed draw cost is flat
~2-3ms from 10s to 5min of take length (was 23-66ms at the 3-5min end
before the LOD pass - see §11c).

Pan/zoom wired up 2026-08-20, in `NoteOverlay.svelte` (the top-most SVG
layer, since it already receives pointer events - `PitchCanvas` underneath
just reacts to `viewport` changing, same as it already did for the
playhead):
- **Drag** (`mousedown`+`mousemove`+`mouseup`, listened on `svelte:window`
  for move/up so a drag continues even if the cursor leaves the SVG) pans
  both time and pitch axes together, computed from the drag's *original*
  start bounds plus cumulative pixel delta (not incremental `panBy` calls
  per move event) to avoid rounding drift. A 3px movement threshold
  (`didDrag`) distinguishes an actual drag from a plain click, so dragging
  doesn't also fire `closePopup`/note-select - the browser still dispatches
  a `click` after `mouseup`, so `handleOverlayClick` checks and swallows it
  when a real drag happened.
- **Wheel** zooms both axes together, centered on the cursor's
  time/pitch position (`viewport.xToTime`/`yToPitch` at the event's offset),
  mirroring Desktop's pyqtgraph ViewBox default (`ev.preventDefault()` stops
  the page from scrolling instead).
- **Double-click** calls `viewport.resetView()` - snaps back to fully
  zoomed out.

Verified against a real `/analyze` run: wheel-zoom centered on the middle
of the take visibly enlarged the MIDI bands and dot spacing, with note-bar
x-positions shifting to match; drag-pan shifted positions by the expected
direction and (correctly clamped) magnitude; double-click-reset returned
note-bar x-positions to byte-identical values as the pre-interaction render;
note click-to-select (`.user-note-hit` -> popup) still works unchanged,
confirming pan/zoom didn't regress the existing click/hover interactivity.

Auto-follow (Desktop's `move_plot`/`timeline_offset` scrolling-window
behavior) wired up 2026-08-20:
- `viewport.follow(t, offsetFrac=0.3)` (`viewportState.svelte.js`) slides
  the window - preserving its current zoom span - so `t` sits 30% from the
  left edge (a judgment call, not a copied Desktop constant - not available
  to check against). A no-op while zoomed all the way out (span == full
  content, nowhere to slide within clamp bounds), matching-only-visible
  once the user has zoomed in.
- A new `followEnabled` flag on `viewport` (default `true`) gates it.
  `NoteOverlay.svelte`'s `handleBackgroundMouseDown`/`handleWheel` call
  `viewport.disableFollow()` at the start of any manual pan/zoom - without
  this, the next `currentTime` tick (up to 10x/sec during playback) would
  immediately undo the user's own drag/zoom. `handleDoubleClick` calls
  `viewport.enableFollow()` alongside its existing `resetView()`, since a
  full reset is the natural "give control back to auto-follow" signal.
- A new `$effect` in `NoteOverlay.svelte` calls `viewport.follow(currentTime)`
  whenever `followEnabled` is true and `currentTime` is set - reacts to any
  `currentTime` change (playback ticks or manual scrub-slider drags alike),
  not just active playback specifically.

Verified via a temporary `window.__viewport` debug hook (added, tested,
removed - not left in the shipped code): narrowed the window to a 2s span
via the singleton directly (bypassing the wheel handler's disableFollow, to
isolate follow's own math), then drove the *actual* transport slider
(`.transport-slider` - the first test attempt accidentally drove the
pitch-tolerance slider instead, since both range inputs matched a loose
`max > 1` selector, and showed no movement; querying by class name fixed
it) through several seek points. Observed `t0`/`t1` tracking exactly to the
`t - 0.3*span` formula at each step, including correct clamping at the
take's end (`contentT1`) rather than overshooting. Separately confirmed
`followEnabled` flips to `false` after a wheel event and back to `true`
after a double-click, matching the disable/re-enable design above.

**Root-caused and fixed 2026-08-20: the default zoom itself, not a width
floor.** A user report ("note bars for a longer score are really thin")
was first patched with a `MIN_BAR_WIDTH` floor on the SVG rects - wrong
fix, per the same user's follow-up: the actual bug was that
`fitToContent` always squeezed the take's *entire* duration into view by
default, so a long score's real per-note pixel-width rounds toward
nothing regardless of any floor, and a floor just forces every note to
the same fake width, destroying the duration information the user
explicitly wanted preserved ("durations should be directly proportional
to widths"). The width floor is real defensive code (`MIN_BAR_WIDTH = 1`,
guards a literal 0px rect from float rounding), not what fixes
readability.

The actual fix, mirroring Desktop's GuitarHero (it never fits an entire
multi-minute take into the plot at once - see §11a): `fitToContent`
(`viewportState.svelte.js`) now defaults to a **fixed pixels-per-second
density** (`DEFAULT_PX_PER_SEC = 30`) instead of the take's full span,
clamped so a take shorter than the resulting window still shows in full
(`Math.min(contentSpan, width / DEFAULT_PX_PER_SEC)`). A long take now
gets a comfortable, genuinely-proportional default slice instead of
being squeezed - the rest is reached via the pan/zoom/auto-follow already
built (§11e above), all of which needed no changes since they already
operate on an arbitrary current window, not specifically "the whole take."

Density was tuned once by testing, not guessed once and shipped: 60px/sec
was tried first and rejected - verified against `major.mxl` (8s, one of
the existing short demo clips) that even that short take no longer fit by
default at 800px container width (`minX/maxX` outside `[0, width]`),
which is a bigger behavior change than intended (only long takes should
need windowing). 30px/sec was verified to keep every current demo clip
(8-18s) fully visible by default while still properly windowing
`triunfal.mxl` (3:23) - 113 of 634 notes visible in the default window,
widths 3.75-30px (vs. all 634 rendered as identical sub-pixel slivers
before any of this).

**Two more auto-follow issues found and fixed 2026-08-20, from a user
report that follow "isn't working" in their own browser (both local dev
and the deployed Amplify build), after a session of testing drag/zoom:**

1. **Reactivity over-firing (efficiency, not correctness).** Re-verifying
   follow with a temporary `window.__viewport` debug hook + a monkey-patched
   `follow()` call counter (installed, used, removed - not shipped) found
   it firing ~73x/sec during real playback against a 10Hz `currentTime`
   poll. Cause: `follow()` reads `viewport.t0`/`t1` internally (to preserve
   the current zoom span) - without guarding that read, it becomes a
   tracked dependency of the *same* `$effect` that calls `follow()`, so the
   effect's own write re-triggers itself. Each extra run was a stable
   no-op once converged (not runaway drift), but still ~7x wasted reactive
   work. Fixed by wrapping the call in Svelte's `untrack()`
   (`NoteOverlay.svelte`), confirmed by re-measuring the steady-state
   rate: exactly 10.0/sec after the fix.
2. **The actual bug the user hit.** `handleBackgroundMouseDown`/
   `handleWheel` call `viewport.disableFollow()` at the start of *any*
   manual pan/zoom - correct in isolation (a drag shouldn't fight the next
   currentTime tick), but the only way back was an undocumented
   double-click, with zero visible indicator that follow had silently
   turned off. A user who drags/zooms once while exploring the overlay -
   exactly what testing pan/zoom naturally involves - loses auto-follow
   for the rest of the session, which reads as "it doesn't work" rather
   than "it's toggled off." Fixed in `playback.svelte.js`'s `play()`:
   calls `viewport.enableFollow()` on every Play press, not just the
   first, so pausing to look around and then resuming playback always
   restores follow, regardless of pan/zoom in between. Reproduced the
   exact reported sequence (drag -> `followEnabled` false -> press Play ->
   `followEnabled` true, window immediately tracking real `currentTime`
   again) and confirmed the fix closes it.

**Known remaining gap, not yet addressed:** dragging/zooming *while
already playing* (without pausing first) still suspends follow until the
next Play press, since `enableFollow()` only fires from `play()`. Whether
that should also auto-resume (e.g., a short time after the last manual
interaction, even mid-playback) is a real UX tradeoff against fighting an
active pan - deliberately left as-is pending user feedback on whether the
Play-press fix above is sufficient.

**A third, more serious bug found immediately after, from asking "does
re-arming on Play also restart the actual playback position?" - it did,
and this one predates all of today's viewport work entirely.**
`play()` calls `reload()` unguarded (`if (lastLoadedKey == null) await
reload();`) on the first Play press after a score loads. `reload()`
(`playback.svelte.js:163`) only computes `resumeTicks` - the position to
seek the freshly-rebuilt SMF player to - when `wasPlaying || resume` is
true. On that first Play press, `isPlaying` is still `false` (it's only
set `true` further down in `play()`, after `reload()` returns) and
`resume` defaults to `false`, so if the user had seeked to a nonzero
`currentTime` while paused (exactly what testing pan/zoom naturally
involves), the seek was silently dropped: the SMF rebuilt fresh and
playback started from tick 0, while `currentTime` itself (a separate
piece of state, not read back from the synth) still displayed the old
seeked value until the poll loop overwrote it a moment later - reading as
"playback restarted" because the *audio* genuinely did, even though nothing
about the pitch overlay was the cause.

Reproduced precisely via temporary `window.__playback`/`window.__viewport`
debug hooks (added, used, removed): `seek(60)` -> drag the overlay (view
pans, `followEnabled` -> `false`, `currentTime` still `60`, confirming the
drag itself never touches playback state) -> press Play -> `currentTime`
observed at `~5` moments later (i.e., counting up from near 0, not from
60). Fixed by passing `{ resume: true }` to that one `reload()` call in
`play()` - harmless when `currentTime` is already 0 (`secondsToTicks(0,
...)` is 0, so the resume-seek is skipped, identical to before for an
ordinary from-the-start Play). Re-ran the identical repro post-fix:
`currentTime` observed at `64.9` after the same sequence - correctly
continuing from the seeked 60, not restarting.

This bug is unrelated to the canvas/SVG split or viewport work (§11) - it
lives entirely in `playback.svelte.js`'s pre-existing reload/resume logic
- but calling `viewport.enableFollow()` from `play()` made it something a
user would actually notice: re-arming follow on every Play press means
Play now gets pressed (and this bug triggered) far more often during
normal pan/zoom exploration than before.

## 12. Pitch transpose (implemented 2026-08-21)

Previously a disabled UI placeholder (`SettingsPanel.svelte`'s Transpose
row shipped `disabled` from the start, with a comment admitting "nothing
sends it yet"). Note there are two unrelated, confusingly similarly-named
fields: `transpose_offset` (a TIME offset, already wired through
`scoreTimeMap.js` for score-alignment, unrelated to this feature) and
`transpose_semitones` (the actual PITCH shift, what this section is
about).

**Backend** (`web/api/analyze_api.py`): both `/notedata` and `/analyze`
gained an optional `transpose_semitones: int | None = Form(None)` param.
Applied via `score_data.transpose(dy=transpose_semitones)` immediately
after `ScoreData.load()`/`_parse_uploaded_score()`, before
`Recording`/`PitchDetector`/`MistakeDetector` ever see the score - so
pitch detection, alignment, and mistake classification all run against
the transposed score, mirroring desktop's `on_transpose_applied ->
update_alignment_distances()` re-scoring. Always the TOTAL shift from the
original score, not an incremental delta - unlike desktop's long-lived
`ScoreData` (which accumulates `transpose_semitones` across repeated
calls), this endpoint reloads the score fresh from the uploaded file
every request, so there's no persisted state to apply a delta against.

**Client-side cache** (`noteDataCache.js`): `getNoteData(scoreFile,
apiBaseUrl, semitones = 0)` - the cache key became `` `${fileHash}:${semitones}` ``
instead of just the file hash, so a transposed and untransposed request
for the same file are independent cache entries, not a mutation of one.
Switching transpose back to a previously-tried value (including 0) is an
instant cache hit.

**Session state** (`sessionState.svelte.js`): `transposeSemitones` (total
from original, reset to 0 in `pickScore`) + `setTranspose(targetNoteName)`.
UX mirrors desktop exactly: the user types a target note name (e.g. "D4"),
not a raw semitone count. Computes the incremental nudge from
`firstNoteMidiForActiveInstrument()` (the CURRENT first note - reflects
any transpose already applied) to the target, adds it to the running
total, re-fetches at that total, and - mirroring desktop's re-scoring
behavior - automatically re-runs `/analyze` if a take already exists
(`audioFile && analysisResult`), since otherwise the mistake table/pitch
overlay would keep comparing user notes against the OLD score. A new
`firstNoteName` getter drives `SettingsPanel.svelte`'s input syncing to
the current first note whenever score/instrument/transpose changes,
mirroring `SettingsWidget._sync_transpose_input`.

**UI** (`SettingsPanel.svelte`): un-disabled, wired `applyTranspose()`
following the exact same pattern as `applyRange`/`applyTuning`, added a
`transposeError` display row matching the existing `rangeError` one.

**Verified end-to-end** via temporary `window.__session` (plus
`window.__viewport`/`window.__playback` from earlier work) debug hooks -
added, used, removed, not shipped - against a real `/notedata` + `/analyze`
round trip (`major.mxl` + `flute_scale_bad.m4a`):
- Transpose input correctly synced to "C4" (the score's real first note)
  on load.
- Applying "D4" shifted `transposeSemitones` 0 -> 2 and note MIDI values
  `[60,62,64] -> [62,64,66]` (exactly +2) - both in the pre-analysis
  `/notedata` payload and, after clicking Analyze, in a real `/analyze`
  result (8 pitch mistakes returned - a real classification, not an
  error).
- With that analysis already in hand, applying "C4" again correctly
  auto-triggered a fresh `/analyze` call (`analysisResult` object
  identity changed, mistake count changed 8 -> 7, matching the
  now-different alignment) and reverted note MIDI back to the original
  `[60,62,64]`.
- Invalid input ("not-a-note") produced the expected parse error
  (`transposeError` set, rendered in `.field-error`) without corrupting
  `transposeSemitones` (stayed at 0).

**Semantic verification (not just mechanical):** confirmed
`transpose_semitones` genuinely changes what `/analyze`'s alignment
considers correct, not just a display shift. Using `flute_scale_good.m4a`
(a clean take, not the intentionally-flawed `_bad` one) against `major.mxl`:
2 pitch mistakes at 0 semitones (matching key - a good take should score
well). Transposing to D4 (+2 semitones, still the same recording) jumped
that to 6 mistakes (mostly `substitution`, one `deletion`) - the singer/
flute is still playing the C major scale, but the score now expects D
major, and the analyzer correctly flags most notes as wrong. A
cosmetic-only implementation (shifting only what's displayed, not what
`Recording`/`MistakeDetector` actually compare against) would have shown 2
mistakes either way.

**Range fields sync too**, confirmed separately: `lowNoteName`/
`highNoteName` went from `C4`-`C5` to `D4`-`D5` on the same +2 transpose -
an exact +2 shift, matching Desktop's `_sync_range_after_transpose(delta)`.
Implemented differently (a full recompute from the now-transposed note
data via the existing `applyDefaultRangeForActiveInstrument()`, rather than
sliding the two numbers by `delta` the way desktop does) but produces the
same result - and arguably more robust, since a recompute can't drift from
the note data the way repeated incremental shifts theoretically could.
Tuning (440 Hz) correctly untouched, as expected - transpose has no
tuning-reference implications.

**Not done:** no automated test suite exists anywhere in this repo (no
`pytest.ini`/`conftest.py`/`test_*.py` found on either platform) - adding
one is a separate scope decision (test framework choice, CI wiring) from
this feature, deliberately not made unilaterally. Verification here is
live-browser/API-driven, same approach used throughout this session's
other web work.
