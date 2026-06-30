from voice_typer import decide_key_action


def _state(ptt_recording=False, stream_active=False, stream_key_held=False,
           stream_key="f10"):
    return {
        "ptt_key": "f9",
        "stream_key": stream_key,
        "ptt_recording": ptt_recording,
        "stream_active": stream_active,
        "stream_key_held": stream_key_held,
    }


# --- streaming toggle key ---

def test_tap_stream_key_from_idle_starts_stream():
    assert decide_key_action("down", "f10", True, _state()) == "start_stream"


def test_tap_stream_key_during_session_stops_stream():
    assert decide_key_action("down", "f10", True,
                             _state(stream_active=True)) == "stop_stream"


def test_stream_key_autorepeat_is_ignored():
    # physically held -> repeated downs must not toggle
    assert decide_key_action("down", "f10", True,
                             _state(stream_key_held=True)) == "ignore"
    assert decide_key_action("down", "f10", True,
                             _state(stream_active=True, stream_key_held=True)) == "ignore"


def test_stream_key_up_is_ignored():
    assert decide_key_action("up", "f10", True, _state(stream_active=True)) == "ignore"


def test_stream_key_ignored_while_ptt_recording():
    assert decide_key_action("down", "f10", True,
                             _state(ptt_recording=True)) == "ignore"


def test_stream_start_requires_modifiers():
    assert decide_key_action("down", "f10", False, _state()) == "ignore"


def test_stream_stop_does_not_require_modifiers():
    # toggling OFF works even if modifiers aren't held
    assert decide_key_action("down", "f10", False,
                             _state(stream_active=True)) == "stop_stream"


def test_stream_key_none_disables_streaming_branch():
    st = _state(stream_key=None)
    assert decide_key_action("down", "f10", True, st) == "ignore"


# --- push-to-talk key (unchanged behavior) ---

def test_ptt_down_from_idle_starts_ptt():
    assert decide_key_action("down", "f9", True, _state()) == "start_ptt"


def test_ptt_up_while_recording_stops_ptt():
    assert decide_key_action("up", "f9", True, _state(ptt_recording=True)) == "stop_ptt"


def test_ptt_autorepeat_is_ignored():
    assert decide_key_action("down", "f9", True, _state(ptt_recording=True)) == "ignore"


def test_ptt_ignored_while_stream_active():
    assert decide_key_action("down", "f9", True, _state(stream_active=True)) == "ignore"


def test_ptt_down_requires_modifiers():
    assert decide_key_action("down", "f9", False, _state()) == "ignore"


def test_ptt_up_while_not_recording_is_ignored():
    assert decide_key_action("up", "f9", True, _state()) == "ignore"


def test_unrelated_key_is_ignored():
    assert decide_key_action("down", "x", True, _state()) == "ignore"
