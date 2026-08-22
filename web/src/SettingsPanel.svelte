<script>
  // Ports ui/info/SettingsWidget.py's row structure exactly: Instrument,
  // Range, Tuning, Transpose, each a label + control(s) + checkmark Apply
  // button, all wired to something real. Transpose maps to
  // ScoreData.transpose(dy=...) server-side (analyze_api.py's /notedata and
  // /analyze both accept transpose_semitones) - distinct from
  // ScoreData.transpose_offset, an unrelated TIME-alignment field with a
  // confusingly similar name (see scoreTimeMap.js).
  import { session } from "./sessionState.svelte.js";

  const ICONS = "/icons";

  let pendingInstrument = $state(null);
  $effect(() => {
    // reset the pending selection to whatever's actually active whenever a
    // new score loads, mirroring SettingsWidget syncing on score/recording
    // change rather than carrying over a stale pending value.
    pendingInstrument = session.activeInstrument;
  });

  function applyInstrument() {
    if (pendingInstrument != null) {
      session.setSelectedInstrument(pendingInstrument);
    }
  }

  // Range defaults to the score's own pitch span (see sessionState's
  // computeDefaultRange) the moment a score loads or the instrument
  // changes - these mirror that committed value until the user edits and
  // applies their own.
  let pendingLow = $state(session.lowNoteName);
  let pendingHigh = $state(session.highNoteName);
  $effect(() => {
    pendingLow = session.lowNoteName;
    pendingHigh = session.highNoteName;
  });

  function applyRange() {
    session.setRange(pendingLow.trim(), pendingHigh.trim());
  }

  let pendingTuning = $state(session.tuning);
  $effect(() => {
    pendingTuning = session.tuning;
  });

  function applyTuning() {
    session.setTuning(parseFloat(pendingTuning));
  }

  // Syncs to the active instrument's CURRENT first note whenever score/
  // instrument/transpose changes - mirrors SettingsWidget's
  // _sync_transpose_input, so the field always shows "what note does the
  // piece start on right now" rather than carrying over a stale typed value.
  let pendingTranspose = $state(session.firstNoteName);
  $effect(() => {
    pendingTranspose = session.firstNoteName;
  });

  function applyTranspose() {
    session.setTranspose(pendingTranspose.trim());
  }
</script>

<div class="settings-panel">
  <div class="row">
    <label for="instrument-select">Instrument:</label>
    <select
      id="instrument-select"
      bind:value={pendingInstrument}
      disabled={!session.noteData}
    >
      {#if session.noteData}
        {#each session.noteData.instruments as ch}
          <option value={ch}>Channel {ch}</option>
        {/each}
      {/if}
    </select>
    <button class="apply-btn" onclick={applyInstrument} disabled={!session.noteData} title="Apply instrument">
      <img src="{ICONS}/check.svg" alt="Apply" />
    </button>
  </div>

  <div class="row">
    <label for="range-low">Range:</label>
    <input id="range-low" type="text" placeholder="G3" bind:value={pendingLow} />
    <span class="sep">—</span>
    <input type="text" placeholder="E7" bind:value={pendingHigh} />
    <button class="apply-btn" onclick={applyRange} title="Apply frequency range">
      <img src="{ICONS}/check.svg" alt="Apply" />
    </button>
  </div>
  {#if session.rangeError}
    <p class="field-error">{session.rangeError}</p>
  {/if}

  <div class="row">
    <label for="tuning-input">Tuning:</label>
    <input id="tuning-input" type="text" bind:value={pendingTuning} />
    <span class="sep">Hz</span>
    <button class="apply-btn" onclick={applyTuning} title="Apply tuning">
      <img src="{ICONS}/check.svg" alt="Apply" />
    </button>
  </div>

  <div class="row">
    <img src="{ICONS}/circle-help.svg" alt="" class="help-icon" title="Shift the score's displayed/matched pitch by a fixed interval." />
    <label for="transpose-input">Transpose:</label>
    <input id="transpose-input" type="text" placeholder="C4" bind:value={pendingTranspose} disabled={!session.noteData} />
    <button class="apply-btn" onclick={applyTranspose} disabled={!session.noteData} title="Apply transpose">
      <img src="{ICONS}/check.svg" alt="Apply" />
    </button>
  </div>
  {#if session.transposeError}
    <p class="field-error">{session.transposeError}</p>
  {/if}
</div>

<style>
  /* The scroll area content sits on the base QWidget background, not the
     input-family gray. */
  .settings-panel {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 8px;
    background: var(--bg-window);
    border-top: 1px solid var(--border);
    font-size: 0.8rem;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  /* QLabel isn't dimmed - full-strength text, same as everything else */
  .row label {
    color: var(--text);
    width: 62px;
    flex-shrink: 0;
  }
  /* QLineEdit/QComboBox: bg #3f4042, 4px radius, accent focus border */
  .row input,
  .row select {
    flex: 1;
    min-width: 0;
    background: var(--bg-surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px 4px;
  }
  .row input:focus,
  .row select:focus {
    outline: none;
    border-color: var(--accent);
  }
  .row input:disabled,
  .row select:disabled {
    color: var(--text-disabled);
  }
  .sep {
    color: var(--text);
  }
  .field-error {
    color: var(--danger);
    font-size: 0.75rem;
    margin: -2px 0 0;
  }
  /* QPushButton (icon-only, 28x28): bordered, transparent at rest,
     accent-tinted hover/pressed. */
  .apply-btn {
    width: 24px;
    height: 24px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 3px;
    cursor: pointer;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .apply-btn:hover:not(:disabled) {
    background: var(--accent-hover-bg);
  }
  .apply-btn:active:not(:disabled) {
    background: var(--accent-pressed-bg);
  }
  .apply-btn:disabled {
    border-color: transparent;
    cursor: default;
    opacity: 0.4;
  }
  .apply-btn img {
    width: 16px;
    height: 16px;
  }
  .help-icon {
    width: 14px;
    height: 14px;
    opacity: 0.7;
    flex-shrink: 0;
  }
</style>
