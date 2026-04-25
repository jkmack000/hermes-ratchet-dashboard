# Ratchet Mode — Live Training Dashboard

> A Hermes Agent dashboard plugin for the Nous Research 24-hour hackathon.

## What is this?

Ratchet Mode visualizes iterative auto-optimization experiments in real time.

Inspired by Karpathy's "ratchet loop" and our own `bwrap` sandbox orchestrator, this plugin turns a Git repository full of experiments into a live telemetry stream. Every commit is an experiment. Every score change is a data point. The dashboard shows you the optimization landscape as it unfolds.

## The Metaphor

A ratchet only moves forward. In this dashboard:

- **Green** = score improved (ratchet clicked up)
- **Red** = score regressed (change was reverted)
- **Cyan line** = the optimization trajectory over time

The system watches your workspace Git repo, parses scores from commit messages or `score.txt`, and streams updates to the frontend via SSE.

## Features

| Feature | Description |
|---------|-------------|
| **Live SSE Stream** | Real-time updates as new commits land |
| **Score Waterfall** | Canvas-rendered trajectory with glow effects |
| **Experiment History** | Scrollable list with delta indicators |
| **Git Graph Timeline** | Visual `git log --graph` in terminal style |
| **Agent Telemetry** | Live session metrics: tokens, tools, models, latency |
| **Self-Healing Loop** | Test harness + Claude Code auto-fixes dashboard bugs |
| **Retro CRT UI** | Scanlines, cyan glow, monospace — terminal aesthetic |

## Two Modes

### Ratchet Mode
Monitors an auto-optimization Git repo. Every commit is an experiment. Shows score trajectory, experiment lineage, and live progress.

### Agent Telemetry Mode
Monitors the Hermes Agent itself by parsing `~/.hermes/sessions/*.jsonl`. Shows:
- **KPIs**: Sessions (24h), estimated tokens, tool calls, errors
- **Model Breakdown**: Which models are being used
- **Tool Usage**: Frequency chart of tool calls
- **Recent Sessions**: Duration, messages, tools per session
- **Activity Sparkline**: Messages per hour over 24h
- **Platform & Tool Breakdowns**

## Architecture

```
┌─────────────────┐      SSE       ┌──────────────────┐
│   dashboard     │ ◄────────────  │  backend/ratchet │
│  (vanilla JS)   │                │   (FastAPI)      │
└─────────────────┘                └────────┬─────────┘
                                            │
                              ┌─────────────┬─────────────┐
                              │  git watcher  │  session parser │
                              │ ~/auto-research│ ~/.hermes/sessions│
                              │  (Git repo)    │  (JSONL files)   │
                              └─────────────┴─────────────┘
```

## Quick Start

### Standalone (dev mode)

```bash
# Install deps
uv sync

# Start the backend
uv run python backend/ratchet.py

# Open dashboard
curl http://localhost:8765/api/plugins/ratchet/
```

### As a Hermes Plugin

Copy this directory into your Hermes Agent dashboard plugins path:

```bash
cp -r hermes-ratchet-dashboard/ ~/.hermes/dashboard/plugins/
```

The plugin mounts at `/api/plugins/ratchet/` and serves the dashboard HTML at the root.

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `RATCHET_WORKSPACE` | `~/auto-research` | Git repo to watch |
| `RATCHET_POLL_INTERVAL` | `2` | Git poll interval (seconds) |

## Score Detection

The backend tries these sources in order:

1. Git commit message patterns: `score:1.234`, `best=3.14`, `loss:0.5`
2. `score.txt` or `best_score.txt` in the workspace root
3. `experiments.json` (reads `best_score` or last entry)

## Self-Healing Ratchet Loop

This plugin dogfoods itself. `ratchet_loop.py` runs `ratchet_test.py` against the dashboard. If the test score > 0 (validation errors), it invokes Claude Code to fix the code, re-tests, and commits only if the score improves.

```bash
python ratchet_loop.py
```

Max 5 fix attempts with exponential backoff. No runaway loops.

## Structure

```
.
├── backend/
│   ├── __init__.py          # Package marker
│   ├── ratchet.py           # FastAPI router + git watcher
│   └── telemetry.py         # Hermes session parser
├── dashboard.html          # Retro CRT frontend with tab switcher
├── ratchet_test.py         # 7-point validation harness
├── ratchet_loop.py         # Autonomous fix/commit loop
├── plugin.yaml             # Hermes plugin manifest
└── pyproject.toml          # Python deps
```

## Demo

With `~/auto-research` running experiments, the dashboard shows:

- Best score: **3.374** (big cyan number)
- 16 experiments tracked
- Waterfall chart showing improvement trajectory
- Live git log stream
- Status: `RUNNING █` (blinking cursor)

## License

MIT — built in 24 hours for the Nous Research hackathon.
