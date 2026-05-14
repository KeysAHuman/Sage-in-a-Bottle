"""
vault_ingest.py — One-time library ingestion script.

Chunks all .txt and .md files from ./library/ into ~600-word passages,
embeds them, and loads them into the ChromaDB library collection.

Run once before starting the daemon:
  python vault_ingest.py

Safe to re-run — duplicate chunks are skipped via content hash.
The library is read-only at runtime; only this script writes to it.

Suggested free texts (Project Gutenberg):
  Plato     — The Republic, Phaedo, Symposium
  Aristotle — Nicomachean Ethics, Metaphysics
  Marcus Aurelius — Meditations
  Epictetus — Discourses
  Kant      — Critique of Pure Reason (Meiklejohn translation)
  Nietzsche — Thus Spoke Zarathustra, Beyond Good and Evil
  Tao Te Ching (Legge translation)
  Upanishads (various)
  Rilke     — Letters to a Young Poet
  Wittgenstein — Tractatus (Ogden translation)
"""

import hashlib
import sys
import yaml
from pathlib import Path
from vault_memory import Memory


def load_config() -> dict:
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def chunk_text(text: str, chunk_words: int = 550, overlap_words: int = 60) -> list[str]:
    """
    Split text into overlapping word chunks.
    Overlap prevents ideas from being cut off entirely at chunk boundaries.
    """
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i : i + chunk_words]
        if len(chunk) > 50:  # skip tiny trailing fragments
            chunks.append(" ".join(chunk))
        i += chunk_words - overlap_words
    return chunks


def main():
    config      = load_config()
    memory      = Memory(config)
    library_dir = Path(config["memory"]["library_dir"])

    if not library_dir.exists():
        print(f"\n  Library directory '{library_dir}' not found.")
        print("  Create it and drop in some .txt or .md files, then run again.\n")
        sys.exit(0)

    text_files = sorted(
        list(library_dir.glob("**/*.txt")) +
        list(library_dir.glob("**/*.md"))
    )

    if not text_files:
        print(f"\n  No .txt or .md files found in {library_dir}/")
        print("  The daemon will still run — it just won't have library passages.\n")
        sys.exit(0)

    print(f"\n  Ingesting {len(text_files)} file(s) into library…\n")

    total_new    = 0
    total_skip   = 0
    total_errors = 0
    interrupted  = False

    try:
        for filepath in text_files:
            print(f"  📄 {filepath.name}")
            try:
                text   = filepath.read_text(encoding="utf-8", errors="ignore")
                text   = " ".join(text.split())  # normalise whitespace
                chunks = chunk_text(text)
                source = filepath.stem.replace("_", " ").replace("-", " ")

                new_here     = 0
                skipped_here = 0
                for i, chunk in enumerate(chunks):
                    chunk_hash = hashlib.md5(chunk.encode()).hexdigest()[:12]
                    chunk_id   = f"{filepath.stem}_{chunk_hash}"

                    try:
                        was_new = memory.add_library_text(chunk, source, chunk_id)
                        if was_new:
                            new_here   += 1
                            total_new  += 1
                        else:
                            skipped_here += 1
                            total_skip   += 1
                    except KeyboardInterrupt:
                        raise  # let it propagate to the outer handler
                    except Exception as e:
                        total_errors += 1
                        print(f"\n    ⚠ Chunk {i+1} error: {e}")

                    # Progress
                    print(f"    {i + 1}/{len(chunks)} chunks processed", end="\r")

                if skipped_here == len(chunks):
                    print(f"    ✓ already fully ingested ({skipped_here} chunks)    ")
                elif skipped_here > 0:
                    print(f"    {new_here} new  |  {skipped_here} already existed    ")
                else:
                    print(f"    {new_here} chunks ingested    ")

            except KeyboardInterrupt:
                raise  # let it propagate to the outer handler
            except Exception as e:
                print(f"    ✗ ERROR: {e}")

    except KeyboardInterrupt:
        interrupted = True
        print("\n\n  ⛔ Interrupted by user — progress so far is saved.")
        print("  Re-run this script to resume; already-ingested chunks will be skipped.\n")

    print(f"\n  {'Partial' if interrupted else 'Done'}.")
    print(f"  {total_new:>5} new chunks ingested")
    print(f"  {total_skip:>5} skipped (already in database)")
    if total_errors:
        print(f"  {total_errors:>5} errors")
    print(f"  Library now has {memory.library_count()} total passages.\n")


if __name__ == "__main__":
    main()
