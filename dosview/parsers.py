"""Parsers for different dosview log formats.

This module isolates the parsing logic from the GUI stack so that it can be
imported and tested without initializing PyQt.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import time
from pathlib import Path

import numpy as np


class BaseLogParser:
    """Base parser class."""

    def __init__(self, file_path: str | Path):
        self.file_path = str(file_path)

    @staticmethod
    def detect(file_path: str | Path) -> bool:
        """Return True if this parser can handle the supplied file."""
        raise NotImplementedError

    def parse(self):  # pragma: no cover - concrete classes implement
        raise NotImplementedError


def strip_optional_timestamp_prefix(line: str) -> tuple[str, str | None]:
    """Return the payload without an optional ``@ISO8601,`` prefix."""
    stripped = line.strip()
    if not stripped:
        return "", None
    if stripped.startswith("@"):
        timestamp, separator, payload = stripped.partition(",")
        if separator and payload:
            return payload, timestamp[1:]
    return stripped, None


def build_cached_delta_histogram(
    events: Sequence[Tuple[int, int, int, int, int]],
    primary_index: int,
    secondary_index: int,
):
    """Build a cached 2D histogram for ``primary`` vs ``primary-secondary``."""
    if not events:
        return {
            "matrix": np.zeros((0, 0), dtype=int),
            "x_max": 0,
            "delta_min": 0,
            "delta_max": 0,
        }

    primary_values = [event[primary_index] for event in events]
    delta_values = [event[primary_index] - event[secondary_index] for event in events]

    x_max = max(primary_values)
    delta_min = min(delta_values)
    delta_max = max(delta_values)
    matrix = np.zeros((x_max + 1, delta_max - delta_min + 1), dtype=int)

    for primary_value, delta_value in zip(primary_values, delta_values):
        matrix[primary_value, delta_value - delta_min] += 1

    return {
        "matrix": matrix,
        "x_max": int(x_max),
        "delta_min": int(delta_min),
        "delta_max": int(delta_max),
    }


class CoincidenceLogParser(BaseLogParser):
    """Parser for coincidence logs with ``$C`` records."""

    @staticmethod
    def detect(file_path: str | Path) -> bool:
        with open(file_path, "r") as f:
            for line in f:
                payload, _timestamp = strip_optional_timestamp_prefix(line)
                if payload.startswith("$C,"):
                    return True
        return False

    def parse(self):
        start_time = time.time()
        events: List[Tuple[int, int, int, int, int]] = []
        timestamped_lines = 0
        first_timestamp = None
        last_timestamp = None
        metadata = {
            "log_runs_count": 0,
            "log_device_info": {},
            "log_info": {},
        }
        type_counts = {0: 0, 1: 0, 2: 0, 3: 0}
        max_channel = 0

        with open(self.file_path, "r") as file:
            for line in file:
                payload, timestamp = strip_optional_timestamp_prefix(line)
                if not payload:
                    continue

                if timestamp is not None:
                    timestamped_lines += 1
                    if first_timestamp is None:
                        first_timestamp = timestamp
                    last_timestamp = timestamp

                parts = payload.split(",")
                record_type = parts[0]

                if record_type == "$DOS" and len(parts) >= 8:
                    metadata["log_device_info"]["DOS"] = {
                        "type": parts[0],
                        "hw-model": parts[1],
                        "fw-version": parts[2],
                        "eeprom": parts[3],
                        "fw-commit": parts[4],
                        "fw-build_info": parts[5],
                        "hw-sn": parts[6].strip(),
                        "payload": parts[7].strip(),
                    }
                    metadata["log_runs_count"] += 1
                    continue

                if record_type != "$C" or len(parts) < 6:
                    continue

                try:
                    coincidence_type = int(parts[1])
                    val0 = int(parts[2])
                    val0b = int(parts[3])
                    val1 = int(parts[4])
                    val1b = int(parts[5])
                except ValueError:
                    continue

                events.append((coincidence_type, val0, val0b, val1, val1b))
                type_counts[coincidence_type] = type_counts.get(coincidence_type, 0) + 1
                max_channel = max(max_channel, val0, val0b, val1, val1b)

        bins_count = max_channel + 1 if events else 1
        histograms = {
            "val0": np.zeros(bins_count, dtype=int),
            "val0b": np.zeros(bins_count, dtype=int),
            "val1": np.zeros(bins_count, dtype=int),
            "val1b": np.zeros(bins_count, dtype=int),
        }

        for _coincidence_type, val0, val0b, val1, val1b in events:
            histograms["val0"][val0] += 1
            histograms["val0b"][val0b] += 1
            histograms["val1"][val1] += 1
            histograms["val1b"][val1b] += 1

        delta_histograms = {
            "val0": build_cached_delta_histogram(events, primary_index=1, secondary_index=2),
            "val1": build_cached_delta_histogram(events, primary_index=3, secondary_index=4),
        }

        metadata["log_info"].update(
            {
                "log_type": "COINCIDENCE",
                "log_type_version": "1.0",
                "records_total": len(events),
                "histogram_channels": bins_count,
                "max_channel": int(max_channel),
                "timestamped_lines": int(timestamped_lines),
                "first_timestamp": first_timestamp or "",
                "last_timestamp": last_timestamp or "",
                "coincidence_type_counts": {str(key): int(value) for key, value in type_counts.items()},
            }
        )
        print("Parsed COINCIDENCE format in", time.time() - start_time, "s")

        return {
            "events": events,
            "histograms": histograms,
            "delta_histograms": delta_histograms,
            "metadata": metadata,
        }


class Airdos04CLogParser(BaseLogParser):
    """Parser for AIRDOS04C log files."""

    @staticmethod
    def detect(file_path: str | Path) -> bool:
        with open(file_path, "r") as f:
            for line in f:
                if line.startswith("$DOS") and "AIRDOS04C" in line:
                    return True
        return False

    def parse(self):
        start_time = time.time()
        print("AIRDOS04C parser start")
        metadata = {
            "log_runs_count": 0,
            "log_device_info": {},
            "log_info": {},
        }
        hist = np.zeros(1024, dtype=int)
        total_counts = 0
        sums: List[int] = []
        time_axis: List[float] = []
        inside_run = False
        current_hist = None
        current_counts = 0

        with open(self.file_path, "r") as file:
            for line in file:
                parts = line.strip().split(",")
                match parts[0]:
                    case "$DOS":
                        metadata["log_device_info"]["DOS"] = {
                            "type": parts[0],
                            "hw-model": parts[1],
                            "fw-version": parts[2],
                            "eeprom": parts[3],
                            "fw-commit": parts[4],
                            "fw-build_info": parts[5],
                            "hw-sn": parts[6].strip(),
                        }
                        metadata["log_runs_count"] += 1
                    case "$START":
                        inside_run = True
                        current_hist = np.zeros_like(hist)
                        current_counts = 0
                    case "$E":
                        if inside_run and len(parts) >= 3:
                            channel = int(parts[2])
                            if 0 <= channel < current_hist.shape[0]:
                                current_hist[channel] += 1
                                current_counts += 1
                    case "$STOP":
                        if inside_run:
                            if len(parts) > 4:
                                for idx, val in enumerate(parts[4:]):
                                    try:
                                        current_hist[idx] += int(val)
                                    except ValueError:
                                        continue
                            hist += current_hist
                            total_counts += current_counts
                            sums.append(current_counts)
                            time_axis.append(float(parts[2]))
                        inside_run = False
                        current_hist = None
                    case _:
                        continue

        metadata["log_info"]["histogram_channels"] = hist.shape[0]
        metadata["log_info"]["events_total"] = int(total_counts)
        metadata["log_info"]["log_type_version"] = "2.0"
        metadata["log_info"]["log_type"] = "xDOS_SPECTRAL"
        metadata["log_info"]["detector_type"] = "AIRDOS04C"
        print("Parsed AIRDOS04C format in", time.time() - start_time, "s")

        return [np.array(time_axis), np.array(sums), hist, metadata]


class OldLogParser(BaseLogParser):
    """Parser for legacy (pre-AIRDOS04C) log files."""

    @staticmethod
    def detect(file_path: str | Path) -> bool:
        with open(file_path, "r") as f:
            for line in f:
                if line.startswith("$DOS") and "AIRDOS04C" not in line:
                    return True
                if line.startswith("$AIRDOS"):
                    return True
                if line.startswith("$HIST"):
                    return True
        return False

    def parse(self):
        start_time = time.time()
        print("OLD parser start")
        metadata = {
            "log_runs_count": 0,
            "log_device_info": {},
            "log_info": {},
        }
        df_lines: List[Sequence[str]] = []
        df_metadata: List[Sequence[str]] = []
        unique_events: List[Tuple[float, int]] = []
        with open(self.file_path, "r") as file:
            for line in file:
                parts = line.strip().split(",")
                match parts[0]:
                    case "$DOS":
                        metadata["log_device_info"]["DOS"] = {
                            "type": parts[0],
                            "hw-model": parts[1],
                            "fw-version": parts[2],
                            "eeprom": parts[3],
                            "fw-commit": parts[4],
                            "fw-build_info": parts[5],
                            "hw-sn": parts[6].strip(),
                        }
                        metadata["log_runs_count"] += 1
                    case "$AIRDOS":
                        metadata["log_device_info"]["AIRDOS"] = {
                            "type": parts[0],
                            "hw-model": parts[1] if len(parts) > 1 else "",
                            "detector": parts[2] if len(parts) > 2 else "",
                            "hw-sn": parts[3].strip() if len(parts) > 3 else "",
                        }
                        metadata["log_runs_count"] += 1
                    case "$ENV":
                        df_metadata.append(parts[2:])
                    case "$HIST":
                        df_lines.append(parts[1:])
                    case "$HITS":
                        for i in range(2, len(parts) - 1, 2):
                            try:
                                unique_events.append((float(parts[i]), int(parts[i + 1])))
                            except ValueError:
                                continue
                    case _:
                        continue
        if not df_lines:
            raise ValueError("Soubor neobsahuje žádné záznamy $HIST pro starší log.")
        np_spectrum = np.array(df_lines, dtype=float)
        zero_columns = np.zeros((np_spectrum.shape[0], 1000))
        np_spectrum = np.hstack((np_spectrum, zero_columns))
        time_column = np_spectrum[:, 1]
        np_spectrum = np_spectrum[:, 7:]
        for event in unique_events:
            t, ch = event
            time_index = np.searchsorted(time_column, t)
            if 0 <= time_index < np_spectrum.shape[0] and 0 <= ch < np_spectrum.shape[1]:
                np_spectrum[time_index, ch] += 1
        hist = np.sum(np_spectrum[:, 1:], axis=0)
        sums = np.sum(np_spectrum[:, 1:], axis=1)
        metadata["log_info"].update(
            {
                "internal_time_min": float(time_column.min()),
                "internal_time_max": float(time_column.max()),
                "log_duration": float(time_column.max() - time_column.min()),
                "spectral_count": int(sums.shape[0]),
                "channels": int(hist.shape[0]),
                "hits_count": len(unique_events),
                "log_type_version": "1.0",
                "log_type": "xDOS_SPECTRAL",
                "detector_type": metadata["log_device_info"].get("DOS", {}).get(
                    "hw-model",
                    metadata["log_device_info"].get("AIRDOS", {}).get("hw-model", "unknown"),
                ),
            }
        )
        print("Parsed OLD format in", time.time() - start_time, "s")
        return [time_column, sums, hist, metadata]


LOG_PARSERS: Sequence[type[BaseLogParser]] = [CoincidenceLogParser, Airdos04CLogParser, OldLogParser]


def get_parser_for_file(file_path: str | Path) -> BaseLogParser:
    for parser_cls in LOG_PARSERS:
        if parser_cls.detect(file_path):
            return parser_cls(file_path)
    raise ValueError("Neznámý typ logu nebo žádný vhodný parser.")


def parse_file(file_path: str | Path):
    parser = get_parser_for_file(file_path)
    return parser.parse()


__all__ = [
    "BaseLogParser",
    "CoincidenceLogParser",
    "build_cached_delta_histogram",
    "Airdos04CLogParser",
    "OldLogParser",
    "strip_optional_timestamp_prefix",
    "get_parser_for_file",
    "parse_file",
]
