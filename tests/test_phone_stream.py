from authops.phone.ivr import normalize_for_speech
from authops.phone.stream import Budget, Playback, latency_report, speakable_chunks

REPLY = normalize_for_speech("Thanks for holding. The member ID is KCM12345678, and the date of birth is "
                             "2015-03-04. I'm calling to check the status of a prior authorization for "
                             "physical therapy. Could you tell me if it has been approved?")


def test_chunks_never_split_identifiers():
    chunks = speakable_chunks(REPLY)
    assert len(chunks) >= 3
    joined = " | ".join(chunks)
    assert "K C M one two three four five six seven eight" in joined.replace(" | ", " ")
    for c in chunks:   # no chunk ends half-way through the spoken member ID or the date
        assert not c.rstrip(",").endswith(("K C M", "one two", "March 4,"))
    assert " ".join(chunks).split() == REPLY.split()


def test_streaming_cuts_time_to_first_audio():
    rep = latency_report([REPLY], Budget(), n=300)
    assert rep["streaming"]["p50_ms"] < rep["full_response"]["p50_ms"]
    assert rep["streaming"]["over_ivr_timeout"] <= rep["full_response"]["over_ivr_timeout"]


def test_interruption_keeps_only_what_was_heard():
    p = Playback()
    p.say(REPLY)
    p.mark()           # first chunk played
    p.interrupt()      # rep starts talking
    assert p.transcript() == speakable_chunks(REPLY)[0]
    assert p.dropped and not p.queue
