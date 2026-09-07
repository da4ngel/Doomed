"""One token counter, shared by ingestion and the reasoning runtime.

WHY it lives in core: the chunker sizes chunks by tokens and the agent budget reserves
them, so both need the SAME number. They used different ones - the chunker asked
tiktoken, the runtime counted UTF-8 bytes - and a budget denominated in a different
unit from the thing it is budgeting is not a budget.

`src/agents/runtime.py` may not import from ingestion, graph or retrieval, so the
estimator cannot live in an adapter module and be shared. It belongs here.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: Which counter the process actually used. Read by the build manifest so a chunk count
#: can always be traced to the tokenizer that produced it.
TOKENIZER_USED = "unknown"

#: Bytes per token when tiktoken is unreachable. Roughly right for English prose and
#: deliberately not tuned - it is a fallback, not a second supported mode.
_BYTES_PER_TOKEN = 4

_ENCODING = None


def _encoding():
    global _ENCODING
    if _ENCODING is None:
        import tiktoken

        _ENCODING = tiktoken.get_encoding("cl100k_base")
    return _ENCODING


def estimate_tokens(text: str) -> int:
    """Token count via tiktoken when available, else a 4-chars-per-token estimate.

    The estimate is a fallback rather than the default because chunk sizing is a reported
    experiment (300/600/1000 sweep) and an approximate denominator would make those
    numbers soft.

    WHY the fallback is loud: it used to be silent, and it changes the chunk count from
    identical inputs and identical code, because `tiktoken.get_encoding` DOWNLOADS its
    BPE table on first use and fails offline. Two builders reported 2,474 and 2,487
    chunks from the same corpus and neither could tell which denominator either build had
    used. A number that quietly reshapes the index - and therefore every retrieval metric
    computed from it - has to announce itself.
    """
    global TOKENIZER_USED
    try:
        count = len(_encoding().encode(text))
    except Exception as exc:  # noqa: BLE001 - never let token counting break a run
        if TOKENIZER_USED != "char-estimate":
            TOKENIZER_USED = "char-estimate"
            log.warning(
                "tiktoken unavailable (%s: %s) - falling back to a 4-chars-per-token "
                "ESTIMATE. Chunk boundaries, and every metric computed from them, will "
                "not match a build made with tiktoken. Install it, or reach the network "
                "once so the BPE table caches, before recording any reported number.",
                type(exc).__name__,
                exc,
            )
        return max(1, len(text) // _BYTES_PER_TOKEN)
    if TOKENIZER_USED == "unknown":
        TOKENIZER_USED = "tiktoken-cl100k_base"
    return count
