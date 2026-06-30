import time
from voice_typer import ChunkTranscriber


def test_chunks_processed_in_order_despite_latency():
    results = []

    def handle(chunk, is_first):
        # Earlier items "take longer" — a single worker must still keep order.
        time.sleep(0.05 if chunk == "a" else 0.0)
        results.append(chunk)

    t = ChunkTranscriber(handle)
    t.start()
    t.submit("a", True)
    t.submit("b", False)
    t.submit("c", False)
    t.wait_idle()
    assert results == ["a", "b", "c"]


def test_is_first_flag_passed_through():
    seen = []

    def handle(chunk, is_first):
        seen.append((chunk, is_first))

    t = ChunkTranscriber(handle)
    t.start()
    t.submit("x", True)
    t.submit("y", False)
    t.wait_idle()
    assert seen == [("x", True), ("y", False)]


def test_handler_exception_does_not_stall_queue():
    results = []

    def handle(chunk, is_first):
        if chunk == "boom":
            raise RuntimeError("transcription failed")
        results.append(chunk)

    t = ChunkTranscriber(handle)
    t.start()
    t.submit("boom", True)
    t.submit("ok", False)
    t.wait_idle()
    assert results == ["ok"]
