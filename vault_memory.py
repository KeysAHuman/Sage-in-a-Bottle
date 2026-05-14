"""
vault_memory.py — Memory layer for The Vault

Two stores:
  - thoughts:  everything the philosopher has generated (grows over time)
  - library:   pre-loaded source texts (read-only after ingest)

Plus a recent.json index for fast retrieval of the last N thoughts
without scanning the full vector DB each cycle.
"""

import json
import random
import uuid
import requests
from datetime import datetime
from pathlib import Path
from collections import deque


class Memory:
    def __init__(self, config):
        self.cfg = config
        data_dir = Path(config["memory"]["data_dir"])
        data_dir.mkdir(parents=True, exist_ok=True)

        # Lazy import so the file is usable even if chromadb isn't installed yet
        import chromadb
        self.client = chromadb.PersistentClient(path=str(data_dir / "chromadb"))
        self.thoughts = self.client.get_or_create_collection("thoughts")
        self.library  = self.client.get_or_create_collection("library")

        # Recent index — keeps last 20 thought previews in a fast JSON file
        self._recent_path = data_dir / "recent.json"
        self._recent = self._load_recent()

        self._host        = config["ollama"]["host"]
        self._embed_model = config["ollama"]["embed_model"]

    # ── Recent index ──────────────────────────────────────────────────────

    def _load_recent(self) -> deque:
        if self._recent_path.exists():
            with open(self._recent_path) as f:
                return deque(json.load(f), maxlen=20)
        return deque(maxlen=20)

    def _save_recent(self):
        with open(self._recent_path, "w") as f:
            json.dump(list(self._recent), f, indent=2)

    # ── Embedding ─────────────────────────────────────────────────────────

    def _embed(self, text: str, retries: int = 3) -> list:
        """
        Embed text via Ollama with retry + backoff.
        First attempt uses a longer timeout to allow model cold-start.
        """
        import time
        last_err = None
        for attempt in range(retries):
            # Longer timeout on first attempt (model may need to load)
            timeout = 300 if attempt == 0 else 180
            try:
                resp = requests.post(
                    f"{self._host}/api/embeddings",
                    json={"model": self._embed_model, "prompt": text[:2000]},
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.json()["embedding"]
            except KeyboardInterrupt:
                raise  # always let Ctrl+C through
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    wait = 5 * (3 ** attempt)  # 5s, 15s, 45s
                    print(f"\n    ⏳ Embed timeout (attempt {attempt+1}/{retries}), retrying in {wait}s…", end="", flush=True)
                    time.sleep(wait)
        raise last_err  # all retries exhausted

    # ── Write ─────────────────────────────────────────────────────────────

    def store(
        self,
        text: str,
        mode: str,
        topics: list,
        mood: str,
        source_ids: list = None,
    ) -> str:
        ts = datetime.now()
        thought_id = f"t_{ts.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

        meta = {
            "timestamp": ts.isoformat(),
            "mode":      mode,
            "topics":    ",".join(topics[:5]) if topics else "",
            "mood":      mood or "neutral",
            "depth":     len(source_ids) if source_ids else 0,
        }

        embedding = self._embed(text)
        self.thoughts.add(
            ids=[thought_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )

        # Update the recent index (stores a 500-char preview, not full text)
        self._recent.append({
            "id":   thought_id,
            "text": text[:500],
            "meta": meta,
        })
        self._save_recent()

        return thought_id

    def library_id_exists(self, chunk_id: str) -> bool:
        """Check whether a library chunk ID already exists in the collection."""
        full_id = f"lib_{chunk_id}"
        try:
            result = self.library.get(ids=[full_id])
            return bool(result and result["ids"])
        except Exception:
            return False

    def add_library_text(self, text: str, source: str, chunk_id: str) -> bool:
        """
        Called by vault_ingest.py only — library is read-only at runtime.
        Returns True if the chunk was newly inserted, False if it already existed.
        """
        full_id = f"lib_{chunk_id}"

        # Explicit existence check — the primary duplicate guard
        if self.library_id_exists(chunk_id):
            return False

        embedding = self._embed(text)
        # Use upsert (not add) as a safety net: if the ID somehow already
        # exists despite the check above, this overwrites instead of doubling.
        self.library.upsert(
            ids=[full_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{"source": source}],
        )
        return True

    # ── Read / Gather ─────────────────────────────────────────────────────

    def gather(self, seed_text: str = None) -> dict:
        """
        Assemble context for the next thought cycle.
        Returns a dict with: recent, semantic, surfaced, library, thought_ids.
        """
        result = {
            "recent":     list(self._recent)[-2:],  # last 2 thoughts (previews)
            "semantic":   [],
            "surfaced":   None,
            "library":    None,
            "thought_ids": [],
        }

        total = self.count()

        # ── Semantic retrieval ──────────────────────────────────────
        if seed_text and total > 0:
            try:
                n = min(3, total)
                sem = self.thoughts.query(query_texts=[seed_text], n_results=n)
                for i, tid in enumerate(sem["ids"][0]):
                    result["semantic"].append({
                        "id":   tid,
                        "text": sem["documents"][0][i],
                        "meta": sem["metadatas"][0][i],
                    })
                    result["thought_ids"].append(tid)
            except Exception:
                pass

        # ── Random surfacing (old thought) ─────────────────────────
        if total > 5:
            try:
                offset = random.randint(0, total - 1)
                item = self.thoughts.get(limit=1, offset=offset)
                if item["ids"]:
                    result["surfaced"] = {
                        "id":   item["ids"][0],
                        "text": item["documents"][0],
                        "meta": item["metadatas"][0],
                    }
                    result["thought_ids"].append(item["ids"][0])
            except Exception:
                pass

        # ── Library passage (30% chance per cycle) ─────────────────
        lib_count = self.library.count()
        if lib_count > 0 and random.random() < 0.30:
            try:
                offset = random.randint(0, lib_count - 1)
                item = self.library.get(limit=1, offset=offset)
                if item["ids"]:
                    result["library"] = {
                        "id":   item["ids"][0],
                        "text": item["documents"][0],
                        "meta": item["metadatas"][0],
                    }
            except Exception:
                pass

        return result

    # ── Counts ────────────────────────────────────────────────────────────

    def count(self) -> int:
        return self.thoughts.count()

    def library_count(self) -> int:
        return self.library.count()
