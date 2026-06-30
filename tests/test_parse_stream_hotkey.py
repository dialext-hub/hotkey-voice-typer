from voice_typer import _parse_stream_hotkey


def test_empty_disables():
    assert _parse_stream_hotkey("", "f9", set()) == (None, set())
    assert _parse_stream_hotkey(None, "f9", set()) == (None, set())
    assert _parse_stream_hotkey("   ", "f9", set()) == (None, set())


def test_distinct_key_enables():
    assert _parse_stream_hotkey("f10", "f9", set()) == ("f10", set())


def test_modifiers_parsed():
    assert _parse_stream_hotkey("ctrl+f10", "f9", set()) == ("f10", {"ctrl"})


def test_same_base_key_disables_even_with_different_modifiers():
    # f9 PTT + ctrl+f9 streaming would hijack F9 via name dispatch -> disable
    assert _parse_stream_hotkey("ctrl+f9", "f9", set()) == (None, set())


def test_exact_same_hotkey_disables():
    assert _parse_stream_hotkey("f9", "f9", set()) == (None, set())
