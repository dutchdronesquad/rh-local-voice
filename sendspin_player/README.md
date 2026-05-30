# Sendspin Browser Player

This is the React/shadcn browser player for Race Voice. It connects to a
Sendspin server with `@sendspin/sendspin-js`. The standalone Sendspin service
serves it at `/`; the RotorHazard plugin serves its plugin build at `/player`.

The source app lives in this directory, but production assets are written to:

```text
../custom_plugins/race_voice/player/
```

That output path is intentional. The plugin ZIP and Docker image both copy or
serve the built files from `custom_plugins/race_voice/player/` while keeping
the editable frontend source in `sendspin_player/`.

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
npm run build:plugin
```

`npm run build` builds for root hosting (`/`), which is the standalone
Docker service default. `npm run build:plugin` builds for RotorHazard's
`/player/` route. Both commands run the TypeScript build and write the
production player files to `custom_plugins/race_voice/player/`.

## Runtime Notes

- The app is a single page. Standalone service deployments serve it at `/`;
  RotorHazard plugin deployments serve it at `/player`.
- Vite's `base` defaults to `/`. Use `VITE_PLAYER_BASE=/player/` for the
  RotorHazard plugin build.
- Sendspin connection, buffering, sync correction, and reconnect behavior are
  owned by `@sendspin/sendspin-js`; this app only presents the player UI and
  user controls.
- The Server URL control can connect this player to another Sendspin server,
  including the public `https://sendspin-demo.openhomefoundation.org` demo.

## Credits

This player UI is a Race Voice wrapper around Sendspin. Sendspin and the
browser SDK are Open Home Foundation projects; see
[sendspin-audio.com](https://www.sendspin-audio.com/) and
[openhomefoundation.org](https://www.openhomefoundation.org/).
