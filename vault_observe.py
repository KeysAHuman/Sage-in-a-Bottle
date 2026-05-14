"""
vault_observe.py — The Observer.

Watches the vault from a distance. Reads only status.json — never the journal,
never the vector DB. You see presence and posture, not thought content.

Run in a separate terminal:
  python vault_observe.py

Press Ctrl+C to stop observing (the vault keeps running).
"""

import json
import os
import sys
import time
import yaml
from datetime import datetime
from pathlib import Path


# ── Labels & symbols ─────────────────────────────────────────────────────────

MODE_LABELS = {
    "free_associate":       "free association",
    "retrieve_and_reflect": "returning to an old thought",
    "synthesize":           "finding a relationship",
    "read_text":            "reading",
    "write_aphorism":       "distilling",
    "gathering":            "gathering…",
    "thinking":             "in thought",
    "starting":             "waking up",
    "—":                    "—",
}

STATUS_SYMBOLS = {
    "thinking":  "◉",
    "resting":   "○",
    "gathering": "◎",
    "starting":  "◌",
    "offline":   "·",
}

STATUS_LABELS = {
    "thinking":  "thinking",
    "resting":   "resting",
    "gathering": "gathering",
    "starting":  "starting up",
    "offline":   "offline",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        with open("config.yaml") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return {"observer": {"status_file": "./data/status.json", "refresh_sec": 10}}


def time_ago(ts_str: str) -> str:
    if not ts_str:
        return "—"
    try:
        ts   = datetime.fromisoformat(ts_str)
        diff = (datetime.now() - ts).total_seconds()
        if diff < 60:
            return f"{int(diff)}s ago"
        elif diff < 3600:
            return f"{int(diff / 60)}m ago"
        else:
            h = int(diff / 3600)
            m = int((diff % 3600) / 60)
            return f"{h}h {m}m ago"
    except Exception:
        return "—"


def fmt_sleep(sec: int) -> str:
    if sec <= 0:
        return "—"
    m = sec // 60
    s = sec % 60
    return f"{m}m {s}s" if m else f"{s}s"


def pad(s: str, width: int) -> str:
    """Truncate to width and left-pad with spaces to fill."""
    s = str(s)
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s.ljust(width)


# ── Renderer ──────────────────────────────────────────────────────────────────

def render(data: dict):
    os.system("clear" if os.name == "posix" else "cls")

    name       = data.get("vault_name", "The Vault")
    status     = data.get("status", "offline")
    mode       = data.get("mode", "—")
    cycle      = data.get("cycle", 0)
    topics     = data.get("topics", [])
    mood       = data.get("mood", "")
    mem_size   = data.get("memory_size", 0)
    last_ts    = data.get("last_thought_at", "")
    next_sleep = data.get("next_sleep_sec", 0)

    sym         = STATUS_SYMBOLS.get(status, "·")
    status_lbl  = STATUS_LABELS.get(status, status)
    mode_lbl    = MODE_LABELS.get(mode, mode)
    topics_str  = "  ·  ".join(topics[:4]) if topics else "—"
    W = 50   # inner content width
    B = W + 2

    def row(label: str, value: str) -> str:
        label_col = f"{label:<14}"
        value_col = pad(value, W - 14)
        return f"  │  {label_col}{value_col}  │"

    border  = "─" * B
    title   = pad(f"  {sym}  {name}", B)

    # Rest countdown if resting
    if status == "resting" and next_sleep > 0:
        status_display = f"{status_lbl}  ({fmt_sleep(next_sleep)} remaining)"
    else:
        status_display = status_lbl

    print()
    print(f"  ┌{border}┐")
    print(f"  │{title}│")
    print(f"  ├{border}┤")
    print(row("state",       status_display))
    print(row("doing",       mode_lbl))
    print(row("mood",        mood or "—"))
    print(row("themes",      topics_str))
    print(f"  ├{border}┤")
    print(row("thoughts",    str(mem_size)))
    print(row("cycle",       str(cycle)))
    print(row("last thought", time_ago(last_ts)))
    print(f"  └{border}┘")
    print()
    print(f"    observed {datetime.now().strftime('%H:%M:%S')}  ·  ctrl+c to stop")
    print()


def render_offline(status_file: Path):
    os.system("clear" if os.name == "posix" else "cls")
    print()
    print("  ·  vault offline")
    print(f"     waiting for: {status_file}")
    print()
    print(f"     {datetime.now().strftime('%H:%M:%S')}  ·  ctrl+c to stop")
    print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    config      = load_config()
    obs_cfg     = config.get("observer", {})
    status_file = Path(obs_cfg.get("status_file", "./data/status.json"))
    refresh_sec = int(obs_cfg.get("refresh_sec", 10))

    print("\n  The Vault — Observer connecting…")
    time.sleep(0.8)

    while True:
        try:
            if status_file.exists():
                try:
                    with open(status_file) as f:
                        data = json.load(f)
                    render(data)
                except (json.JSONDecodeError, KeyError):
                    # File mid-write — skip this tick
                    pass
            else:
                render_offline(status_file)

        except KeyboardInterrupt:
            print("\n  Observer closed. The vault continues.\n")
            sys.exit(0)

        time.sleep(refresh_sec)


if __name__ == "__main__":
    main()
