"""Thread-safe circular ring buffer for real-time PCM audio streaming.

Adapted for Project PA with:
- Sub-0.05ms atomic drain with 2ms half-cosine micro-fadeout to eliminate step discontinuities (ADR-006).
- Zero-allocation read_into for real-time audio playback callbacks.
- Generation fencing against stale/zombie audio re-injection during barge-in interruptions.
- Monotonic playhead tracking.
"""

from __future__ import annotations
import threading
from typing import Any, Optional, Union
import numpy as np


class AudioRingBuffer:
    """Thread-safe circular ring buffer for real-time PCM audio streaming."""

    def __init__(self, capacity_samples: int = 48000 * 5, sample_rate: int = 24000):
        if capacity_samples <= 0:
            raise ValueError(f"capacity_samples must be positive, got {capacity_samples}")
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")

        self.capacity = capacity_samples
        self.sample_rate = sample_rate
        self.buffer = np.zeros(capacity_samples, dtype=np.int16)
        self.read_pos = 0
        self.write_pos = 0
        self.size = 0
        self.generation = 0
        self.total_samples_played = 0
        self.fadeout_tail: Optional[np.ndarray] = None
        self.lock = threading.Lock()

    @property
    def available_write(self) -> int:
        """Remaining capacity available for writing."""
        with self.lock:
            return self.capacity - self.size

    def available_read(self) -> int:
        """Number of narrative audio samples currently queued in the ring buffer."""
        with self.lock:
            return self.size

    @property
    def playhead_seconds(self) -> float:
        """Monotonic playhead progress in seconds."""
        with self.lock:
            return self.total_samples_played / self.sample_rate

    def get_playhead_seconds(self) -> float:
        """Compatibility accessor for playhead progress in seconds."""
        return self.playhead_seconds

    def reset_playhead(self) -> None:
        """Explicitly reset the monotonic playhead counter."""
        with self.lock:
            self.total_samples_played = 0

    def is_actively_playing(self) -> bool:
        """Returns True if any audio or fadeout tail is queued for output."""
        with self.lock:
            return self.size > 0 or (self.fadeout_tail is not None and len(self.fadeout_tail) > 0)

    def write(self, data: Union[np.ndarray, bytes, bytearray, memoryview], generation: Optional[int] = None) -> int:
        """Write audio into circular buffer with generation fencing and format normalization.

        - Converts bytes, bytearray, memoryview, and numpy arrays to 1D int16.
        - Downmixes 2D (N, 1) and (N, 2) arrays to 1D mono.
        - Scales normalized floats in [-1.0, 1.0] by 32767.0 and clips.
        - Clips integer inputs to [-32768, 32767].
        - Rejects stale writes where generation != self.generation.
        """
        if data is None:
            return 0

        # 1. Type normalization to numpy array
        if isinstance(data, (bytes, bytearray)):
            nbytes = len(data)
            if nbytes % 2 != 0:
                data = data[:nbytes - (nbytes % 2)]
            if len(data) == 0:
                return 0
            arr = np.frombuffer(data, dtype=np.int16)
        elif isinstance(data, memoryview):
            if data.format in ('B', 'b', 'c') or data.itemsize == 1:
                nbytes = len(data)
                if nbytes % 2 != 0:
                    data = data[:nbytes - (nbytes % 2)]
                if len(data) == 0:
                    return 0
                arr = np.frombuffer(data, dtype=np.int16)
            else:
                arr = np.asarray(data)
        elif isinstance(data, np.ndarray):
            arr = data
        else:
            arr = np.asarray(data)

        if arr.size == 0:
            return 0

        # 2. Downmix 2D inputs to 1D mono
        if arr.ndim == 2:
            if arr.shape[1] == 1:
                arr = arr[:, 0]
            elif arr.shape[0] == 1 and arr.shape[1] > 2:
                arr = arr[0, :]
            elif arr.shape[1] == 2:
                if np.issubdtype(arr.dtype, np.floating):
                    arr = 0.5 * (arr[:, 0] + arr[:, 1])
                else:
                    arr = (arr[:, 0].astype(np.int64) + arr[:, 1].astype(np.int64)) // 2
            else:
                if np.issubdtype(arr.dtype, np.floating):
                    arr = np.mean(arr, axis=1)
                else:
                    arr = np.mean(arr.astype(np.float64), axis=1)
        elif arr.ndim > 2:
            arr = arr.reshape(-1)

        # 3. Clean NaNs/Infs, scale float to int16, clip integer ranges
        if np.issubdtype(arr.dtype, np.floating):
            arr = np.nan_to_num(arr, copy=True, nan=0.0, posinf=1.0, neginf=-1.0)
            arr = np.clip(np.round(arr * 32767.0), -32768.0, 32767.0).astype(np.int16)
        elif arr.dtype != np.int16:
            arr = np.clip(arr, -32768, 32767).astype(np.int16)
        elif not arr.flags.contiguous:
            arr = np.ascontiguousarray(arr)

        length = len(arr)
        if length == 0:
            return 0

        # 4. Ring buffer write under lock
        with self.lock:
            if generation is not None and generation != self.generation:
                return 0

            available_space = self.capacity - self.size
            if length > available_space:
                length = available_space
                arr = arr[:length]
            if length == 0:
                return 0

            end1 = min(length, self.capacity - self.write_pos)
            self.buffer[self.write_pos : self.write_pos + end1] = arr[:end1]
            end2 = length - end1
            if end2 > 0:
                self.buffer[0:end2] = arr[end1:length]

            self.write_pos = (self.write_pos + length) % self.capacity
            self.size += length
            return length

    def drain(self, fade_ms: float = 2.0) -> None:
        """Instantaneously drop all pending audio with 2ms half-cosine micro-fadeout (< 5ms).

        Increments generation fence to invalidate in-flight TTS chunks.
        Extracts up to 2ms of audio from the read position, attenuates via a half-cosine
        window to 0 amplitude, and stores in fadeout_tail to eliminate DAC step-discontinuity clicks.
        """
        with self.lock:
            self.generation += 1
            fade_samples = min(int(round(self.sample_rate * (fade_ms / 1000.0))), self.size)
            if fade_samples > 0:
                end1 = min(fade_samples, self.capacity - self.read_pos)
                raw = np.empty(fade_samples, dtype=np.int16)
                raw[:end1] = self.buffer[self.read_pos : self.read_pos + end1]
                end2 = fade_samples - end1
                if end2 > 0:
                    raw[end1:] = self.buffer[0:end2]

                if fade_samples > 1:
                    t = np.linspace(0.0, np.pi, fade_samples, endpoint=True)
                    window = 0.5 * (1.0 + np.cos(t))
                    self.fadeout_tail = np.round(raw * window).astype(np.int16)
                else:
                    self.fadeout_tail = np.zeros(1, dtype=np.int16)
            else:
                self.fadeout_tail = None

            self.read_pos = 0
            self.write_pos = 0
            self.size = 0

    def read_into(self, outdata: np.ndarray) -> int:
        """Zero-allocation read directly into audio callback buffer outdata.

        Zero-pads any buffer underrun deficit.
        Consumes micro-fadeout tail first if available.
        Updates monotonic playhead tracking.
        Supports both 1D and 2D (mono/stereo callback) arrays.
        Returns the number of valid audio samples written.
        """
        if outdata is None or not isinstance(outdata, np.ndarray):
            return 0
        samples_requested = outdata.shape[0] if outdata.ndim > 0 else 0
        if samples_requested <= 0:
            return 0

        def _assign_out(start: int, end: int, data: np.ndarray) -> None:
            if outdata.ndim == 1:
                outdata[start:end] = data
            elif outdata.ndim == 2:
                outdata[start:end, :] = data[:, None]
            else:
                outdata[start:end] = data.reshape(end - start, *outdata.shape[1:])

        def _zero_out(start: int, end: int) -> None:
            if outdata.ndim == 1:
                outdata[start:end] = 0
            elif outdata.ndim == 2:
                outdata[start:end, :] = 0
            else:
                outdata[start:end] = 0

        with self.lock:
            samples_written = 0

            # 1. Drain micro-fadeout tail if present
            if self.fadeout_tail is not None and len(self.fadeout_tail) > 0:
                tail_len = len(self.fadeout_tail)
                to_copy = min(tail_len, samples_requested)
                _assign_out(0, to_copy, self.fadeout_tail[:to_copy])
                samples_written += to_copy

                if to_copy < tail_len:
                    self.fadeout_tail = self.fadeout_tail[to_copy:]
                else:
                    self.fadeout_tail = None

                self.total_samples_played += to_copy
                if samples_written == samples_requested:
                    return samples_written

            # 2. Read narrative audio from ring buffer
            remaining_needed = samples_requested - samples_written
            samples_to_read = min(remaining_needed, self.size)

            if samples_to_read > 0:
                end1 = min(samples_to_read, self.capacity - self.read_pos)
                _assign_out(samples_written, samples_written + end1, self.buffer[self.read_pos : self.read_pos + end1])
                end2 = samples_to_read - end1
                if end2 > 0:
                    _assign_out(samples_written + end1, samples_written + samples_to_read, self.buffer[0:end2])

                self.read_pos = (self.read_pos + samples_to_read) % self.capacity
                self.size -= samples_to_read
                samples_written += samples_to_read
                self.total_samples_played += samples_to_read

            # 3. Zero-pad any underrun deficit
            if samples_written < samples_requested:
                _zero_out(samples_written, samples_requested)

            return samples_written

    def read(self, samples: int) -> np.ndarray:
        """Convenience method to read audio as a newly allocated numpy array."""
        out = np.zeros(samples, dtype=np.int16)
        self.read_into(out)
        return out
