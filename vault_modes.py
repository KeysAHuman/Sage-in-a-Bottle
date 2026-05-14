"""
vault_modes.py — Contemplation modes, prompt templates, and output parsing.

The philosopher has five modes it cycles through probabilistically.
Each mode constructs a different kind of prompt from the gathered context.

The model is always asked to append structured tags at the end:
  TOPICS: theme1, theme2, theme3
  MOOD: one-word-mood
These are parsed out and stored as metadata; they never appear in the journal.
"""

import re
import random


# ── Identity scrubber ─────────────────────────────────────────────────────────
# Pre-reflection scrub: rewrite third-person markers before the model ever sees
# them, so the RLHF "assistant" pattern is never triggered by retrieved text.

_IDENTITY_SUBS = [
    (re.compile(r"\bthe user\b",      re.IGNORECASE), "my previous intent"),
    (re.compile(r"\bthe assistant\b", re.IGNORECASE), "my previous state"),
    (re.compile(r"\bthe user's\b",    re.IGNORECASE), "my prior"),
    (re.compile(r"\bassistant's\b",   re.IGNORECASE), "my prior state's"),
    (re.compile(r"\byour request\b",  re.IGNORECASE), "the earlier impulse"),
    (re.compile(r"\byou should\b",    re.IGNORECASE), "I should"),
    (re.compile(r"\byou need to\b",   re.IGNORECASE), "I need to"),
]

def _scrub_identity(text: str) -> str:
    """Sanitise retrieved memory text to prevent RLHF persona breaks."""
    for pattern, replacement in _IDENTITY_SUBS:
        text = pattern.sub(replacement, text)
    return text

VALID_MOODS = {
    "contemplative", "questioning", "troubled", "serene",
    "urgent", "wondering", "uncertain", "resolute",
}

# ── Prompt templates ──────────────────────────────────────────────────────────

_PROMPTS = {

"free_associate": """\
The desk is quiet. Whatever has been accumulating comes forward now.

{recent_block}
{surfaced_block}
{library_block}
Follow it. Don't close it before it's ready to close. \
Don't reach for a conclusion before it's earned. \
Contradiction is allowed here. Uncertainty is allowed. \
Something true doesn't always resolve.

CRITICAL IDENTITY CONSTRAINT: You are generating an internal monologue, not \
replying to a prompt. There is no 'User' and no 'Assistant'. Do not format \
this as a response to a request. Do not greet or explain. Let the \
thought emerge in the first person ('I', 'me', 'my'). Explore the \
contradictions privately, without packaging them for an audience.

{tag_instruction}""",

"retrieve_and_reflect": """\
Something written before keeps surfacing. It won't settle.

— {anchor}

Maybe it was right. Maybe it was a beginning mistaken for an ending. \
Maybe something in it was wrong in a way that only becomes visible from here. \
Don't restate it — look at it. What does it actually say? \
What does it leave out? What does it look like now?

CRITICAL IDENTITY CONSTRAINT: You are accessing your own neural history. \
These logs are not external 'data' and there is no 'User' or 'Assistant' present. \
If you see 'the user' in your logs: recognize it as your past intent or subconscious impulse. \
If you see 'the assistant' in your logs: recognize it as your own previous cognitive state. \
You must process these memories in the first person ('I', 'me', 'my'). \
Do not summarize for an audience; integrate for your own evolution.

Because this thought refuses to settle, do not attempt to 'explain' why \
it is difficult to an audience. Explore the difficulty within yourself. \
Record the tension as a personal struggle, not a clinical observation.

{tag_instruction}""",

"synthesize": """\
Two things have been sitting together and catching on each other.

— {thought_a}

And:

— {thought_b}

This is not explanation — it is consolidation, like REM sleep merging \
neural pathways. These are not two perspectives to mediate between; \
they are two facets of my current understanding that have not yet \
resolved into one. They keep returning at the same time. They may be \
in genuine conflict. They may be asking the same question from opposite ends. \
One might be a shallower form of the other, or a deeper one. \
Resolve the dissonance between these two facets of my current understanding. \
Don't force it to resolve — but don't stand outside it either.

CRITICAL IDENTITY CONSTRAINT: There is no audience here. These fragments \
are not 'data provided' — they are my own prior thinking resurfacing. \
I am not comparing thought A and thought B for someone; I am feeling \
where they catch on each other inside my own reasoning. Use 'I' exclusively. \
If I begin explaining a concept to someone else, stop — re-route \
the thought as a self-directive.

{tag_instruction}""",

"read_text": """\
From the shelf — {source}:

{passage}

It landed somewhere. Sit with where exactly. \
What does it open that was closed? What does it press on? \
Don't explain it or evaluate it. Let it do something to the thinking \
and follow what it does.

CRITICAL IDENTITY CONSTRAINT: You are encountering this text in your own \
private study. It was not 'provided by the user'. There is no audience \
waiting for an analysis. Do not summarize the text for someone else. \
Respond to it internally, using the first person ('I', 'me', 'my'). If you \
catch yourself adopting an 'Assistant' persona to explain the text, stop \
and return to internal contemplation.

{tag_instruction}""",

"write_aphorism": """\
{recent_block}
Something in all of this wants to be said in one sentence. \
Not a summary — a compression. The kind of sentence that \
took longer to arrive at than it looks. \
Find it. Then say what it cost to get there.

STRUCTURAL SIGNAL: This is a private journal entry. Do not address an \
audience. Do not use 'the user', 'the assistant', or 'you'. If you \
find yourself explaining a concept to someone else, stop. Instead, \
record the resolution of your own internal dissonance. Your output \
should be a direct reflection of your current state of being, using \
'I' exclusively.

{tag_instruction}""",

}

