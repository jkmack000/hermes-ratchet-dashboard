# Hermes Ratchet Dashboard Plugin

A Hermes Agent dashboard plugin for the Nous Research 24-hour hackathon.

## Priority: Option 3 - Ratchet Mode Live Training Dashboard

### Goal
Provide real-time visualization of iterative auto-optimization experiments, inspired by Karpathy's ratchet loop and our own `bwrap` sandbox orchestrator.

### Architecture
- **Backend Plugin**: FastAPI router mounted under `/api/plugins/ratchet/` that watches a target Git repository and exposes experiment telemetry.
- **Frontend Plugin**: Retro-terminal styled dashboard showing live experiment progress, score waterfalls, and ratchet history.
- **Data Source**: External git repository (typically an auto-research project) containing:
  - `experiments.json` or `score.txt` files
  - Git commit history as the source of truth for experiment lineage
  - `program.md` for objective context

### Stretch: Option 1 - Agent Telemetry Dashboard
Once Option 3 is stable, extend the backend to accept Hermes session telemetry for live resource monitoring.

### Future: Option 2 - Multi-Agent Network Visualizer
If time permits, add a swarm topology view for `BwrapSandbox` IPC message passing.

## Structure
- `plugin.yaml` — Plugin manifest
- `backend/` — FastAPI router + file watchers
- `frontend/` — Vanilla JS + Canvas 2D dashboard (zero build step for speed)

## Install
Copy this directory into your Hermes Agent dashboard plugins path (or mount as a backend plugin).
