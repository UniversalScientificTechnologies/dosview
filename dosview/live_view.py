"""Live-view helpers for serial event processing and circular buffering."""

from __future__ import annotations

import re
import time
from typing import List, Optional, Tuple

import numpy as np

try:
    import serial
    from serial.tools import list_ports
except Exception:
    serial = None
    list_ports = None

CHANNEL_ALIASES = {
    "0": 0,
    "r": 0,
    "red": 0,
    "cerveny": 0,
    "ch0": 0,
    "1": 1,
    "b": 1,
    "blue": 1,
    "modry": 1,
    "ch1": 1,
}


def serial_available() -> bool:
    return serial is not None and list_ports is not None


def list_serial_ports() -> List[str]:
    if not serial_available():
        return []
    return [port.device for port in list_ports.comports()]


def _parse_channel(token: str) -> Optional[int]:
    key = token.strip().lower()
    if key in CHANNEL_ALIASES:
        return CHANNEL_ALIASES[key]
    if key.isdigit() and int(key) in (0, 1):
        return int(key)
    return None


def _parse_bin(token: str, bins_count: int) -> Optional[int]:
    try:
        value = int(float(token))
    except ValueError:
        return None
    if 0 <= value < bins_count:
        return value
    return None


def _parse_timestamp(token: str) -> Optional[float]:
    try:
        return float(token)
    except ValueError:
        return None


def parse_serial_event_line(
    line: str,
    bins_count: int = 1024,
    fallback_timestamp: Optional[float] = None,
) -> Optional[Tuple[float, int, int]]:
    """Parse a single serial line into (timestamp, channel, bin)."""
    if fallback_timestamp is None:
        fallback_timestamp = time.time()

    stripped = line.strip()
    if not stripped:
        return None

    tokens = [part for part in re.split(r"[,;\s]+", stripped) if part]
    if not tokens:
        return None

    if tokens[0].startswith("$"):
        tokens = tokens[1:]
    if tokens and tokens[0].upper() == "E":
        tokens = tokens[1:]
    if len(tokens) < 2:
        return None

    ts = fallback_timestamp
    channel = None
    energy_bin = None

    # Prefer the canonical format: ts,channel,bin
    if len(tokens) >= 3:
        maybe_ts = _parse_timestamp(tokens[0])
        maybe_ch = _parse_channel(tokens[1])
        maybe_bin = _parse_bin(tokens[2], bins_count)
        if maybe_ch is not None and maybe_bin is not None:
            ts = maybe_ts if maybe_ts is not None else fallback_timestamp
            return (ts, maybe_ch, maybe_bin)

    # Fallback: channel,bin (local timestamp)
    maybe_ch = _parse_channel(tokens[0])
    maybe_bin = _parse_bin(tokens[1], bins_count) if len(tokens) > 1 else None
    if maybe_ch is not None and maybe_bin is not None:
        return (fallback_timestamp, maybe_ch, maybe_bin)

    # Fallback: ts,bin,channel
    if len(tokens) >= 3:
        maybe_ts = _parse_timestamp(tokens[0])
        maybe_bin = _parse_bin(tokens[1], bins_count)
        maybe_ch = _parse_channel(tokens[2])
        if maybe_bin is not None and maybe_ch is not None:
            ts = maybe_ts if maybe_ts is not None else fallback_timestamp
            return (ts, maybe_ch, maybe_bin)

    return None


class LiveCircularBuffer:
    """Per-second circular storage for two-channel spectral events."""

    def __init__(self, seconds_capacity: int = 300, bins_count: int = 1024):
        self.seconds_capacity = max(3, int(seconds_capacity))
        self.bins_count = max(8, int(bins_count))
        self.slot_seconds = np.full(self.seconds_capacity, -1, dtype=np.int64)
        self.slot_hist = np.zeros((self.seconds_capacity, 2, self.bins_count), dtype=np.int32)
        self.slot_counts = np.zeros((self.seconds_capacity, 2), dtype=np.int32)

    def add_event(self, timestamp: float, channel: int, energy_bin: int) -> None:
        if channel not in (0, 1):
            return
        if energy_bin < 0 or energy_bin >= self.bins_count:
            return

        sec = int(timestamp)
        slot = sec % self.seconds_capacity
        if self.slot_seconds[slot] != sec:
            self.slot_seconds[slot] = sec
            self.slot_hist[slot, :, :] = 0
            self.slot_counts[slot, :] = 0

        self.slot_hist[slot, channel, energy_bin] += 1
        self.slot_counts[slot, channel] += 1

    def _iter_recent_slots(self, seconds: int):
        now_sec = int(time.time())
        window = max(1, min(int(seconds), self.seconds_capacity))
        start_sec = now_sec - window + 1
        for sec in range(start_sec, now_sec + 1):
            slot = sec % self.seconds_capacity
            if self.slot_seconds[slot] == sec:
                yield slot

    def get_histogram(self, seconds: int, channel: Optional[int] = None) -> np.ndarray:
        out = np.zeros(self.bins_count, dtype=np.int32)
        for slot in self._iter_recent_slots(seconds):
            if channel is None:
                out += self.slot_hist[slot, 0, :] + self.slot_hist[slot, 1, :]
            else:
                out += self.slot_hist[slot, channel, :]
        return out

    def get_channel_counts(self, seconds: int) -> np.ndarray:
        counts = np.zeros(2, dtype=np.int32)
        for slot in self._iter_recent_slots(seconds):
            counts += self.slot_counts[slot, :]
        return counts

    def get_spectrogram(self, seconds: int) -> np.ndarray:
        window = max(1, min(int(seconds), self.seconds_capacity))
        matrix = np.zeros((window, self.bins_count), dtype=np.int32)
        now_sec = int(time.time())
        start_sec = now_sec - window + 1
        row = 0
        for sec in range(start_sec, now_sec + 1):
            slot = sec % self.seconds_capacity
            if self.slot_seconds[slot] == sec:
                matrix[row, :] = self.slot_hist[slot, 0, :] + self.slot_hist[slot, 1, :]
            row += 1
        return matrix

    def get_recent_3x3_grid(self) -> np.ndarray:
        grid = np.zeros((3, 3), dtype=np.int32)
        now_sec = int(time.time())
        for i in range(9):
            sec = now_sec - (8 - i)
            slot = sec % self.seconds_capacity
            if self.slot_seconds[slot] == sec:
                value = int(self.slot_counts[slot, 0] + self.slot_counts[slot, 1])
            else:
                value = 0
            grid[i // 3, i % 3] = value
        return grid


__all__ = [
    "LiveCircularBuffer",
    "list_serial_ports",
    "parse_serial_event_line",
    "serial",
    "serial_available",
]
