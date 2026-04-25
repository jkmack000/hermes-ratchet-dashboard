"""
Telemetry parser for Hermes Agent session data.
Reads ~/.hermes/sessions/*.jsonl and extracts metrics.
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SESSIONS_DIR = Path.home() / ".hermes" / "sessions"
LOGS_DIR = Path.home() / ".hermes" / "logs"


def parse_iso(ts: str) -> Optional[datetime]:
    try:
        ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def load_sessions(limit: int = 50) -> list[dict]:
    """Load recent session files and compute per-session stats."""
    if not SESSIONS_DIR.exists():
        return []

    files = sorted(SESSIONS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    sessions = []

    for fpath in files[:limit]:
        try:
            lines = fpath.read_text().strip().splitlines()
        except Exception:
            continue

        msgs = []
        for line in lines:
            try:
                msgs.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        if not msgs:
            continue

        # Extract metadata from first message if it's session_meta
        meta = msgs[0] if msgs[0].get("role") == "session_meta" else {}
        model = meta.get("model", "unknown")
        platform = meta.get("platform", "cli")

        # Collect timestamps
        timestamps = []
        tool_calls = 0
        tool_names = defaultdict(int)
        errors = 0
        user_msgs = 0
        assistant_msgs = 0
        total_chars = 0

        for msg in msgs:
            ts = msg.get("timestamp")
            if ts:
                dt = parse_iso(ts)
                if dt:
                    timestamps.append(dt)

            role = msg.get("role")
            if role == "user":
                user_msgs += 1
                total_chars += len(msg.get("content", ""))
            elif role == "assistant":
                assistant_msgs += 1
                total_chars += len(msg.get("content", ""))
                # Count tool calls
                calls = msg.get("tool_calls", [])
                tool_calls += len(calls)
                for call in calls:
                    fn = call.get("function", {})
                    name = fn.get("name", "unknown")
                    tool_names[name] += 1

            elif role == "tool":
                content = msg.get("content", "")
                if isinstance(content, str) and ("error" in content.lower() or "failed" in content.lower() or "traceback" in content.lower()):
                    errors += 1

        if not timestamps:
            continue

        start = min(timestamps)
        end = max(timestamps)
        duration_sec = (end - start).total_seconds() if start and end else 0

        # Rough token estimate: ~4 chars per token
        est_tokens = total_chars // 4

        sessions.append({
            "id": fpath.stem,
            "model": model,
            "platform": platform,
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "duration_sec": round(duration_sec, 1),
            "messages": len(msgs),
            "user_msgs": user_msgs,
            "assistant_msgs": assistant_msgs,
            "tool_calls": tool_calls,
            "tools": dict(tool_names),
            "errors": errors,
            "est_tokens": est_tokens,
            "size_bytes": fpath.stat().st_size,
        })

    return sessions


def get_aggregate_metrics(sessions: list[dict]) -> dict:
    """Compute aggregate metrics across all loaded sessions."""
    if not sessions:
        return {
            "total_sessions": 0,
            "total_messages": 0,
            "total_tool_calls": 0,
            "total_est_tokens": 0,
            "total_errors": 0,
            "avg_duration": 0,
            "model_breakdown": {},
            "platform_breakdown": {},
            "tool_breakdown": {},
            "active_last_hour": 0,
            "active_last_day": 0,
        }

    total_msgs = sum(s["messages"] for s in sessions)
    total_tools = sum(s["tool_calls"] for s in sessions)
    total_tokens = sum(s["est_tokens"] for s in sessions)
    total_errors = sum(s["errors"] for s in sessions)
    avg_dur = sum(s["duration_sec"] for s in sessions) / len(sessions)

    model_breakdown = defaultdict(int)
    platform_breakdown = defaultdict(int)
    tool_breakdown = defaultdict(int)

    now = datetime.now(timezone.utc)
    active_hour = 0
    active_day = 0

    for s in sessions:
        model_breakdown[s["model"]] += 1
        platform_breakdown[s["platform"]] += 1
        for tool, count in s["tools"].items():
            tool_breakdown[tool] += count

        end = parse_iso(s["end"]) if s["end"] else None
        if end:
            age_hours = (now - end).total_seconds() / 3600
            if age_hours < 1:
                active_hour += 1
            if age_hours < 24:
                active_day += 1

    return {
        "total_sessions": len(sessions),
        "total_messages": total_msgs,
        "total_tool_calls": total_tools,
        "total_est_tokens": total_tokens,
        "total_errors": total_errors,
        "avg_duration": round(avg_dur, 1),
        "model_breakdown": dict(model_breakdown),
        "platform_breakdown": dict(platform_breakdown),
        "tool_breakdown": dict(tool_breakdown),
        "active_last_hour": active_hour,
        "active_last_day": active_day,
    }


def get_hourly_activity(sessions: list[dict], hours: int = 24) -> list[dict]:
    """Return message count per hour for sparkline."""
    buckets = defaultdict(int)
    now = datetime.now(timezone.utc)

    for s in sessions:
        start = parse_iso(s["start"]) if s["start"] else None
        if not start:
            continue
        age_hours = (now - start).total_seconds() / 3600
        if age_hours < hours:
            hour_key = start.strftime("%Y-%m-%d %H:00")
            buckets[hour_key] += s["messages"]

    # Fill gaps
    result = []
    for i in range(hours):
        t = now - __import__("datetime").timedelta(hours=i)
        key = t.strftime("%Y-%m-%d %H:00")
        result.append({"hour": key, "messages": buckets.get(key, 0)})
    result.reverse()
    return result