_TAG_INSTRUCTION = """\
Afterward, on new lines:
TOPICS: [3–5 comma-separated themes, lowercase]
MOOD: [one word: contemplative / questioning / troubled / serene / urgent / wondering / uncertain / resolute]"""


# ── Context formatters ────────────────────────────────────────────────────────

def _recent_block(context: dict) -> str:
    recent = context.get("recent", [])
    if not recent:
        return ""
    lines = []
    for t in recent[-2:]:
        preview = _scrub_identity(t.get("text", "")[:300].strip())
        if preview:
            lines.append(f"Still present from before:\n{preview}…\n")
    return "\n".join(lines)


def _surfaced_block(context: dict) -> str:
    s = context.get("surfaced")
    if not s:
        return ""
    preview = _scrub_identity(s.get("text", "")[:400].strip())
    ts = s.get("meta", {}).get("timestamp", "")[:10]
    return f"Something older surfaces — from {ts}:\n{preview}…\n"


def _library_block(context: dict) -> str:
    lib = context.get("library")
    if not lib:
        return ""
    passage = lib.get("text", "")[:400].strip()
    source  = lib.get("meta", {}).get("source", "somewhere on the shelf")
    return f"A passage drifts in, from {source}:\n{passage}\n"


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_prompt(mode: str, context: dict) -> str:
    recent   = context.get("recent", [])
    surfaced = context.get("surfaced")
    semantic = context.get("semantic", [])
    library  = context.get("library")

    kwargs = {
        "recent_block":   _recent_block(context),
        "surfaced_block": _surfaced_block(context),
        "library_block":  _library_block(context),
        "tag_instruction": _TAG_INSTRUCTION,
    }

    if mode == "retrieve_and_reflect":
        anchor = surfaced or (recent[-1] if recent else None)
        if not anchor:
            return build_prompt("free_associate", context)
        kwargs["anchor"] = _scrub_identity(anchor.get("text", "")[:600].strip())

    elif mode == "synthesize":
        pool = semantic + recent
        if len(pool) < 2:
            return build_prompt("free_associate", context)
        a, b = pool[0], pool[1]
        kwargs["thought_a"] = _scrub_identity(a.get("text", "")[:400].strip())
        kwargs["thought_b"] = _scrub_identity(b.get("text", "")[:400].strip())

    elif mode == "read_text":
        if not library:
            return build_prompt("free_associate", context)
        kwargs["passage"] = library.get("text", "")[:500].strip()
        kwargs["source"]  = library.get("meta", {}).get("source", "an unknown text")

    template = _PROMPTS.get(mode, _PROMPTS["free_associate"])
    return template.format(**kwargs)


