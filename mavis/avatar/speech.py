"""Voice an answer sentence by sentence while it is still being written.

The backend streams the answer; each sentence is spoken as soon as it is
complete, so he starts talking after ONE sentence has been written and voiced
rather than after the whole reply. Three parties, two queues:

    feeder    (the asyncio loop)   feed(sentence) ... close() / fail(exc)
    producer  (a thread here)      sentence -> wav, in order
    consumer  (Runtime._speak)     next() -> (wav, sentence), None at the end

`SentenceCutter` is the piece that turns a stream of text fragments into
whole sentences, never ending one after "U.S." or "Dr.".
"""
import os
import queue
import re
import threading

_END = object()

_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "inc.",
                  "co.", "vs.", "etc.", "e.g.", "i.e."}
_INITIALISM = re.compile(r"(?:[A-Za-z]\.){2,}")


def _is_abbreviation(token: str) -> bool:
    return token.lower() in _ABBREVIATIONS or bool(_INITIALISM.fullmatch(token))


def _ends_a_sentence(sentence: str) -> bool:
    last = sentence.rsplit(" ", 1)[-1]
    return last[-1:] in ".!?" and not _is_abbreviation(last)


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


# The first thing he says sets time-to-first-word, and a model asked for a
# short opener still sometimes writes one 170-character sentence (measured
# 2026-10-01: 11s of audio, 3s to voice, before he made a sound). So if the
# first sentence has not ended by FIRST_MAX_CHARS, it is cut at a clause break
# instead. Only the first: every cut is a small seam in the intonation, and
# after he has started the next sentence has the whole of this one to arrive.
FIRST_MAX_CHARS = 70
FIRST_MIN_CHARS = 25
_CLAUSE_BREAKS = ("; ", ": ", ", ", " -- ", " — ", " – ")


def _clause_cut(text: str):
    """Index just past the last clause break leaving a head of usable size."""
    best = None
    for delim in _CLAUSE_BREAKS:
        at = text.rfind(delim)
        if at < 0:
            continue
        # A dash opens the tail; other punctuation closes the head.
        cut = at if delim.startswith(" ") else at + len(delim) - 1
        if cut >= FIRST_MIN_CHARS and (best is None or cut > best):
            best = cut
    return best


class SentenceCutter:
    """Feed it text as it arrives; it hands back each sentence once complete.

    A sentence is complete only when text FOLLOWS its terminator: "3." may be
    the start of "3.5%", and "U.S." may be mid-sentence. The tail is
    returned by `flush()` when the stream ends.
    """

    def __init__(self):
        self._buffer = ""
        self._started = False

    def push(self, text: str) -> list[str]:
        self._buffer += text
        sentences = split_sentences(self._buffer)
        if sentences and self._buffer[-1:].isspace() and _ends_a_sentence(sentences[-1]):
            # Whitespace after the terminator is as good as the next word:
            # "3. " is not the start of "3.5%". This is what lets a line the
            # backend sends ahead of the answer be spoken while the answer
            # is still being written.
            self._buffer = ""
            self._started = True
            return sentences
        if len(sentences) < 2:
            if self._started or len(self._buffer) < FIRST_MAX_CHARS:
                return []
            cut = _clause_cut(self._buffer)
            if cut is None:
                return []
            head, self._buffer = self._buffer[:cut].strip(), self._buffer[cut:].lstrip()
            self._started = True
            return [head]
        done, tail = sentences[:-1], sentences[-1]
        # split_sentences collapses whitespace; the tail keeps streaming in,
        # so a trailing space the next fragment relies on must survive.
        self._buffer = tail + (" " if self._buffer[-1:].isspace() else "")
        self._started = True
        return done

    def flush(self) -> list[str]:
        sentences = split_sentences(self._buffer)
        self._buffer = ""
        return sentences


class SpeechStream:
    def __init__(self, speaker, workdir, on_degraded=None):
        self.speaker = speaker
        self.workdir = workdir
        self._on_degraded = on_degraded
        self._texts = queue.Queue()
        self._ready = queue.Queue()
        self._cancelled = threading.Event()
        self._done = False
        self._count = 0
        self._warned = False

    def start(self):
        threading.Thread(target=self._run, name="mavis-speech",
                         daemon=True).start()
        return self

    # -- feeder ---------------------------------------------------------------

    def feed(self, sentence: str) -> None:
        if sentence.strip():
            self._texts.put(sentence.strip())

    def close(self) -> None:
        self._texts.put(_END)

    def fail(self, exc: BaseException) -> None:
        """The answer broke off; what is already voiced still plays first."""
        self._texts.put(exc)

    # -- consumer -------------------------------------------------------------

    def next(self, timeout=None):
        """(wav path, sentence) to play next, None when the answer is over.

        Re-raises whatever the feeder reported. `queue.Empty` on timeout.
        """
        if self._done:
            return None
        item = self._ready.get(timeout=timeout)
        if item is _END or isinstance(item, BaseException):
            self._done = True
        if isinstance(item, BaseException):
            raise item
        return None if item is _END else item

    def cancel(self) -> None:
        self._cancelled.set()
        self._texts.put(_END)
        self._ready.put(_END)       # wake a consumer blocked in next()

    # -- producer -------------------------------------------------------------

    def _run(self):
        try:
            while not self._cancelled.is_set():
                item = self._texts.get()
                if item is _END or isinstance(item, BaseException):
                    self._ready.put(item)
                    return
                path = os.path.join(self.workdir, f"speech-{self._count}.wav")
                self._count += 1
                in_voice = self.speaker.synth(item, path)
                if self._cancelled.is_set():
                    # Its files may already be deleted; nothing here is news.
                    return
                if not in_voice and not self._warned and self._on_degraded:
                    self._warned = True
                    self._on_degraded()
                self._ready.put((path, item))
        except BaseException as exc:    # handed to the consumer, not lost here
            self._ready.put(exc)
