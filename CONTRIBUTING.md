# Contributing

Thank you for your interest in contributing to Local Voice!

## Requirements

You need the following tools to get started:

- [uv] — Python virtual environment and package manager
- [Python] 3.12 or higher
- [Node.js] 20 or higher (for the browser player)

## Setup

1. Clone the repository.
2. Install Python dependencies:

```bash
uv sync --all-groups
```

3. Install browser player dependencies:

```bash
cd player && npm install
```

## Pre-commit checks

This repository uses the [prek] framework. All changes are linted and tested on each commit.

Install the pre-commit hook:

```bash
uv run prek install
```

Run all checks manually:

```bash
uv run prek run --all-files
```

Run checks on staged files only:

```bash
uv run prek run
```

## Browser Player

The Sendspin browser player source lives in `player/` and is built with Vite + Preact.

```bash
cd player
npm run dev      # local dev server
npm run check    # type-check
npm run lint     # lint
npm run build    # production build → custom_plugins/local_voice/player/
```

`npm run build` writes the production build to `custom_plugins/local_voice/player/`. The `assets/` subdirectory is not committed to git and must be built locally before deploying.

> **Browser compatibility note**: During local testing, Safari on macOS gave the smoothest playback experience. Chrome on macOS occasionally showed small playback interruptions and more sync-error movement, particularly with browser extensions active. When testing sync quality in Chrome, use an incognito window with extensions disabled before treating jitter as a server-side issue.

<!-- LINKS -->
[uv]: https://docs.astral.sh/uv/
[Python]: https://www.python.org/
[Node.js]: https://nodejs.org/
[prek]: https://prek.j178.dev/