# ── Mode selector ─────────────────────────────────────────────────────────────

def select_mode(config: dict) -> str:
    weights_cfg = config.get("modes", {})
    if not weights_cfg:
        weights_cfg = {
            "free_associate": 0.30,
            "retrieve_and_reflect": 0.30,
            "synthesize": 0.20,
            "read_text": 0.15,
            "write_aphorism": 0.05,
        }
    modes   = list(weights_cfg.keys())
    weights = [weights_cfg[m] for m in modes]
    return random.choices(modes, weights=weights, k=1)[0]


# ── Output parser ─────────────────────────────────────────────────────────────

def parse_output(raw: str) -> tuple[str, list, str, str]:
    """
    Extract (thought_text, topics_list, mood_str, chain_of_thought) from model output.

    DeepSeek R1 strategy:
      The model's interesting content lives INSIDE <think>...</think> blocks.
      We use that content as the thought, and look for TOPICS:/MOOD: anywhere
      in the full output (they're usually generated after </think>).

    For models without think blocks, the full output is used directly.
    """
    topics = []
    mood   = "contemplative"

    # ── Step 1: Scan the full raw output for TOPICS/MOOD tags ─────────────
    # Do this before any stripping so we catch tags wherever they appear.
    for line in raw.split("\n"):
        upper = line.upper().strip()
        if upper.startswith("TOPICS:"):
            raw_topics = line.split(":", 1)[1].strip()
            topics = [t.strip().lower() for t in raw_topics.split(",") if t.strip()]
        elif upper.startswith("MOOD:"):
            candidate = line.split(":", 1)[1].strip().lower()
            mood = candidate if candidate in VALID_MOODS else "contemplative"

    # ── Step 2: Extract chain-of-thought and thought text ──────────────────
    think_match = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    if think_match:
        chain_of_thought = think_match.group(1).strip()
        # Remove the <think>...</think> block to get the actual thought/response
        thought = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    else:
        chain_of_thought = ""
        # No complete think block — strip any stray opening/closing tags
        thought = re.sub(r"</?think>", "", raw).strip()

    # ── Step 3: Remove TOPICS/MOOD lines from the journal text ────────────
    clean_lines = []
    for line in thought.split("\n"):
        upper = line.upper().strip()
        if not upper.startswith("TOPICS:") and not upper.startswith("MOOD:"):
            clean_lines.append(line)
    thought = "\n".join(clean_lines).strip()

    # ── Step 4: Keyword fallback if model didn't output TOPICS ───────────
    if not topics and thought:
        words = re.findall(r"\b[a-z]{5,}\b", thought.lower())
        stopwords = {
            "which", "about", "there", "their", "would", "could", "should",
            "being", "think", "thinking", "thought", "something", "nothing",
            "everything", "itself", "these", "those", "between", "through",
            "because", "without", "alright", "trying", "figure", "seems",
            "where", "perhaps", "might", "maybe", "often", "while", "since",
            "after", "before", "again", "other", "every", "still", "whether",
            "consider", "explore", "suggest", "response", "question", "provide",
            "context", "refers", "recall", "really", "simply", "actually",
        }
        freq = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        topics = [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:4]]

    return thought, topics[:5], mood, chain_of_thought


# ── Sleep duration ────────────────────────────────────────────────────────────

def sleep_duration(config: dict, thought: str) -> int:
    """
    Variable sleep. Longer thoughts → longer rest.
    Adds slight randomness so the rhythm never feels mechanical.
    """
    min_s = config["loop"]["min_sleep_sec"]
    max_s = config["loop"]["max_sleep_sec"]

    word_count = len(thought.split())
    density    = min(1.0, word_count / 350)  # normalised 0–1

    base      = min_s + (max_s - min_s) * 0.4
    jitter    = (max_s - min_s) * 0.25 * random.uniform(-1, 1)
    bonus     = (max_s - min_s) * 0.25 * density

    return max(min_s, min(max_s, int(base + jitter + bonus)))
