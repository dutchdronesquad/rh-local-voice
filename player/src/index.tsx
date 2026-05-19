import { SendspinPlayer } from "@sendspin/sendspin-js";
import type { CorrectionMode, GroupUpdatePayload, ServerStatePayload, StreamFormat } from "@sendspin/sendspin-js";
import { ChevronRight, Play, Volume2, VolumeX } from "lucide-preact";
import { render } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import "./style.css";

type ConnectionState = "disconnected" | "connecting" | "connected" | "playing" | "error";

type PlayerSnapshot = {
  isPlaying: boolean;
  volume: number;
  muted: boolean;
  playerState: string;
  groupState?: string;
  format: StreamFormat | null;
  syncErrorMs: number | null;
  outputLatencyMs: number | null;
  correctionMethod: string;
  playbackRate: number | null;
  timeSynced: boolean;
};

type LogEntry = {
  id: number;
  kind: "info" | "warn" | "error" | "play";
  message: string;
};

type PlayerEventState = {
  isPlaying: boolean;
  volume: number;
  muted: boolean;
  playerState: string;
  serverState: ServerStatePayload;
  groupState: GroupUpdatePayload;
};

type DetailLogState = {
  correctionMethod: string;
  formatKey: string | null;
  groupPlayback: string | null;
  latencyBucket: number | null;
  syncBucket: number | null;
  timeSynced: boolean;
  trackLabel: string | null;
};

const STORE_SERVER_URL = "localVoice.player.serverUrl";
const STORE_VOLUME = "localVoice.player.volume";
const STORE_MUTED = "localVoice.player.muted";
const STORE_MODE = "localVoice.player.correctionMode";
const STORE_PLAYER_ID = "localVoice.player.id";
const DEFAULT_VOLUME = 80;
const DEFAULT_CORRECTION_MODE: CorrectionMode = "sync";
const CODECS = ["pcm"] as const;
const CORRECTION_THRESHOLDS = {
  sync: {
    deadbandBelowMs: 2,
    rate1AboveMs: 12,
    rate2AboveMs: 38,
    samplesBelowMs: 8,
    resyncAboveMs: 220,
  },
  quality: {
    deadbandBelowMs: 2,
    samplesBelowMs: 24,
    resyncAboveMs: 55,
  },
};
const RECONNECT_CONFIG = {
  baseDelayMs: 1000,
  maxDelayMs: 15000,
  maxAttempts: Infinity,
};

function defaultBaseUrl(): string {
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  return `${protocol}//${window.location.hostname}:8927`;
}

function normalizeBaseUrl(input: string): string {
  const trimmed = input.trim() || defaultBaseUrl();
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed)
    ? trimmed
    : `${window.location.protocol === "https:" ? "https" : "http"}://${trimmed}`;
  const url = new URL(withScheme, window.location.href);

  if (url.protocol === "ws:") url.protocol = "http:";
  if (url.protocol === "wss:") url.protocol = "https:";
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error(`Unsupported protocol: ${url.protocol}`);
  }

  url.pathname = url.pathname.replace(/\/sendspin\/?$/i, "");
  if (url.pathname === "") url.pathname = "/";
  url.search = "";
  url.hash = "";
  return url.toString().replace(/\/$/, "");
}

function getOrCreatePlayerId(): string {
  const existing = window.localStorage.getItem(STORE_PLAYER_ID);
  if (existing) return existing;
  const id = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `local-voice-${Math.random().toString(16).slice(2)}`;
  window.localStorage.setItem(STORE_PLAYER_ID, id);
  return id;
}

function initialVolume(): number {
  const storedValue = window.localStorage.getItem(STORE_VOLUME);
  if (storedValue === null) return DEFAULT_VOLUME;

  const stored = Number(storedValue);
  return Number.isFinite(stored) && stored >= 0 && stored <= 100 ? stored : DEFAULT_VOLUME;
}

function initialMuted(): boolean {
  return window.localStorage.getItem(STORE_MUTED) === "true";
}

function initialCorrectionMode(): CorrectionMode {
  const value = window.localStorage.getItem(STORE_MODE);
  return value === "sync" || value === "quality" || value === "quality-local"
    ? value
    : DEFAULT_CORRECTION_MODE;
}

function formatNumber(value: number | null, suffix = ""): string {
  if (value === null || !Number.isFinite(value)) return "-";
  return `${value.toFixed(1)}${suffix}`;
}

function formatStream(format: StreamFormat | null): string {
  if (!format) return "-";
  const bits = format.bit_depth ? `${format.bit_depth}bit` : "audio";
  return `${format.codec} · ${format.sample_rate} Hz · ${format.channels}ch · ${bits}`;
}

