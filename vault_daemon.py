"""
vault_daemon.py — The Vault's contemplation loop.

Run with:  python vault_daemon.py
Stop with: Ctrl+C  (it completes the current thought first)

The daemon:
  1. Wakes up
  2. Selects a contemplation mode
  3. Gathers context from memory
  4. Generates a thought via Ollama
  5. Stores the thought + metadata
  6. Appends to the journal
  7. Updates the heartbeat
  8. Sleeps a variable duration
  9. Repeat
"""

import time
import signal
import logging
import sys
import yaml
import requests
from pathlib import Path

from vault_memory  import Memory
from vault_modes   import select_mode, build_prompt, parse_output, sleep_duration
from vault_journal import Journal, Heartbeat


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vault")


# ── Config ────────────────────────────────────────────────────────────────────

def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Ollama call ───────────────────────────────────────────────────────────────

def generate(config: dict, prompt: str) -> str:
    """
    Call the Ollama /api/generate endpoint.
    Timeout is generous — CPU inference on a 7B+ model can take several minutes.
    """
    resp = requests.post(
        f"{config['ollama']['host']}/api/generate",
        json={
            "model":  config["ollama"]["model"],
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": config["ollama"]["temperature"],
                "num_predict": config["ollama"]["num_predict"],
            },
        },
        timeout=5000,  # 10 min — CPU inference can be slow, and that's fine
    )
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


# ── Graceful shutdown ─────────────────────────────────────────────────────────

_shutdown = False

def _handle_signal(sig, frame):
    global _shutdown
    log.info("Shutdown signal received — will stop after this thought completes.")
    _shutdown = True

signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    config    = load_config()
    memory    = Memory(config)
    journal   = Journal(config)
    heartbeat = Heartbeat(config)

    vault_name = config.get("vault_name", "The Vault")
    model      = config["ollama"]["model"]

    log.info("=" * 56)
    log.info(f"  {vault_name}")
    log.info(f"  model   : {model}")
    log.info(f"  thoughts: {memory.count()} stored")
    log.info(f"  library : {memory.library_count()} passages")
    log.info("=" * 56)

    heartbeat.write(status="starting", cycle=0, memory_size=memory.count())

    cycle = 0

    while not _shutdown:
        cycle += 1
        mode  = select_mode(config)

        log.info(f"─── Cycle {cycle} ─── mode: {mode}")

        # ── Gather ───────────────────────────────────────────────────
        heartbeat.write(
            status="gathering",
            mode=mode,
            cycle=cycle,
            memory_size=memory.count(),
        )

        recent = memory._recent
        anchor = recent[-1]["text"] if recent else None
        context = memory.gather(seed_text=anchor)

        lib_note = " + library" if context.get("library") else ""
        surfaced_note = " + surfaced" if context.get("surfaced") else ""
        log.info(f"  context: {len(context['recent'])} recent, "
                 f"{len(context['semantic'])} semantic"
                 f"{surfaced_note}{lib_note}")

        # ── Generate ─────────────────────────────────────────────────
        heartbeat.write(
            status="thinking",
            mode=mode,
            cycle=cycle,
            memory_size=memory.count(),
        )

        prompt = build_prompt(mode, context)

        try:
            raw_output = generate(config, prompt)
        except requests.exceptions.Timeout:
            log.error("Generation timed out — skipping cycle, sleeping 60s")
            time.sleep(60)
            continue
        except requests.exceptions.ConnectionError:
            log.error("Cannot reach Ollama — is it running? Sleeping 30s")
            time.sleep(30)
            continue
        except Exception as e:
            log.error(f"Generation error: {e} — sleeping 60s")
            time.sleep(60)
            continue

        if not raw_output:
            log.warning("Empty output — skipping cycle")
            continue

        thought, topics, mood, chain_of_thought = parse_output(raw_output)

        if not thought:
            log.warning("Could not parse a thought from output — skipping")
            continue

        log.info(f"  mood: {mood}  |  topics: {', '.join(topics[:3])}")
        log.info(f"  length: {len(thought.split())} words")

        # ── Store ─────────────────────────────────────────────────────
        source_ids = context.get("thought_ids", [])
        thought_id = memory.store(
            text=thought,
            mode=mode,
            topics=topics,
            mood=mood,
            source_ids=source_ids,
        )

        journal.append(
            thought=thought,
            mode=mode,
            topics=topics,
            mood=mood,
            cycle=cycle,
        )

        journal.append_cot(
            chain_of_thought=chain_of_thought,
            mode=mode,
            topics=topics,
            mood=mood,
            cycle=cycle,
        )

        if chain_of_thought:
            log.info(f"  cot: {len(chain_of_thought.split())} words captured")

        log.info(f"  stored: {thought_id}")

        # ── Rest ──────────────────────────────────────────────────────
        sleep_sec = sleep_duration(config, thought)

        heartbeat.write(
            status="resting",
            mode=mode,
            cycle=cycle,
            topics=topics,
            mood=mood,
            memory_size=memory.count(),
            last_thought_at=journal.last_timestamp(),
            next_sleep_sec=sleep_sec,
        )

        log.info(f"  resting {sleep_sec // 60}m {sleep_sec % 60}s\n")

        # Sleep in small increments so Ctrl+C is responsive
        # Re-write heartbeat each tick so the observer countdown is live
        slept = 0
        while slept < sleep_sec and not _shutdown:
            tick = min(5, sleep_sec - slept)
            time.sleep(tick)
            slept += tick
            remaining = max(0, sleep_sec - slept)
            heartbeat.write(
                status="resting",
                mode=mode,
                cycle=cycle,
                topics=topics,
                mood=mood,
                memory_size=memory.count(),
                last_thought_at=journal.last_timestamp(),
                next_sleep_sec=remaining,
            )

    # ── Clean shutdown ────────────────────────────────────────────────
    log.info("Vault closing. Thoughts preserved.")
    heartbeat.write(status="offline", cycle=cycle, memory_size=memory.count())


if __name__ == "__main__":
    main()
