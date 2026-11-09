"""Voice Activity Detection (VAD) module with 80Hz IIR filter and ST LIS25BA VPU fusion.

Adapted for Project PA:
- 80Hz IIR high-pass filter + DC blocker (ADR-006).
- Adaptive noise floor estimator with dual-rate EMA tracking.
- Multi-frame onset persistence & hangover bridging.
- ST LIS25BA bone-conduction vocal cord resonance fusion for whisper pickup (ADR-003).
"""

from __future__ import annotations
from typing import Any, Generator, List, Optional, Union
import numpy as np


class VoiceActivityDetector:
    """Voice Activity Detector evaluating strictly 30ms frames with adaptive noise floor,
    DC blocking, 80Hz IIR high-pass filter, and bone-conduction VPU whisper fusion.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        energy_threshold: Optional[float] = 300.0,
        snr_margin_db: float = 12.0,
        hangover_frames: int = 6,
        turn_completion_frames: int = 16,
        onset_frames: int = 2,
        min_noise_floor_dbfs: float = -90.0,
        max_noise_floor_dbfs: float = -20.0,
        initial_noise_floor_dbfs: float = -60.0,
        ducking_attenuation_db: float = 14.0,
        high_pass_cutoff_hz: float = 80.0,
        high_pass_r: float = 0.968,
        vpu_whisper_threshold: float = 0.35,
        fixed_threshold_dbfs: Optional[float] = None,
    ):
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.frame_size = int(sample_rate * (frame_duration_ms / 1000.0))
        self.energy_threshold = energy_threshold
        self.snr_margin_db = float(snr_margin_db)
        self.hangover_frames = int(hangover_frames)
        self.turn_completion_frames = int(turn_completion_frames)
        self.onset_frames = int(onset_frames)
        self.min_noise_floor_dbfs = float(min_noise_floor_dbfs)
        self.max_noise_floor_dbfs = float(max_noise_floor_dbfs)
        self.initial_noise_floor_dbfs = float(initial_noise_floor_dbfs)
        self.ducking_attenuation_db = float(ducking_attenuation_db)
        self.high_pass_cutoff_hz = float(high_pass_cutoff_hz)
        self.high_pass_r = float(high_pass_r)
        self.vpu_whisper_threshold = float(vpu_whisper_threshold)

        # Baseline fixed threshold converted to dBFS if specified
        self._fixed_threshold_dbfs: Optional[float] = None
        if fixed_threshold_dbfs is not None:
            self._fixed_threshold_dbfs = float(fixed_threshold_dbfs)
        elif energy_threshold is not None:
            eth = float(energy_threshold)
            if eth > 1.0:
                self._fixed_threshold_dbfs = float(20.0 * np.log10(eth / 32768.0))
            elif eth <= 0.0:
                self._fixed_threshold_dbfs = eth
            else:
                self._fixed_threshold_dbfs = float(20.0 * np.log10(eth))

        # Filter state for stateful 1st-order IIR high-pass filter: y[n] = x[n] - x[n-1] + R * y[n-1]
        self._prev_x = 0.0
        self._prev_y = 0.0

        # Sample accumulator FIFO
        self._fifo = np.empty(0, dtype=np.float32)

        # Adaptive state
        self.noise_floor_dbfs = float(initial_noise_floor_dbfs)
        self.threshold_dbfs = self.noise_floor_dbfs + self.snr_margin_db
        if self._fixed_threshold_dbfs is not None:
            self.threshold_dbfs = max(self.threshold_dbfs, self._fixed_threshold_dbfs)
        self.is_speech = False
        self.is_turn_complete = False
        self.hangover_count = 0
        self._consecutive_speech_frames = 0
        self._silence_frames = 0
        self._has_speech_occurred = False

        # VPU Whisper Fusion state
        self.is_whisper_active = False
        self.vpu_energy = 0.0

        # Acoustic Echo Suppression (AES) / Ducking state
        self._is_playback_active = False
        self._reference_ducking_threshold: Optional[float] = None

    @property
    def is_playback_active(self) -> bool:
        """Indicates whether speaker playback is currently active."""
        return self._is_playback_active

    def set_playback_active(self, active: bool, reference_signal: Optional[Any] = None) -> None:
        """Set acoustic echo suppression state to prevent self-triggering."""
        self._is_playback_active = bool(active)
        if active and reference_signal is not None:
            clean_ref = self._sanitize_audio(reference_signal)
            if len(clean_ref) > 0:
                ref_dbfs = self.compute_dbfs(clean_ref)
                leakage_est = ref_dbfs - 12.0
                self._reference_ducking_threshold = leakage_est + self.ducking_attenuation_db
            else:
                self._reference_ducking_threshold = None
        else:
            self._reference_ducking_threshold = None

    def reset(self) -> None:
        """Reset internal FIFO, DSP filter state, and speech detection counters."""
        self._fifo = np.empty(0, dtype=np.float32)
        self._prev_x = 0.0
        self._prev_y = 0.0
        self.noise_floor_dbfs = float(self.initial_noise_floor_dbfs)
        self.threshold_dbfs = self.noise_floor_dbfs + self.snr_margin_db
        if self._fixed_threshold_dbfs is not None:
            self.threshold_dbfs = max(self.threshold_dbfs, self._fixed_threshold_dbfs)
        self.is_speech = False
        self.is_turn_complete = False
        self.hangover_count = 0
        self._consecutive_speech_frames = 0
        self._silence_frames = 0
        self._has_speech_occurred = False
        self.is_whisper_active = False
        self.vpu_energy = 0.0
        self._is_playback_active = False
        self._reference_ducking_threshold = None

    def _sanitize_audio(self, chunk: Any) -> np.ndarray:
        """Validate, sanitize, downmix to mono, and normalize input audio to float32 [-1.0, 1.0]."""
        if chunk is None:
            return np.empty(0, dtype=np.float32)

        if isinstance(chunk, (bytes, bytearray)):
            nbytes = len(chunk)
            if nbytes % 2 != 0:
                chunk = chunk[:nbytes - (nbytes % 2)]
            if len(chunk) == 0:
                return np.empty(0, dtype=np.float32)
            arr = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
            return arr

        if not isinstance(chunk, np.ndarray):
            try:
                chunk = np.asarray(chunk)
            except Exception:
                return np.empty(0, dtype=np.float32)

        if chunk.size == 0:
            return np.empty(0, dtype=np.float32)

        if chunk.ndim > 1:
            if chunk.shape[0] < chunk.shape[1]:
                chunk = np.mean(chunk, axis=0)
            else:
                chunk = np.mean(chunk, axis=-1)

        chunk = chunk.flatten()
        chunk = np.nan_to_num(chunk, copy=True, nan=0.0, posinf=1.0, neginf=-1.0)

        if np.issubdtype(chunk.dtype, np.integer):
            chunk = chunk.astype(np.float32) / 32768.0
        else:
            chunk = chunk.astype(np.float32)
            max_abs = float(np.max(np.abs(chunk))) if len(chunk) > 0 else 0.0
            if max_abs > 1.5:
                chunk = chunk / 32768.0

        return chunk

    def _apply_high_pass_filter(self, samples: np.ndarray) -> np.ndarray:
        """Applies 80Hz IIR high-pass filter + DC blocker: y[n] = x[n] - x[n-1] + R * y[n-1]."""
        n = len(samples)
        if n == 0:
            return samples

        filtered = np.empty(n, dtype=np.float32)
        r = self.high_pass_r
        prev_x = self._prev_x
        prev_y = self._prev_y

        for i in range(n):
            curr_x = samples[i]
            curr_y = curr_x - prev_x + r * prev_y
            filtered[i] = curr_y
            prev_x = curr_x
            prev_y = curr_y

        self._prev_x = prev_x
        self._prev_y = prev_y
        return filtered

    def compute_dbfs(self, frame: np.ndarray) -> float:
        """Calculates RMS energy in dBFS relative to full scale 1.0."""
        if len(frame) == 0:
            return -100.0
        rms = np.sqrt(np.mean(frame ** 2))
        if not np.isfinite(rms) or rms < 1e-6:
            return -100.0
        return float(20.0 * np.log10(rms))

    def fuse_vpu_resonance(self, vpu_energy: float, confidence: float = 1.0) -> bool:
        """Fuses bone-conduction vocal cord resonance from ST LIS25BA VPU sensor.
        
        Whisper vocalizations directly vibrate cranial bone, bypassing airborne acoustic
        noise floor requirements.
        """
        self.vpu_energy = float(vpu_energy)
        if vpu_energy >= self.vpu_whisper_threshold and confidence > 0.5:
            self.is_whisper_active = True
            return True
        else:
            self.is_whisper_active = False
            return False

    def process(
        self,
        audio_chunk: Any,
        vpu_energy: Optional[float] = None,
        vpu_confidence: float = 1.0
    ) -> List[bool]:
        """Processes incoming audio through 30ms frame FIFO, IIR filtering, and VAD decision."""
        if vpu_energy is not None:
            self.fuse_vpu_resonance(vpu_energy, vpu_confidence)

        samples = self._sanitize_audio(audio_chunk)
        if len(samples) == 0:
            return []

        # Filter audio
        filtered = self._apply_high_pass_filter(samples)

        # Accumulate in FIFO
        self._fifo = np.concatenate((self._fifo, filtered))

        results: List[bool] = []
        while len(self._fifo) >= self.frame_size:
            frame = self._fifo[:self.frame_size]
            self._fifo = self._fifo[self.frame_size:]

            frame_dbfs = self.compute_dbfs(frame)
            is_frame_speech = self._evaluate_frame(frame_dbfs)
            results.append(is_frame_speech)

        return results

    def _evaluate_frame(self, frame_dbfs: float) -> bool:
        """Evaluates single 30ms frame against noise floor and VPU state."""
        # Acoustic ducking
        effective_threshold = self.threshold_dbfs
        if self._is_playback_active:
            if self._reference_ducking_threshold is not None:
                effective_threshold = max(effective_threshold, self._reference_ducking_threshold)
            else:
                effective_threshold += self.ducking_attenuation_db

        raw_acoustic_speech = frame_dbfs > effective_threshold

        # VPU bone-conduction override for whisper detection
        raw_speech = raw_acoustic_speech or self.is_whisper_active

        # Update noise floor (slow update during speech, fast during silence)
        if not raw_speech and not self._is_playback_active:
            alpha = 0.05
            self.noise_floor_dbfs = (1.0 - alpha) * self.noise_floor_dbfs + alpha * frame_dbfs
            self.noise_floor_dbfs = float(np.clip(self.noise_floor_dbfs, self.min_noise_floor_dbfs, self.max_noise_floor_dbfs))
            self.threshold_dbfs = self.noise_floor_dbfs + self.snr_margin_db
            if self._fixed_threshold_dbfs is not None:
                self.threshold_dbfs = max(self.threshold_dbfs, self._fixed_threshold_dbfs)
        elif not self._is_playback_active:
            alpha = 0.005
            self.noise_floor_dbfs = (1.0 - alpha) * self.noise_floor_dbfs + alpha * frame_dbfs
            self.noise_floor_dbfs = float(np.clip(self.noise_floor_dbfs, self.min_noise_floor_dbfs, self.max_noise_floor_dbfs))
            self.threshold_dbfs = self.noise_floor_dbfs + self.snr_margin_db
            if self._fixed_threshold_dbfs is not None:
                self.threshold_dbfs = max(self.threshold_dbfs, self._fixed_threshold_dbfs)

        # Onset persistence
        if raw_speech:
            self._consecutive_speech_frames += 1
            if self._consecutive_speech_frames >= self.onset_frames or self.is_whisper_active:
                self.is_speech = True
                self._has_speech_occurred = True
                self.hangover_count = self.hangover_frames
                self._silence_frames = 0
                self.is_turn_complete = False
        else:
            self._consecutive_speech_frames = 0
            if self.hangover_count > 0:
                self.hangover_count -= 1
                self.is_speech = True
            else:
                self.is_speech = False
                if self._has_speech_occurred:
                    self._silence_frames += 1
                    if self._silence_frames >= self.turn_completion_frames:
                        self.is_turn_complete = True
                        self._has_speech_occurred = False

        return self.is_speech
