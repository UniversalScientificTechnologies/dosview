from pathlib import Path
import importlib.util

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
PARSERS_PATH = ROOT / "dosview" / "parsers.py"

spec = importlib.util.spec_from_file_location("dosview_parsers", PARSERS_PATH)
parsers = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(parsers)

LOG_PARSERS = parsers.LOG_PARSERS
get_parser_for_file = parsers.get_parser_for_file
parse_file = parsers.parse_file

DATA_DIR = ROOT / "data"

if not DATA_DIR.exists():
    pytest.skip("Data fixture directory is missing", allow_module_level=True)

LOG_FIXTURES = sorted(
    path
    for path in DATA_DIR.iterdir()
    if path.is_file() and not path.name.startswith(".")
)

if not LOG_FIXTURES:
    pytest.skip("No data fixtures found for parser tests", allow_module_level=True)


@pytest.mark.parametrize("log_path", LOG_FIXTURES, ids=lambda p: p.name)
def test_any_parser_detects_fixture(log_path):
    assert log_path.exists(), f"Fixture {log_path.name} is missing"
    detected = [parser for parser in LOG_PARSERS if parser.detect(log_path)]
    assert detected, f"No parser detected {log_path.name}"
    parser_instance = get_parser_for_file(log_path)
    assert any(isinstance(parser_instance, parser_cls) for parser_cls in detected)


@pytest.mark.parametrize("log_path", LOG_FIXTURES, ids=lambda p: p.name)
def test_parse_fixture_returns_consistent_shapes(log_path):
    time_axis, sums, hist, metadata = parse_file(log_path)

    for array in (time_axis, sums, hist):
        np_array = np.asarray(array, dtype=float)
        assert np_array.ndim == 1
        assert np_array.size > 0
        assert np.all(np.isfinite(np_array))

    assert time_axis.shape[0] == sums.shape[0]
    assert hist.shape[0] > 0
    assert np.all(np.asarray(hist) >= 0)

    if time_axis.shape[0] > 1:
        assert np.all(np.diff(np.asarray(time_axis, dtype=float)) >= 0)

    assert isinstance(metadata, dict)
    assert "log_info" in metadata and isinstance(metadata["log_info"], dict)
    assert "log_type" in metadata["log_info"]

    if log_path.name == "legacy_airdos_log.txt":
        assert metadata["log_device_info"]["AIRDOS"]["detector"] == "NaI(Tl)-D16x30"
        assert metadata["log_info"]["detector_type"] == "GEO_1024_v1"

    if metadata["log_info"].get("detector_type") == "AIRDOS04C":
        assert metadata["log_info"].get("histogram_channels") == hist.shape[0]
