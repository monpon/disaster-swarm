"""Word-level transcript of the recorded narration -> vo/real/words.json."""
import json
import sys

import soundfile as sf
from faster_whisper import WhisperModel

src = sys.argv[1] if len(sys.argv) > 1 else "vo/real/narration16k.wav"
# Pass samples directly: the bundled PyAV build rejects faster-whisper's open() args.
audio, _ = sf.read(src, dtype="float32")
model = WhisperModel("medium.en", device="cpu", compute_type="int8")
segs, _ = model.transcribe(audio, word_timestamps=True, vad_filter=False, beam_size=5)
words = []
for s in segs:
    for w in s.words:
        words.append({"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)})
    print(f"{s.start:7.2f} {s.end:7.2f} {s.text.strip()}")
json.dump(words, open("vo/real/words.json", "w"), indent=0)
