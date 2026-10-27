"""Outils audio partagés : mesure de durée, concaténation avec pauses, écriture WAV."""
from __future__ import annotations

import struct
import wave
from pathlib import Path

from ..render.ffmpeg import ffmpeg_bin, probe_duration, run
from .base import Segment, TTSResult


def write_wav(path: Path, samples, sample_rate: int) -> None:
    """Écrit des échantillons float (-1..1) en WAV mono 16 bits, sans dépendance numpy."""
    ints = [max(-32767, min(32767, int(float(s) * 32767))) for s in samples]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{len(ints)}h", *ints))


def assemble(parts: list[Path], sentences: list[str], out_path: Path, pause_s: float,
             provider: str) -> TTSResult:
    """Concatène les fichiers audio (un par phrase) avec une pause entre chaque ; timings exacts."""
    if len(parts) != len(sentences):
        raise ValueError("un fichier audio par phrase est attendu")
    durations = [probe_duration(p) for p in parts]
    segments: list[Segment] = []
    t = 0.0
    for text, d in zip(sentences, durations, strict=True):
        segments.append(Segment(text=text, start=round(t, 3), end=round(t + d, 3)))
        t += d + pause_s
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    chain = "".join(
        f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,"
        f"apad=pad_dur={pause_s}[a{i}];"
        for i in range(len(parts))
    )
    chain += "".join(f"[a{i}]" for i in range(len(parts)))
    chain += f"concat=n={len(parts)}:v=0:a=1[out]"
    cmd += ["-filter_complex", chain, "-map", "[out]", "-c:a", "aac", "-b:a", "128k", str(out_path)]
    run(cmd)
    total = probe_duration(out_path)
    return TTSResult(audio_path=out_path, duration_s=total, segments=segments, provider=provider,
                     synthetic=True)
