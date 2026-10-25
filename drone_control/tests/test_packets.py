from drone_link.packets import build_extended_packet, build_short_packet


def test_short_layout():
    p = build_short_packet(10, 20, 30, 40, flags=1)
    assert len(p) == 8 and p[0] == 0x66 and p[7] == 0x99
    assert list(p[1:6]) == [10, 20, 30, 40, 1]
    assert p[6] == 10 ^ 20 ^ 30 ^ 40 ^ 1


def test_extended_layout():
    p = build_extended_packet(10, 20, 30, 40, flags1=1, flags2=2)
    assert len(p) == 20 and p[:2] == b"\x66\x14" and p[19] == 0x99
    assert list(p[2:8]) == [10, 20, 30, 40, 1, 2]
    assert p[18] == 10 ^ 20 ^ 30 ^ 40 ^ 1 ^ 2


def test_markers_escaped_and_clamped():
    p = build_short_packet(0x66, 0x99, 999, -5)
    assert p[1] == 0x67 and p[2] == 0x9A and p[3] == 255 and p[4] == 0


def test_frame_stats_detects_loss():
    from drone_link.video import CHUNK, FrameStats

    def pkt(fid, final, total, body):
        return bytes([fid, final, total, 0, 0, 0, 0, 0]) + body

    full = lambda head: head + bytes(CHUNK - len(head))   # a full-size non-final chunk
    st = FrameStats()
    # good 2-chunk frame; final chunk has padding after EOI
    st.feed(pkt(1, 0, 2, full(b"\xff\xd8abc"))); st.feed(pkt(1, 1, 2, b"def\xff\xd9junk"))
    # frame missing a chunk (final arrives after only 1 of 3)
    st.feed(pkt(2, 0, 3, full(b"\xff\xd8x"))); st.feed(pkt(2, 1, 3, b"y\xff\xd9"))
    # frame whose final chunk never arrives, then a good frame
    st.feed(pkt(3, 0, 2, full(b"\xff\xd8z"))); st.feed(pkt(4, 0, 2, full(b"\xff\xd8q"))); st.feed(pkt(4, 1, 2, b"r\xff\xd9"))
    s = st.summary()
    assert (st.ok, st.bad_count, st.abandoned) == (2, 1, 1), s
