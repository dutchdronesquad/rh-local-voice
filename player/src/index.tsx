import { SendspinPlayer } from "@sendspin/sendspin-js";
import type { CorrectionMode, GroupUpdatePayload, ServerStatePayload, StreamFormat } from "@sendspin/sendspin-js";
import { ChevronRight, Play, Share2, Volume2, VolumeX, X } from "lucide-preact";
import { render } from "preact";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { qrMatrix } from "./qr";
import "./style.css";

type ConnectionState = "disconnected" | "connecting" | "connected" | "playing" | "reconnecting" | "error";

type PlayerSnapshot = {
  isConnected: boolean;
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
const SHARE_ANIMATION_MS = 180;

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

function playerPageUrl(): string {
  const url = new URL(window.location.href);
  url.search = "";
  url.hash = "";
  url.pathname = url.pathname.replace(/\/player(?:\/.*)?$/i, "/player");
  return url.toString();
}

function App() {
  const [baseUrl, setBaseUrl] = useState(() => window.localStorage.getItem(STORE_SERVER_URL) || defaultBaseUrl());
  const [volume, setVolume] = useState(initialVolume);
  const [muted, setMuted] = useState(initialMuted);
  const [correctionMode, setCorrectionMode] = useState<CorrectionMode>(initialCorrectionMode);
  const [serverOpen, setServerOpen] = useState(true);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareClosing, setShareClosing] = useState(false);
  const [state, setState] = useState<ConnectionState>("disconnected");
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [snapshot, setSnapshot] = useState<PlayerSnapshot>({
    isConnected: false,
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
  const hasConnectedRef = useRef(false);
  const lastPlayingRef = useRef(false);
  const shareCloseTimerRef = useRef<number | null>(null);
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
  const shareUrl = useMemo(playerPageUrl, []);

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

  function openShare() {
    if (shareCloseTimerRef.current !== null) {
      window.clearTimeout(shareCloseTimerRef.current);
      shareCloseTimerRef.current = null;
    }
    setShareClosing(false);
    setShareOpen(true);
  }

  function closeShare() {
    setShareClosing(true);
    if (shareCloseTimerRef.current !== null) window.clearTimeout(shareCloseTimerRef.current);
    shareCloseTimerRef.current = window.setTimeout(() => {
      setShareOpen(false);
      setShareClosing(false);
      shareCloseTimerRef.current = null;
    }, SHARE_ANIMATION_MS);
  }

  function readSnapshot(player: SendspinPlayer): PlayerSnapshot {
    const syncInfo = player.syncInfo;
    return {
      isConnected: player.isConnected,
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

  function stateFromSnapshot(nextSnapshot: PlayerSnapshot): ConnectionState {
    if (!nextSnapshot.isConnected) {
      return hasConnectedRef.current ? "reconnecting" : "connecting";
    }
    return nextSnapshot.isPlaying ? "playing" : "connected";
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
    hasConnectedRef.current = false;
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
          setState("reconnecting");
          addLog(`Reconnecting (${attempt})`, "warn");
        },
        onReconnected: () => {
          hasConnectedRef.current = true;
          resetDetailLogs();
          const nextSnapshot = readSnapshot(player);
          setSnapshot(nextSnapshot);
          setState(stateFromSnapshot(nextSnapshot));
          addLog("Reconnected");
        },
        onExhausted: () => {
          setState("error");
          setError("Reconnect attempts exhausted");
          addLog("Reconnect attempts exhausted", "error");
        },
      },
      onStateChange: (nextState) => {
        if (playerRef.current !== player) return;
        const nextSnapshot = readSnapshot(player);
        setSnapshot(nextSnapshot);
        setState(stateFromSnapshot(nextSnapshot));
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
      hasConnectedRef.current = true;
      const nextSnapshot = readSnapshot(player);
      setSnapshot(nextSnapshot);
      setState(stateFromSnapshot(nextSnapshot));
      setServerOpen(false);
      addLog("Connected");
    } catch (err) {
      player.disconnect("shutdown");
      playerRef.current = null;
      hasConnectedRef.current = false;
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
    hasConnectedRef.current = false;
    lastPlayingRef.current = false;
    resetDetailLogs();
    if (player) player.disconnect("user_request");
    setState("disconnected");
    setServerOpen(true);
    setSnapshot((current) => ({ ...current, isConnected: false, isPlaying: false, format: null, timeSynced: false }));
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
      if (player) {
        const nextSnapshot = readSnapshot(player);
        setSnapshot(nextSnapshot);
        if (!nextSnapshot.isConnected) {
          setState(stateFromSnapshot(nextSnapshot));
        }
      }
    }, 500);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => () => {
    playerRef.current?.disconnect("shutdown");
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => () => {
    if (shareCloseTimerRef.current !== null) window.clearTimeout(shareCloseTimerRef.current);
  }, []);

  const connected = state === "connected" || state === "playing" || state === "connecting" || state === "reconnecting";

  const statusText = state === "playing"
    ? "Playing"
    : state === "connected"
      ? "Ready"
      : state === "reconnecting"
        ? "Reconnecting..."
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
          <div class="header-text">
            <h1>Sendspin Player</h1>
            <p>Live audio</p>
          </div>
          <div class="header-actions">
            <button
              class="icon-button"
              type="button"
              aria-label="Share browser player"
              title="Share browser player"
              onClick={openShare}
            >
              <Share2 aria-hidden="true" />
            </button>
            <button
              class={`connection-button header-connection ${connected ? "connected" : ""}`}
              type="button"
              onClick={connected ? disconnect : connect}
            >
              {connected ? "Disconnect" : "Connect"}
            </button>
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

        <footer class="player-credit">
          Playback powered by{" "}
          <a href="https://www.sendspin-audio.com/" target="_blank" rel="noopener noreferrer">
            Sendspin
          </a>
        </footer>
      </section>

      {shareOpen && (
        <div class={`share-backdrop ${shareClosing ? "closing" : ""}`} role="presentation" onClick={closeShare}>
          <section
            class="share-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="share-title"
            onClick={(event) => event.stopPropagation()}
          >
            <header class="share-header">
              <h2 id="share-title">Share browser player</h2>
              <button class="icon-button" type="button" aria-label="Close share dialog" onClick={closeShare}>
                <X aria-hidden="true" />
              </button>
            </header>
            <p class="share-copy">
              Scan this code on another device to open this Sendspin player and join the same audio session there.
            </p>
            <QrCodeSvg text={shareUrl} />
            <p class="share-url">{shareUrl}</p>
          </section>
        </div>
      )}
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

function QrCodeSvg({ text }: { text: string }) {
  try {
    const matrix = qrMatrix(text);
    const size = matrix.length;
    const padding = 4;
    return (
      <svg
        class="qr-code"
        viewBox={`0 0 ${size + padding * 2} ${size + padding * 2}`}
        role="img"
        aria-label="QR code for this player"
      >
        <rect width={size + padding * 2} height={size + padding * 2} fill="white" />
        {matrix.map((row, y) => row.map((filled, x) => filled && (
          <rect key={`${x}-${y}`} x={x + padding} y={y + padding} width="1" height="1" fill="black" />
        )))}
      </svg>
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : "Cannot render QR code";
    return <p class="qr-error">{message}</p>;
  }
}

const root = document.getElementById("app");
if (root) render(<App />, root);
