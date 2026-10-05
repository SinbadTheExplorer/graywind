"""Cutting a streamed answer into sentences, and voicing them in order."""
import os

import pytest

from avatar import speech


@pytest.mark.parametrize("text", [
    "The U.S. dollar is collateral. Everyone needs it.",
    "Use a hedge, e.g. gold. It works.",
    "Ask Dr. Powell. He knows.",
    "Rates rose vs. last year. Bonds fell.",
])
def test_abbreviations_do_not_end_a_sentence(text):
    assert len(speech.split_sentences(text)) == 2


def test_punctuation_runs_end_a_sentence_and_stay_on_it():
    assert speech.split_sentences("Really?! Yes... Fine.") == [
        "Really?!", "Yes...", "Fine."]


def test_decimals_and_newlines():
    assert speech.split_sentences("It hit $8.9\ntrillion.  Then\n\nfell.") == [
        "It hit $8.9 trillion.", "Then fell."]


def _cut(fragments):
    cutter, out = speech.SentenceCutter(), []
    for fragment in fragments:
        out += cutter.push(fragment)
    return out, cutter.flush()


def test_a_sentence_is_handed_over_once_the_next_one_starts():
    """Not at its full stop: "3." may be the first half of "3.5%"."""
    cutter = speech.SentenceCutter()
    assert cutter.push("Gold is up 3.") == []
    assert cutter.push("5% today.") == []
    assert cutter.push(" The") == ["Gold is up 3.5% today."]
    assert cutter.flush() == ["The"]


def test_a_sentence_followed_by_a_space_is_handed_over_at_once():
    """The backend's opening line arrives whole, seconds before the answer."""
    cutter = speech.SentenceCutter()
    assert cutter.push("Give me a second, I'm pulling the wires. ") == [
        "Give me a second, I'm pulling the wires."]
    assert cutter.push("Bond yields are up. ") == ["Bond yields are up."]
    assert cutter.push("Ask Dr. ") == []             # an abbreviation is not an end
    assert cutter.push("Powell.") == []
    assert cutter.flush() == ["Ask Dr. Powell."]


def test_fragments_split_anywhere_rejoin_into_the_same_sentences():
    text = "Listen up. The U.S. dollar is collateral. Everyone needs it, choom."
    for size in (1, 3, 7, 200):
        done, tail = _cut([text[i:i + size] for i in range(0, len(text), size)])
        assert done + tail == speech.split_sentences(text)


def test_a_long_first_sentence_is_cut_at_a_clause_so_he_can_start():
    text = ("When real yields drop, gold climbs as investors chase the hedge; the "
            "upside lands on bullion holders while central banks bear the cost. Next one.")
    done, tail = _cut([text[i:i + 5] for i in range(0, len(text), 5)])
    first = done[0]
    assert speech.FIRST_MIN_CHARS <= len(first) < speech.FIRST_MAX_CHARS + 5
    assert first.endswith((",", ";"))
    assert " ".join(done + tail) == text         # nothing lost, nothing repeated


def test_only_the_first_sentence_is_ever_cut_mid_way():
    long_one = "This second sentence, which runs on, and on, and on, well past the limit, stays whole."
    done, tail = _cut(["Short opener. ", long_one, " End."])
    assert done == ["Short opener.", long_one]
    assert tail == ["End."]


def test_a_long_first_sentence_with_no_clause_break_stays_whole():
    text = "A" + " word" * 30 + ". Tail."
    done, tail = _cut([text])
    assert done == [text[:-6]] and tail == ["Tail."]


class FakeSpeaker:
    def __init__(self, fail_on=()):
        self.fail_on = set(fail_on)
        self.said = []
        self.last_error = None

    def synth(self, text, path):
        self.said.append(text)
        with open(path, "wb") as handle:
            handle.write(b"x")
        if text in self.fail_on:
            self.last_error = "kokoro failed"
            return False
        return True


def _drain(stream):
    out = []
    while (item := stream.next(timeout=5)) is not None:
        out.append(item)
    return out


def test_sentences_come_out_voiced_and_in_order(tmp_path):
    speaker = FakeSpeaker()
    stream = speech.SpeechStream(speaker, str(tmp_path)).start()
    for sentence in ("One.", "Two.", "Three."):
        stream.feed(sentence)
    stream.close()
    items = _drain(stream)
    assert [text for _, text in items] == ["One.", "Two.", "Three."]
    assert all(os.path.exists(path) for path, _ in items)
    assert len({path for path, _ in items}) == 3
    assert stream.next() is None                 # stays finished


def test_the_first_sentence_is_ready_before_the_answer_is_finished(tmp_path):
    stream = speech.SpeechStream(FakeSpeaker(), str(tmp_path)).start()
    stream.feed("One.")
    assert stream.next(timeout=5)[1] == "One."   # no close() yet
    stream.cancel()


def test_a_fallback_sentence_is_reported_once_and_still_played(tmp_path):
    warned = []
    speaker = FakeSpeaker(fail_on={"Two.", "Three."})
    stream = speech.SpeechStream(speaker, str(tmp_path),
                                 on_degraded=lambda: warned.append(speaker.last_error)).start()
    for sentence in ("One.", "Two.", "Three."):
        stream.feed(sentence)
    stream.close()
    assert len(_drain(stream)) == 3
    assert warned == ["kokoro failed"]


def test_a_broken_answer_plays_what_it_has_then_raises(tmp_path):
    stream = speech.SpeechStream(FakeSpeaker(), str(tmp_path)).start()
    stream.feed("One.")
    stream.fail(RuntimeError("backend dropped"))
    assert stream.next(timeout=5)[1] == "One."
    with pytest.raises(RuntimeError, match="backend dropped"):
        stream.next(timeout=5)
    assert stream.next() is None


def test_cancel_wakes_a_waiting_consumer(tmp_path):
    stream = speech.SpeechStream(FakeSpeaker(), str(tmp_path)).start()
    stream.cancel()
    assert stream.next(timeout=5) is None


def test_blank_sentences_are_not_voiced(tmp_path):
    speaker = FakeSpeaker()
    stream = speech.SpeechStream(speaker, str(tmp_path)).start()
    stream.feed("   ")
    stream.close()
    assert _drain(stream) == [] and speaker.said == []
