"""Split an answer into chunks that can be voiced while the last one plays.

Voice conversion no longer waits for the whole answer: chunk k is converted
while chunk k-1 is playing, so he starts talking after one short chunk instead
of after the whole reply. The chunk sizes come from how ChatterboxVC's cost
actually behaves, measured 2026-09-28: every call pays a FIXED cost on top of
RATE per second of speech, because the reference prompt is re-processed with
each call. That fixed cost is why equal sentence-sized chunks would stall.
Chunk k plays without a gap only if

    fixed + rate * d_k  <=  d_(k-1) + slack

so the first chunk is short (it sets time-to-first-word), and each later chunk
grows as large as the bound allows.

Pure stdlib, no audio: the durations are estimated from the text.
First drafted by the `delegate` model; its abbreviation check never matched
(it looked at the token without its final period) and was fixed in review.
"""
import re

# Real answers speak at 76-92 ms/char through `say`, slower than plain prose,
# because finance text expands ("U.S." is spelled out, "$8.9 trillion" is six
# words). Measured 2026-09-25.
SECONDS_PER_CHAR = 0.08

# Longest silence allowed between two chunks of one answer. A plan predicted to
# leave a longer one falls back to a single chunk -- the shipped behaviour:
# a longer wait before he speaks, then an unbroken answer. On battery with Low
# Power Mode (2026-09-28) conversion ran slower than realtime, and the naive
# plan said a clause, went quiet for 6-13 seconds mid-sentence, then went on.
# That reads as broken; waiting behind the filler line does not.
MAX_GAP_SECONDS = 1.0

# Must match `BUCKETS` in scripts/voice_worker.py (a test checks). The worker
# pads every input up to the next of these lengths, so a chunk costs as much as
# its bucket, not its own length: a 4.1s chunk costs a 6s conversion. Planning
# on the real length under-predicted gaps (code review, 2026-09-29).
BUCKETS = (1, 2, 3, 4, 6, 8, 12, 16)

_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "inc.",
                  "co.", "vs.", "etc.", "e.g.", "i.e."}
_INITIALISM = re.compile(r"(?:[A-Za-z]\.){2,}")
# (delimiter, head keeps it). A dash starts the tail rather than ending the head.
_CLAUSE_BREAKS = ((", ", True), ("; ", True), (": ", True),
                  (" -- ", False), (" — ", False))


def spoken_seconds(text: str) -> float:
    return len(text.strip()) * SECONDS_PER_CHAR


def bucket_seconds(seconds: float, buckets=BUCKETS) -> float:
    """The padded length the worker will actually convert."""
    for size in buckets:
        if seconds <= size:
            return float(size)
    return float(-(-seconds // buckets[-1]) * buckets[-1])


def _cost(text, fixed, rate, seconds):
    return fixed + rate * bucket_seconds(seconds(text))


def _is_abbreviation(token: str) -> bool:
    return token.lower() in _ABBREVIATIONS or bool(_INITIALISM.fullmatch(token))


def split_sentences(text: str) -> list[str]:
    """Sentences, punctuation kept, never split after "U.S." or "Dr."."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences, start = [], 0
    for match in re.finditer(r"[.!?]+(?= )", text):
        token = text[text.rfind(" ", 0, match.start()) + 1:match.end()]
        if _is_abbreviation(token):
            continue
        sentences.append(text[start:match.end()].strip())
        start = match.end()
    sentences.append(text[start:].strip())
    return [s for s in sentences if s]


def _split_first(sentence: str, max_chars: int, min_chars: int):
    """(head, tail) at the last clause break that keeps the head in bounds."""
    if len(sentence) <= max_chars:
        return sentence, None
    best = None
    for delim, keep in _CLAUSE_BREAKS:
        for match in re.finditer(re.escape(delim), sentence):
            cut = match.end() if keep else match.start()
            if min_chars <= cut <= max_chars and (best is None or cut > best):
                best = cut
    if best is None:
        return sentence, None
    return sentence[:best].strip(), sentence[best:].strip()


def predicted_gaps(chunks, *, fixed, rate, seconds=spoken_seconds):
    """Silence before each chunk after the first, if chunk k is converted
    while chunk k-1 plays and conversions run back to back."""
    ready = play_end = 0.0
    gaps = []
    for k, chunk in enumerate(chunks):
        ready += _cost(chunk, fixed, rate, seconds)
        start = ready if k == 0 else max(ready, play_end)
        if k:
            gaps.append(max(0.0, ready - play_end))
        play_end = start + seconds(chunk)
    return gaps


def plan(text: str, *, fixed: float, rate: float, first_max_chars: int = 90,
         min_first_chars: int = 20, slack: float = 0.3,
         max_gap: float = MAX_GAP_SECONDS, seconds=spoken_seconds) -> list[str]:
    """Chunks whose joined text is the input, sized so playback does not stall.

    The first chunk is the smallest that leaves no gap longer than `max_gap`
    anywhere after it: a clause of the first sentence, else the first one,
    two, ... sentences. The last candidate is the whole answer as one chunk,
    voiced before he starts -- the pre-chunking behaviour, and the answer
    whenever conversion is too slow for any split to keep up.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []
    candidates = []
    head, tail = _split_first(sentences[0], first_max_chars, min_first_chars)
    if tail:
        candidates.append((head, [tail] + sentences[1:]))
    for k in range(1, len(sentences) + 1):
        candidates.append((" ".join(sentences[:k]), sentences[k:]))
    for first, rest in candidates:
        chunks = [first] + _grow(first, rest, fixed=fixed, rate=rate,
                                 slack=slack, seconds=seconds)
        gaps = predicted_gaps(chunks, fixed=fixed, rate=rate, seconds=seconds)
        if not gaps or max(gaps) <= max_gap:
            return chunks
    return chunks   # unreachable: the last candidate has no gaps


def _grow(first, queue, *, fixed, rate, slack, seconds):
    """After `first`, each chunk as large as the gap bound allows.

    A single sentence too long for the bound still becomes one chunk: a pause
    before it is better than cutting a sentence mid-phrase.

    When even the next single sentence cannot meet the bound, a gap is coming
    anyway, and the chunk keeps growing until it is at least `fixed / (1 -
    rate)` seconds long. Below that break-even length no chunk can ever be
    followed without a gap, so sentence-sized chunks would stall at *every*
    boundary; taking the one gap with a bigger chunk lets the rest run clean.
    """
    break_even = fixed / (1.0 - rate) if rate < 1.0 else float("inf")
    chunks, previous = [], first
    i = 0
    while i < len(queue):
        budget = seconds(previous) + slack
        chunk, i = queue[i], i + 1
        stalls = _cost(chunk, fixed, rate, seconds) > budget
        while i < len(queue):
            candidate = f"{chunk} {queue[i]}"
            fits = _cost(candidate, fixed, rate, seconds) <= budget
            if not (fits or (stalls and seconds(chunk) < break_even)):
                break
            chunk, i = candidate, i + 1
        chunks.append(chunk)
        previous = chunk
    return chunks
