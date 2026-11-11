import graywind_grounding


def test_retrieve_matches_watchlist_query():
    hits = graywind_grounding.retrieve("what is graywind's watchlist")

    assert any(h["id"] == "watchlist" for h in hits)


def test_retrieve_returns_empty_for_unrelated_query():
    hits = graywind_grounding.retrieve("!!! ??? ...")

    assert hits == []


def test_retrieve_does_not_match_on_a_single_ordinary_word():
    hits = graywind_grounding.retrieve("approval")

    assert hits == []


def test_retrieve_does_not_flood_on_the_universal_namespace_tag():
    hits = graywind_grounding.retrieve("how is graywind doing lately")

    assert hits == []


def test_a_symbol_tag_stays_strong_even_when_it_is_on_every_fact(monkeypatch):
    # A single-symbol watchlist is a normal, plausible operational state --
    # unlike "graywind" (always on every fact by construction), a symbol
    # tag being on every fact here is just a data coincidence and must not
    # get demoted to a weak term.
    fake_facts = [
        {"id": "watchlist", "tags": ["watchlist", "graywind", "aapl"], "text": "Graywind's active trading watchlist is AAPL."},
        {"id": "pending-100k-13", "tags": ["pending", "graywind", "100k", "aapl"], "text": "Pending trade proposal for AAPL, tier 2, awaiting manual approval."},
    ]
    monkeypatch.setattr(graywind_grounding, "_FACTS", fake_facts)
    monkeypatch.setattr(
        graywind_grounding, "_STRONG_TERMS",
        {tag for fact in fake_facts for tag in fact["tags"]} - {"graywind"},
    )

    hits = graywind_grounding.retrieve("AAPL pending trade")

    assert any(h["id"] == "pending-100k-13" for h in hits)


def test_format_context_returns_none_for_no_hits():
    assert graywind_grounding.format_context([]) is None


def test_format_context_includes_hit_text():
    hits = [{"type": "graywind_fact", "id": "watchlist", "text": "Graywind's active trading watchlist is AAPL, SERV."}]

    context = graywind_grounding.format_context(hits)

    assert "AAPL, SERV" in context


def _point_at(tmp_path, monkeypatch, facts):
    import json
    path = tmp_path / "gg.json"
    path.write_text(json.dumps({"facts": facts}))
    monkeypatch.setattr(graywind_grounding, "_GROUNDING_PATH", str(path))
    monkeypatch.setattr(graywind_grounding, "_loaded_stamp", None)
    monkeypatch.setattr(graywind_grounding, "_bad_stamp", None)
    monkeypatch.setattr(graywind_grounding, "_FACTS", [])
    monkeypatch.setattr(graywind_grounding, "_STRONG_TERMS", set())
    return path


def _fact(sym):
    return {"id": f"d-{sym}", "tags": ["decision", "graywind", sym.lower()],
            "text": f"Most recent decision for {sym}: hold."}


def test_facts_reload_on_mtime_change(tmp_path, monkeypatch):
    import json, os
    path = _point_at(tmp_path, monkeypatch, [_fact("NVDA")])
    assert graywind_grounding.retrieve("nvda decision")
    path.write_text(json.dumps({"facts": [_fact("TSLA"), _fact("AMD")]}))
    os.utime(path, ns=(1, 2_000_000_000_000_000_000))
    ids = {h["id"] for h in graywind_grounding.retrieve("nvda tsla amd decision")}
    assert ids == {"d-TSLA", "d-AMD"}


def test_corrupt_file_keeps_last_good_facts(tmp_path, monkeypatch, capsys):
    import os
    path = _point_at(tmp_path, monkeypatch, [_fact("NVDA")])
    assert graywind_grounding.retrieve("nvda decision")
    path.write_text('{"facts": [ {"id": "half-writ')
    os.utime(path, ns=(1, 2_000_000_000_000_000_000))
    assert graywind_grounding.retrieve("nvda decision")
    graywind_grounding.retrieve("nvda decision")
    assert capsys.readouterr().err.count("keeping last good facts") == 1    # warned once
    path.unlink()
    assert graywind_grounding.retrieve("nvda decision")