function formatMetadata(serverState: ServerStatePayload): string | null {
  const metadata = serverState.metadata;
  if (!metadata) return null;
  const title = metadata.title?.trim();
  const artist = metadata.artist?.trim();
  if (title && artist) return `${title} - ${artist}`;
  return title || artist || null;
}

function bucket(value: number | null, size: number): number | null {
  if (value === null || !Number.isFinite(value)) return null;
  return Math.round(value / size) * size;
}

function App() {
  const [baseUrl, setBaseUrl] = useState(() => window.localStorage.getItem(STORE_SERVER_URL) || defaultBaseUrl());
  const [volume, setVolume] = useState(initialVolume);
  const [muted, setMuted] = useState(initialMuted);
  const [correctionMode, setCorrectionMode] = useState<CorrectionMode>(initialCorrectionMode);
  const [serverOpen, setServerOpen] = useState(true);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [state, setState] = useState<ConnectionState>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [snapshot, setSnapshot] = useState<PlayerSnapshot>({
    isPlaying: false,
    volume,
    muted,
    playerState: "synchronized",
    format: null,
    syncErrorMs: null,
    outputLatencyMs: null,
    correctionMethod: "none",
    playbackRate: null,
    timeSynced: false,
  });
  const playerRef = useRef<SendspinPlayer | null>(null);
  const logRef = useRef<HTMLElement | null>(null);
  const logIdRef = useRef(0);
  const lastPlayingRef = useRef(false);
  const detailLogRef = useRef<DetailLogState>({
    correctionMethod: "none",
    formatKey: null,
    groupPlayback: null,
    latencyBucket: null,
    syncBucket: null,
    timeSynced: false,
    trackLabel: null,
  });
  const playerId = useMemo(getOrCreatePlayerId, []);

  function addLog(message: string, kind: LogEntry["kind"] = "info") {
    setLogs((current) => [
      ...current,
      { id: ++logIdRef.current, kind, message },
    ].slice(-80));
  }

  function resetDetailLogs() {
    detailLogRef.current = {
      correctionMethod: "none",
      formatKey: null,
      groupPlayback: null,
      latencyBucket: null,
      syncBucket: null,
      timeSynced: false,
      trackLabel: null,
    };
  }

  function readSnapshot(player: SendspinPlayer): PlayerSnapshot {
    const syncInfo = player.syncInfo;
    return {
      isPlaying: player.isPlaying,
      volume: player.volume,
      muted: player.muted,
      playerState: player.playerState,
      groupState: player.playerState,
      format: player.currentFormat,
      syncErrorMs: syncInfo.syncErrorMs,
      outputLatencyMs: syncInfo.outputLatencyMs,
      correctionMethod: syncInfo.correctionMethod,
      playbackRate: syncInfo.playbackRate,
      timeSynced: player.timeSyncInfo.synced,
    };
  }

  function logPlaybackDetails(player: SendspinPlayer, nextSnapshot: PlayerSnapshot, nextState: PlayerEventState) {
    const detail = detailLogRef.current;
    const groupPlayback = nextState.groupState.playback_state || null;
    const trackLabel = formatMetadata(nextState.serverState);
    const formatKey = nextSnapshot.format ? formatStream(nextSnapshot.format) : null;
    const syncBucket = bucket(nextSnapshot.syncErrorMs, 5);
    const latencyBucket = bucket(nextSnapshot.outputLatencyMs, 10);

    if (groupPlayback && groupPlayback !== detail.groupPlayback) {
      addLog(`Group playback: ${groupPlayback}`, groupPlayback === "playing" ? "play" : "info");
      detail.groupPlayback = groupPlayback;
    }

    if (trackLabel && trackLabel !== detail.trackLabel) {
      addLog(`Now playing: ${trackLabel}`, "play");
      detail.trackLabel = trackLabel;
    }

    if (formatKey && formatKey !== detail.formatKey) {
      addLog(`Stream format: ${formatKey}`);
      detail.formatKey = formatKey;
    }

    if (nextSnapshot.timeSynced !== detail.timeSynced) {
      detail.timeSynced = nextSnapshot.timeSynced;
      if (nextSnapshot.timeSynced) {
        const timeSync = player.timeSyncInfo;
        addLog(`Clock synced: offset ${timeSync.offset} ms, error ±${timeSync.error} ms`);
      } else {
        addLog("Clock sync lost", "warn");
      }
    }

    if (nextSnapshot.isPlaying && nextSnapshot.correctionMethod !== detail.correctionMethod) {
      detail.correctionMethod = nextSnapshot.correctionMethod;
      addLog(
        `Correction: ${nextSnapshot.correctionMethod} · error ${formatNumber(nextSnapshot.syncErrorMs, " ms")}`,
        nextSnapshot.correctionMethod === "resync" ? "warn" : "info",
      );
    }

    if (nextSnapshot.isPlaying && syncBucket !== null && syncBucket !== detail.syncBucket) {
      detail.syncBucket = syncBucket;
      if (Math.abs(syncBucket) >= 5) addLog(`Sync error: ${formatNumber(nextSnapshot.syncErrorMs, " ms")}`);
    }

    if (nextSnapshot.isPlaying && latencyBucket !== null && latencyBucket !== detail.latencyBucket) {
      detail.latencyBucket = latencyBucket;
      addLog(`Output latency: ${formatNumber(nextSnapshot.outputLatencyMs, " ms")}`);
    }
  }

  async function connect() {
    if (playerRef.current) return;

    let normalizedUrl: string;
    try {
      normalizedUrl = normalizeBaseUrl(baseUrl);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Invalid server URL";
      setError(message);
      setState("error");
      addLog(message, "error");
      return;
    }

    setBaseUrl(normalizedUrl);
    window.localStorage.setItem(STORE_SERVER_URL, normalizedUrl);
    setState("connecting");
    setError(null);
    resetDetailLogs();
    addLog(`Connecting to ${normalizedUrl}`);

    const player = new SendspinPlayer({
      baseUrl: normalizedUrl,
      playerId,
      clientName: "Local Voice Browser Player",
      codecs: [...CODECS],
      correctionMode,
      correctionThresholds: CORRECTION_THRESHOLDS,
      reconnect: {
        ...RECONNECT_CONFIG,
        onReconnecting: (attempt) => {
          setState("connecting");
          addLog(`Reconnecting (${attempt})`, "warn");
        },
        onReconnected: () => {
          setState("connected");
          addLog("Reconnected");
        },
        onExhausted: () => {
          setState("error");
          setError("Reconnect attempts exhausted");
          addLog("Reconnect attempts exhausted", "error");
        },
      },
      onStateChange: (nextState) => {
        const nextSnapshot = readSnapshot(player);
        setSnapshot(nextSnapshot);
        setState(nextState.isPlaying ? "playing" : "connected");
        logPlaybackDetails(player, nextSnapshot, nextState);
        if (nextState.isPlaying !== lastPlayingRef.current) {
          lastPlayingRef.current = nextState.isPlaying;
          addLog(
            nextState.isPlaying
              ? `Playback started${nextSnapshot.format ? ` · ${formatStream(nextSnapshot.format)}` : ""}`
              : "Playback finished",
            nextState.isPlaying ? "play" : "info",
          );
        }
      },
    });

    playerRef.current = player;
    player.setVolume(volume);
    player.setMuted(muted);
    try {
      await player.connect();
      setSnapshot(readSnapshot(player));
      setState(player.isPlaying ? "playing" : "connected");
      setServerOpen(false);
      addLog("Connected");
    } catch (err) {
      playerRef.current = null;
      const message = err instanceof Error ? err.message : "Connection failed";
      setError(message);
      setState("error");
      setServerOpen(true);
      addLog(message, "error");
    }
  }

  function disconnect() {
    const player = playerRef.current;
    playerRef.current = null;
    lastPlayingRef.current = false;
    resetDetailLogs();
    if (player) player.disconnect("user_request");
    setState("disconnected");
    setServerOpen(true);
    setSnapshot((current) => ({ ...current, isPlaying: false, format: null, timeSynced: false }));
    addLog("Disconnected", "warn");
  }

  function updateVolume(value: number) {
    setVolume(value);
    window.localStorage.setItem(STORE_VOLUME, String(value));
    playerRef.current?.setVolume(value);
  }

  function updateMuted(value: boolean) {
    setMuted(value);
    window.localStorage.setItem(STORE_MUTED, String(value));
    playerRef.current?.setMuted(value);
  }

  function updateCorrectionMode(value: CorrectionMode) {
    setCorrectionMode(value);
    window.localStorage.setItem(STORE_MODE, value);
    playerRef.current?.setCorrectionMode(value);
    addLog(`Correction mode: ${value}`);
  }

  useEffect(() => {
    const interval = window.setInterval(() => {
      const player = playerRef.current;
      if (player) setSnapshot(readSnapshot(player));
    }, 500);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => () => {
    playerRef.current?.disconnect("shutdown");
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  const connected = state === "connected" || state === "playing" || state === "connecting";

  const statusText = state === "playing"
    ? "Playing"
    : state === "connected"
      ? "Ready"
      : state === "connecting"
        ? "Connecting..."
        : state === "error"
          ? "Connection error"
          : "Disconnected";

  return (
    <main class="shell">
      <div class="backdrop" aria-hidden="true">
        <div />
        <div />
        <div />
      </div>
      <section class="panel">
        <header class="header">
          <div class="header-icon" aria-hidden="true">
            <Play fill="currentColor" strokeWidth={0} />
          </div>
          <div>
            <h1>Local Voice Player</h1>
            <p>RotorHazard</p>
          </div>
        </header>

        <section class="status-hero" aria-live="polite">
          <div class={`status-ring ${state}`}>
            <svg viewBox="0 0 72 72" aria-hidden="true">
              <circle class="ring-bg" cx="36" cy="36" r="30" />
              <circle class={`ring-arc ${state}`} cx="36" cy="36" r="30" />
            </svg>
            <div class="ring-dot">
              {state === "playing" ? (
                <div class="playing-bars" aria-hidden="true">
                  <span />
                  <span />
                  <span />
                  <span />
                  <span />
                </div>
              ) : (
                <span class={state} />
              )}
            </div>
          </div>
          <div class={`status-label ${state}`}>{statusText}</div>
        </section>

        <section class="details server-details">
          <button
            class={`details-toggle server-toggle ${serverOpen ? "open" : ""}`}
            type="button"
            aria-expanded={serverOpen}
            onClick={() => setServerOpen((open) => !open)}
          >
            <span>Server</span>
            <strong>{baseUrl}</strong>
            <ChevronRight aria-hidden="true" />
          </button>
          {serverOpen && (
            <label class="field server-field">
              <span>Server URL</span>
                <input
                  aria-label="Server URL"
                  value={baseUrl}
                  disabled={connected}
                  spellcheck={false}
                  onInput={(event) => setBaseUrl(event.currentTarget.value)}
                />
            </label>
          )}
        </section>

        <div class="controls">
          <div class="split-row">
            <label class="field volume-field">
              <span>Volume</span>
              <div class="volume-row">
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={volume}
                  onInput={(event) => updateVolume(Number(event.currentTarget.value))}
                />
                <output>{volume}%</output>
              </div>
            </label>
            <button
              class={`mute-button ${muted ? "active" : ""}`}
              type="button"
              aria-pressed={muted}
              onClick={() => updateMuted(!muted)}
            >
              {muted ? <VolumeX aria-hidden="true" /> : <Volume2 aria-hidden="true" />}
              <span>{muted ? "Muted" : "Mute"}</span>
            </button>
          </div>

          <label class="field">
            <span>Correction</span>
            <select
              value={correctionMode}
              onChange={(event) => updateCorrectionMode(event.currentTarget.value as CorrectionMode)}
            >
              <option value="sync">Sync</option>
              <option value="quality">Quality</option>
              <option value="quality-local">Quality local</option>
            </select>
          </label>

          <button class={connected ? "danger" : "primary"} type="button" onClick={connected ? disconnect : connect}>
            {connected ? "Disconnect" : "Connect"}
          </button>
        </div>

        {error && <p class="error-text">{error}</p>}

        <section class="details">
          <button
            class={`details-toggle ${diagnosticsOpen ? "open" : ""}`}
            type="button"
            aria-expanded={diagnosticsOpen}
            onClick={() => setDiagnosticsOpen((open) => !open)}
          >
            <span>Diagnostics</span>
            <ChevronRight aria-hidden="true" />
          </button>
          {diagnosticsOpen && (
            <div class="diagnostics" aria-label="Diagnostics">
              <Metric label="Format" value={formatStream(snapshot.format)} />
              <Metric label="Time sync" value={snapshot.timeSynced ? "yes" : "no"} />
              <Metric label="Sync error" value={formatNumber(snapshot.syncErrorMs, " ms")} />
              <Metric label="Output latency" value={formatNumber(snapshot.outputLatencyMs, " ms")} />
              <Metric label="Correction" value={snapshot.correctionMethod} />
              <Metric label="Rate" value={snapshot.playbackRate === null ? "-" : snapshot.playbackRate.toFixed(3)} />
            </div>
          )}
        </section>

        <section ref={logRef} class="log" aria-label="Activity log">
          {logs.length === 0 ? <p class="empty-log">No activity yet</p> : logs.map((entry) => (
            <p key={entry.id} class={entry.kind}>{entry.message}</p>
          ))}
        </section>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div class="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

const root = document.getElementById("app");
if (root) render(<App />, root);
