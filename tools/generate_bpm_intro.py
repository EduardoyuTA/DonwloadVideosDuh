from __future__ import annotations

import math
import random
import wave
from array import array
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT_DIR / "assets" / "audio" / "bpm75_intro.wav"

SAMPLE_RATE = 44100
CHANNELS = 2
BPM = 75
BEAT_COUNT = 4
BEAT_INTERVAL = 60.0 / BPM
TOTAL_DURATION = BEAT_INTERVAL * BEAT_COUNT


def soft_clip(value: float) -> float:
    return math.tanh(value)


def beat_sample(time_offset: float, *, accent: bool) -> float:
    if time_offset < 0.0 or time_offset > 0.2:
        return 0.0

    click_decay = math.exp(-34.0 * time_offset)
    tone_decay = math.exp(-18.0 * time_offset)
    body_decay = math.exp(-10.0 * time_offset)

    transient_noise = (random.uniform(-1.0, 1.0) * 0.22) * click_decay
    stick_tone = math.sin(2.0 * math.pi * 1480.0 * time_offset) * click_decay
    rim_tone = math.sin(2.0 * math.pi * 980.0 * time_offset) * tone_decay * 0.68
    drum_body = math.sin(2.0 * math.pi * 215.0 * time_offset) * body_decay * 0.4
    wood_resonance = math.sin(2.0 * math.pi * 430.0 * time_offset) * body_decay * 0.22

    envelope = math.exp(-6.5 * time_offset)
    accent_gain = 1.08 if accent else 1.0

    mixed = (
        transient_noise * 0.15
        + stick_tone * 0.58
        + rim_tone * 0.34
        + drum_body * 0.26
        + wood_resonance * 0.18
    ) * envelope * accent_gain
    return soft_clip(mixed * 1.02)


def build_intro() -> array[int]:
    frame_count = int(TOTAL_DURATION * SAMPLE_RATE)
    frames = array("h", [0] * (frame_count * CHANNELS))

    beat_starts = [beat_index * BEAT_INTERVAL for beat_index in range(BEAT_COUNT)]

    for frame_index in range(frame_count):
        current_time = frame_index / SAMPLE_RATE
        sample_value = 0.0

        for beat_index, beat_start in enumerate(beat_starts):
            sample_value += beat_sample(
                current_time - beat_start,
                accent=beat_index == 0,
            )

        pcm_value = int(max(-1.0, min(1.0, sample_value)) * 32767)
        left = frame_index * CHANNELS
        right = left + 1
        frames[left] = pcm_value
        frames[right] = pcm_value

    return frames


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frames = build_intro()

    with wave.open(str(OUTPUT_PATH), "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(frames.tobytes())

    print(f"Arquivo gerado em: {OUTPUT_PATH}")
    print(f"Duracao: {TOTAL_DURATION:.3f}s")


if __name__ == "__main__":
    main()
