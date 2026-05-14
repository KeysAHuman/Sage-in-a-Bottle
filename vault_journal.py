"""
vault_journal.py  — Append-only human-readable journal.
vault_heartbeat.py — status.json writer for the observer.

Both live here since they're simple and related.
"""

import json
from pathlib import Path
from datetime import datetime


# ── Journal ───────────────────────────────────────────────────────────────────

class Journal:
    def __init__(self, config):
        data_dir = Path(config["memory"]["data_dir"])
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "journal.txt"
        self.cot_path = data_dir / "cot.txt"
        self._last_timestamp: str = ""

    def append(
        self,
        thought: str,
        mode: str,
        topics: list,
        mood: str,
        cycle: int,
    ):
        ts = datetime.now()
        self._last_timestamp = ts.isoformat()

        topics_str = ", ".join(topics[:4]) if topics else "—"
        header = (
            f"[{ts.strftime('%Y-%m-%d %H:%M')}  "
            f"cycle {cycle}  |  {mode}  |  {topics_str}  |  {mood}]"
        )
        divider = "─" * 64

        entry = f"\n{header}\n{thought}\n{divider}\n"

        with open(self.path, "a", encoding="utf-8") as f:
            f.write(entry)

    def append_cot(
        self,
        chain_of_thought: str,
        mode: str,
        topics: list,
        mood: str,
        cycle: int,
    ):
        """
        Write SAGE's chain-of-thought (<think> blocks) to a separate
        cot.txt file.  Mirrors the journal entry format for easy
        cross-referencing, but only written when CoT is present.
        """
        if not chain_of_thought:
            return

        ts = datetime.now()
        topics_str = ", ".join(topics[:4]) if topics else "—"
        header = (
            f"[{ts.strftime('%Y-%m-%d %H:%M')}  "
            f"cycle {cycle}  |  {mode}  |  {topics_str}  |  {mood}]"
        )
        divider = "─" * 64

        entry = f"\n{header}\n{chain_of_thought}\n{divider}\n"

        with open(self.cot_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def last_timestamp(self) -> str:
        return self._last_timestamp


# ── Heartbeat ─────────────────────────────────────────────────────────────────

class Heartbeat:
    def __init__(self, config):
        self.path = Path(config["memory"]["data_dir"]) / "status.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._vault_name = config.get("vault_name", "The Vault")

    def write(self, **kwargs):
        """
        Write status.json. Keys used by the observer:
          status, mode, cycle, topics, mood, memory_size,
          last_thought_at, next_sleep_sec
        """
        data = {
            "vault_name":     self._vault_name,
            "status":         kwargs.get("status", "running"),
            "mode":           kwargs.get("mode", "—"),
            "cycle":          kwargs.get("cycle", 0),
            "topics":         kwargs.get("topics", []),
            "mood":           kwargs.get("mood", ""),
            "memory_size":    kwargs.get("memory_size", 0),
            "last_thought_at": kwargs.get("last_thought_at", ""),
            "next_sleep_sec": kwargs.get("next_sleep_sec", 0),
            "updated_at":     datetime.now().isoformat(),
        }
        # Write atomically via temp file to avoid observer reading a half-write
        tmp = Path(str(self.path) + ".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.replace(self.path)
