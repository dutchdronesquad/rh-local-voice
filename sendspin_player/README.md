# Sendspin Browser Player

This is the React/shadcn browser player for Local Voice. It connects to a
Sendspin server with `@sendspin/sendspin-js` and is served at `/player` by the
RotorHazard plugin or the standalone Sendspin service container.

The source app lives in this directory, but production assets are written to:

```text
../custom_plugins/local_voice/player/
```

That output path is intentional. The plugin ZIP and Docker image both serve the
built files from `custom_plugins/local_voice/player/` while keeping the editable
frontend source in `sendspin_player/`.

## Development

Install dependencies:

```bash
npm install
```

Start the Vite dev server:

```bash
npm run dev
```

Run checks:

```bash
npm run lint
npm run build
```

`npm run build` runs the TypeScript build and writes the production player files
to `custom_plugins/local_voice/player/`.

## Runtime Notes

- The app is a single page served under `/player`.
- Vite's `base` is `/player/` so assets resolve correctly from the plugin and
  container routes.
- Sendspin connection, buffering, sync correction, and reconnect behavior are
  owned by `@sendspin/sendspin-js`; this app only presents the player UI and
  user controls.
