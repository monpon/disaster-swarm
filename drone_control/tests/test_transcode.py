import io
import random

from PIL import Image

from relay.transcode import FrameAssembler, chunk_frame, downscale, jpeg_size


def _frame(w=640, h=360):
    rnd = random.Random(1)
    im = Image.new("RGB", (w, h))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(w * h)])
    out = io.BytesIO()
    im.save(out, "JPEG", quality=70)
    return out.getvalue()


def test_roundtrip_downscale_320x240():
    src = _frame()
    assert jpeg_size(src) == (640, 360)
    hdr5 = bytes([2, 0, 0, 0, 0])
    asm = FrameAssembler()
    got = None
    for p in chunk_frame(src, 7, hdr5):          # packetise like the drone does
        got = asm.feed(p) or got
    assert got and got[0] == src
    small = downscale(src, (320, 240), 60)
    assert jpeg_size(small) == (320, 240) and len(small) < len(src)
    asm2, out = FrameAssembler(), None
    for p in chunk_frame(small, 1, got[1]):
        out = asm2.feed(p) or out
    assert out and Image.open(io.BytesIO(out[0])).size == (320, 240)


def test_lost_chunk_is_not_emitted():
    src = _frame()
    pkts = chunk_frame(src, 3, bytes(5))
    asm = FrameAssembler()
    results = [asm.feed(p) for i, p in enumerate(pkts) if i != 1]
    assert not any(results)
