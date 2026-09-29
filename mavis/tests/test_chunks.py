import pytest

from avatar import chunks


INF = float("inf")


def _flat(text):
    return " ".join(text.split())


@pytest.mark.parametrize("text", [
    "The U.S. dollar is collateral. Everyone needs it.",
    "Use a hedge, e.g. gold. It works.",
    "Ask Dr. Powell. He knows.",
    "Rates rose vs. last year. Bonds fell.",
])
def test_abbreviations_do_not_end_a_sentence(text):
    assert len(chunks.split_sentences(text)) == 2


def test_punctuation_runs_end_a_sentence_and_stay_on_it():
    assert chunks.split_sentences("Really?! Yes... Fine.") == [
        "Really?!", "Yes...", "Fine."]


def test_decimals_and_newlines():
    assert chunks.split_sentences("It hit $8.9\ntrillion.  Then\n\nfell.") == [
        "It hit $8.9 trillion.", "Then fell."]


def test_empty():
    assert chunks.split_sentences("   ") == []
    assert chunks.plan(" \n", fixed=1, rate=0.5) == []


LONG_FIRST = ("When the Fed hikes rates, mortgage costs follow within weeks, and "
              "home sales cool off right behind them before anyone notices. Next.")


def test_long_first_sentence_splits_at_the_last_clause_break_in_bounds():
    out = chunks.plan(LONG_FIRST, fixed=0, rate=0)
    assert out[0] == "When the Fed hikes rates, mortgage costs follow within weeks,"
    assert _flat(" ".join(out)) == _flat(LONG_FIRST)


def test_first_sentence_without_a_usable_break_stays_whole():
    sentence = "x" * 120 + "."
    assert chunks.plan(sentence + " Tail.", fixed=9, rate=1)[0] == sentence


def test_a_break_too_early_is_not_used():
    sentence = "Yes, " + "y" * 120 + "."
    assert chunks.plan(sentence, fixed=0, rate=0, min_first_chars=20) == [sentence]


def test_dash_goes_on_the_tail():
    text = "Gold climbs when real yields fall hard and fast -- " + "z" * 60 + "."
    out = chunks.plan(text, fixed=0, rate=0, first_max_chars=60)
    assert out[0] == "Gold climbs when real yields fall hard and fast"
    assert out[1].startswith("-- ")


def test_short_first_sentence_is_the_first_chunk():
    out = chunks.plan("Listen up. The Fed moves first. Everyone follows.",
                      fixed=0.5, rate=0.5)
    assert out[0] == "Listen up."


def test_chunks_grow_when_the_bound_allows():
    text = " ".join(["Short sentence here."] * 12)
    out = chunks.plan(text, fixed=1.0, rate=0.5, slack=0, max_gap=INF)
    sizes = [len(c) for c in out]
    assert max(sizes[1:]) > sizes[0]
    assert len(out) < 12        # sentences were merged, not one chunk each


def test_after_an_unavoidable_gap_the_chunk_clears_break_even():
    # fixed=1, rate=0.5: break-even is 2s. A 1.6s first chunk cannot cover
    # even one 1.6s sentence, so the next chunk must reach 2s, not stay 1.6s.
    text = " ".join(["Short sentence here."] * 12)
    out = chunks.plan(text, fixed=1.0, rate=0.5, slack=0, max_gap=INF)
    assert chunks.spoken_seconds(out[1]) >= 2.0


def test_no_growth_past_break_even_when_nothing_fits():
    text = " ".join(["Short sentence here."] * 12)
    out = chunks.plan(text, fixed=1.0, rate=0.5, slack=0, max_gap=INF)
    # 2 sentences (3.28s) already clear 2s; a third would be greedy for nothing.
    assert len(chunks.split_sentences(out[1])) == 2


def test_rate_at_or_above_one_merges_everything_after_the_first():
    out = chunks.plan("A one. B two. C three. D four.", fixed=1.0, rate=1.2,
                      max_gap=INF)
    assert out == ["A one.", "B two. C three. D four."]


@pytest.mark.parametrize("fixed,rate", [(1.0, 0.5), (2.0, 0.4), (0.5, 0.8)])
def test_chunks_that_follow_a_gap_free_chunk_respect_the_bound(fixed, rate):
    text = " ".join(f"Sentence number {i} is about this long." for i in range(20))
    out = chunks.plan(text, fixed=fixed, rate=rate)
    break_even = fixed / (1 - rate)
    for prev, chunk in zip(out, out[1:]):
        if chunks.spoken_seconds(prev) >= break_even:
            assert (fixed + rate * chunks.spoken_seconds(chunk)
                    <= chunks.spoken_seconds(prev) + 0.3)


@pytest.mark.parametrize("text", [
    LONG_FIRST,
    "One. Two. Three. Four. Five.",
    "No punctuation at all just words",
    "The U.S. Treasury -- the floor under everything -- sets the price.\nThen QE/QT.",
])
def test_nothing_is_lost_reordered_or_duplicated(text):
    assert _flat(" ".join(chunks.plan(text, fixed=1.0, rate=0.5))) == _flat(text)


def test_predicted_gaps_follow_back_to_back_conversion():
    # 10 chars = 0.8s each. fixed=1, rate=1: chunk 0 ready at 1.8, plays to
    # 2.6; chunk 1 ready at 3.6 -> 1.0s gap.
    assert chunks.predicted_gaps(["a" * 10, "b" * 10], fixed=1.0, rate=1.0) == [
        pytest.approx(1.0)]
    assert chunks.predicted_gaps(["a" * 50, "b" * 10], fixed=0.5, rate=0.5) == [0.0]


ANSWER = ("Gold prices rise when real yields fall, because lower real rates "
          "make holding it cheaper for everyone. Central banks buy it too. "
          "And the dollar matters, since gold is priced in it.")


def test_slower_than_realtime_voices_the_answer_whole():
    """Battery + Low Power Mode, 2026-09-28: no plan can avoid a long gap."""
    assert chunks.plan(ANSWER, fixed=2.5, rate=1.2) == [_flat(ANSWER)]


def test_fast_conversion_keeps_the_clause_split():
    out = chunks.plan(ANSWER, fixed=0.8, rate=0.3)
    assert out[0] == "Gold prices rise when real yields fall,"
    assert max(chunks.predicted_gaps(out, fixed=0.8, rate=0.3)) <= 1.0


def test_a_clause_that_would_leave_a_gap_becomes_the_whole_sentence():
    fixed, rate = 1.5, 0.65
    clause = chunks._greedy(ANSWER, fixed=fixed, rate=rate, first_max_chars=90,
                            min_first_chars=20, slack=0.3,
                            seconds=chunks.spoken_seconds)
    assert max(chunks.predicted_gaps(clause, fixed=fixed, rate=rate)) > 1.0
    out = chunks.plan(ANSWER, fixed=fixed, rate=rate)
    assert out[0].endswith("for everyone.")
    assert max(chunks.predicted_gaps(out, fixed=fixed, rate=rate), default=0) <= 1.0
