<script>
  // The GuitarHero pitch-dot layer (system_design.md §11): MIDI background
  // stripes + pitch-frame scatter + playhead, drawn on <canvas> instead of
  // SVG. A real recording measures ~375 pitch frames/sec (§11a) - a 3-5
  // minute take is 60K-110K+ points, which would mean that many permanent
  // SVG <circle> DOM nodes if drawn the way NoteOverlay.svelte's note
  // bars/popup/hit-testing still are. Canvas has no retained-DOM cost, so a
  // redraw is cheap regardless of point count.
  //
  // Redraws imperatively on requestAnimationFrame, not via Svelte's DOM
  // diffing, and reads pixel positions from the same shared `viewport`
  // transform NoteOverlay.svelte's SVG layer uses - the single source of
  // truth that keeps the two layers from drifting out of pixel alignment.
  import { getVoicedPitchFrames } from "./PitchFrameHandler.js";
  import { volumeFrac, volumeRangeDb, viridis, cssRgb } from "./colors.js";
  import { alignHue, hsl } from "./pitchColorRamp.js";
  import { viewport } from "./viewportState.svelte.js";

  let {
    pitchFrames = null,
    colorMode = "pitch",
    pitchTolerance = 0,
    currentTime = null,
    hoveredSpan = null,
  } = $props();

  const REST_COLOR = "rgb(140, 140, 140)";
  const BG_COLOR = "rgb(20, 20, 25)";
  const PITCH_DOT_RADIUS = 2.5;
  const HOVER_DOT_OPACITY = 0.35;

  // --- GuitarHero.MidiBackground, ported (also in NoteOverlay.svelte before
  // the split - duplicated here rather than shared, since it's a handful of
  // lines and the two files draw it into fundamentally different targets
  // (canvas fillRect vs SVG rect elements)). ---
  const LETTER_RGB = {
    A: [230, 60, 60], B: [255, 150, 40], C: [245, 220, 70],
    D: [70, 200, 90], E: [70, 140, 240], F: [100, 90, 210], G: [170, 90, 210],
  };
  const PC_TO_LETTER = ["C", "C", "D", "D", "E", "F", "F", "G", "G", "A", "A", "B"];
  const isSharp = (m) => [1, 3, 6, 8, 10].includes(((m % 12) + 12) % 12);
  function midiRgb(m) {
    const letter = PC_TO_LETTER[((m % 12) + 12) % 12];
    let [r, g, b] = LETTER_RGB[letter];
    if (isSharp(m)) { r *= 0.7; g *= 0.7; b *= 0.7; }
    return [Math.round(r), Math.round(g), Math.round(b)];
  }

  // Only the first (most probable) pitch candidate per frame is plotted,
  // matching GuitarHero's `break` after candidate_pitches[0] - ported
  // straight from NoteOverlay's pre-split pitchPoints derivation. Each point
  // also carries a `severity` used only by the level-of-detail pass below -
  // pitch mode prioritizes the most off-pitch frame in a bucket (so a brief
  // bad note stays visible even zoomed out), volume mode prioritizes the
  // loudest.
  let pitchPoints = $derived.by(() => {
    if (!pitchFrames) return [];
    const points = [];
    const volumeRange = colorMode === "volume" ? volumeRangeDb(pitchFrames) : [null, null];
    for (const frame of getVoicedPitchFrames(pitchFrames, -Infinity, Infinity)) {
      const [time, candidates, volume, , , alignedDistance, isTransition] = frame;
      if (!candidates || candidates.length === 0) continue;
      const midi = candidates[0][0];
      let color;
      let severity;
      if (colorMode === "volume") {
        const frac = volumeFrac(volume, volumeRange[0], volumeRange[1]);
        color = cssRgb(viridis(frac));
        severity = volume ?? 0;
      } else {
        color = isTransition
          ? REST_COLOR
          : alignedDistance != null
            ? hsl(alignHue(alignedDistance, pitchTolerance))
            : REST_COLOR;
        severity = isTransition ? -Infinity : (alignedDistance != null ? Math.abs(alignedDistance) : -Infinity);
      }
      points.push({ time, midi, color, severity });
    }
    return points;
  });

  let canvasEl;
  let ctx = null;
  let dpr = 1;

  // The MIDI background only changes when the visible pitch range or the
  // canvas size changes (not every frame, not when dots/playhead move) -
  // pre-rendered to an offscreen canvas and blitted, mirroring Desktop's
  // pg.ImageItem (system_design.md §11c) so it doesn't cost anything on the
  // frames where only the playhead or a dot color changed.
  let bgCanvas = null;
  let bgKey = "";
  function backgroundLayer() {
    const lo = Math.floor(viewport.pitchMin);
    const hi = Math.ceil(viewport.pitchMax);
    const key = `${lo}:${hi}:${viewport.width}:${viewport.height}:${dpr}`;
    if (bgKey === key && bgCanvas) return bgCanvas;
    bgKey = key;
    bgCanvas = document.createElement("canvas");
    bgCanvas.width = Math.max(1, viewport.width * dpr);
    bgCanvas.height = Math.max(1, viewport.height * dpr);
    const bctx = bgCanvas.getContext("2d");
    bctx.scale(dpr, dpr);
    bctx.fillStyle = BG_COLOR;
    bctx.fillRect(0, 0, viewport.width, viewport.height);
    const semitoneHeight = viewport.height / (viewport.pitchMax - viewport.pitchMin || 1);
    for (let m = lo; m <= hi; m++) {
      const [r, g, b] = midiRgb(m);
      bctx.fillStyle = `rgba(${r}, ${g}, ${b}, 0.2)`;
      bctx.fillRect(0, viewport.pitchToY(m + 0.5) - semitoneHeight / 2, viewport.width, semitoneHeight);
    }
    return bgCanvas;
  }

  // Level-of-detail (system_design.md §11c/§11e): a real take runs ~375
  // pitch frames/sec (§11a), so a fully-zoomed-out 3-5 minute view can have
  // 100+ frames landing on the same pixel column - drawing all of them
  // measured 23-66ms/frame in practice, well past a 60fps budget, and the
  // scrub slider (TransportBar.svelte) already drives redraws at up to 60Hz
  // while dragging. Below LOD_DENSITY_THRESHOLD points-per-pixel this is a
  // no-op (every point drawn, unchanged behavior for short/zoomed-in views);
  // above it, bucket by pixel column and keep only the most severe point per
  // bucket, so draw cost stays bounded by canvas width instead of take
  // length regardless of zoom.
  const LOD_DENSITY_THRESHOLD = 2; // points per pixel column before bucketing kicks in

  function visiblePoints() {
    const visible = [];
    for (const p of pitchPoints) {
      if (p.time < viewport.t0 || p.time > viewport.t1) continue;
      visible.push(p);
    }
    if (visible.length <= viewport.width * LOD_DENSITY_THRESHOLD) return visible;

    const buckets = new Map(); // pixel column -> most severe point in it
    for (const p of visible) {
      const col = Math.floor(viewport.timeToX(p.time));
      const existing = buckets.get(col);
      if (!existing || p.severity > existing.severity) buckets.set(col, p);
    }
    return [...buckets.values()];
  }

  function draw() {
    if (!ctx) return;
    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, viewport.width, viewport.height);
    ctx.drawImage(backgroundLayer(), 0, 0, viewport.width, viewport.height);

    for (const p of visiblePoints()) {
      const dimmed = hoveredSpan && p.time >= hoveredSpan[0] && p.time <= hoveredSpan[1];
      ctx.globalAlpha = dimmed ? HOVER_DOT_OPACITY : 1;
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(viewport.timeToX(p.time), viewport.pitchToY(p.midi), PITCH_DOT_RADIUS, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (currentTime != null && currentTime >= viewport.t0 && currentTime <= viewport.t1) {
      const x = viewport.timeToX(currentTime);
      ctx.strokeStyle = "rgb(0, 255, 0)"; // GuitarHero.timeline: solid green
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, viewport.height);
      ctx.stroke();
    }
    ctx.restore();
  }

  let rafHandle = null;
  function scheduleDraw() {
    if (rafHandle != null) return;
    rafHandle = requestAnimationFrame(() => {
      rafHandle = null;
      draw();
    });
  }

  // Reruns whenever anything draw() depends on changes value - schedules a
  // redraw instead of drawing inline, so rapid updates (a fast scrub) still
  // only pay for one draw per actual animation frame.
  $effect(() => {
    pitchPoints;
    colorMode;
    currentTime;
    hoveredSpan;
    viewport.t0;
    viewport.t1;
    viewport.pitchMin;
    viewport.pitchMax;
    viewport.width;
    viewport.height;
    scheduleDraw();
  });

  // Owns sizing: measures its own rendered box and pushes real pixel
  // dimensions into the shared viewport, so both this canvas and
  // NoteOverlay's SVG (which reads viewport.width/height for its own
  // viewBox) size themselves off the same real container size rather than
  // an abstract fixed unit box - keeps them pixel-aligned at any panel width.
  $effect(() => {
    if (!canvasEl) return;
    ctx = canvasEl.getContext("2d");
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect;
      dpr = window.devicePixelRatio || 1;
      viewport.setSize(Math.max(1, Math.round(rect.width)), Math.max(1, Math.round(rect.height)));
      canvasEl.width = Math.max(1, Math.round(rect.width) * dpr);
      canvasEl.height = Math.max(1, Math.round(rect.height) * dpr);
      bgKey = ""; // size changed - force the background to re-render
      scheduleDraw();
    });
    ro.observe(canvasEl);
    return () => ro.disconnect();
  });
</script>

<canvas bind:this={canvasEl} class="pitch-canvas"></canvas>

<style>
  .pitch-canvas {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 280px;
    background: rgb(20, 20, 25);
    border: 1px solid var(--border);
    border-radius: 4px;
  }
</style>
