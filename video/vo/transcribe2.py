"""Word-level transcripts for the Part C voiceovers -> vo/real/<name>_words.json."""
import json
import sys

import soundfile as sf
from faster_whisper import WhisperModel

model = WhisperModel("medium.en", device="cpu", compute_type="int8")
for name in sys.argv[1:]:
    audio, _ = sf.read(f"vo/real/{name}16k.wav", dtype="float32")
    segs, _ = model.transcribe(audio, word_timestamps=True, beam_size=5)
    words = []
    print("==", name)
    for s in segs:
        words += [{"w": w.word.strip(), "s": round(w.start, 2), "e": round(w.end, 2)} for w in s.words]
        print(f"{s.start:6.2f} {s.end:6.2f} {s.text.strip()}")
    json.dump(words, open(f"vo/real/{name}_words.json", "w"), indent=0)
