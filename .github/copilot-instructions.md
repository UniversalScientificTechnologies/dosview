# Dosview Codebase AI Assistant Instructions

## Project Overview

**Dosview** is a lightweight PyQt5-based log viewer for analyzing radiation detector data from UST (Universal Scientific Technologies) dosimeters. It parses binary/text log files and visualizes spectral and temporal radiation data with matplotlib and pyqtgraph.

### Core Architecture
- **Parser-GUI separation**: `dosview/parsers.py` handles all file format detection and parsing (no Qt dependencies) to enable unit testing without GUI initialization
- **Multi-format support**: Two main log formats (AIRDOS04C v2.0 and legacy pre-2.0) with automatic detection
- **Threading model**: File loading happens in `LoadDataThread` to prevent UI blocking during large file parsing
- **PyQt5 multi-window support**: Handles multiple log files and app instances (single instance via QLocalSocket/QLocalServer pattern)

## Critical Patterns

### Parser Architecture (`dosview/parsers.py`)
The parser module is **parser-agnostic by design**. Add new format support by:
1. Subclass `BaseLogParser` with `detect()` (static) and `parse()` (instance) methods
2. Return tuple: `[time_axis (ndarray), sums (ndarray), hist (ndarray), metadata (dict)]`
3. Add to `LOG_PARSERS` sequence for auto-detection
4. Return data must have consistent ndarray shapes with `time_axis.shape[0] == sums.shape[0]`

**Example metadata structure**:
```python
{
    "log_device_info": {"DOS": {...}, "AIRDOS": {...}},
    "log_info": {
        "log_type": "xDOS_SPECTRAL",
        "detector_type": "AIRDOS04C",  # or legacy detector name
        "histogram_channels": 1024,
        "events_total": 12345
    }
}
```

### Data Format Conventions
- **Time axis**: Seconds (converted to minutes for UI via `/60`)
- **Histogram**: 1D numpy array, channel indices as x-axis
- **Log format detection**: First line matching triggers parser (e.g., `$DOS` prefix with/without `AIRDOS04C`)
- **Legacy format quirk**: Pads histogram to 1024 channels regardless of actual data width

### GUI Patterns (`dosview/__init__.py`)
- **PlotCanvas**: Uses `pg.GraphicsLayoutWidget` for dual-plot layout (evolution + spectrum)
- **Spectrum plot**: Log scale on both axes with marker overlays for channel events
- **Evolution plot**: Linear scale with rolling average overlay (20-point window)
- **Telemetry support**: Temperature, humidity, pressure, voltage metadata—already defined but not fully integrated

## Developer Workflows

### Testing
```bash
pytest  # Automatically discovers tests in tests/test_parser.py
```
- Tests require data fixtures in `data/` directory (e.g., `DATALOG_AIRDOS_GEO.TXT`)
- Parser tests parametrized by fixture files—each format should have at least one sample log
- No GUI testing (parsers are unit-testable independently)

### Building & Distribution
```bash
pip install .              # Development mode
python setup.py build sdist  # Build source distribution
pytest && python setup.py build sdist  # Full CI/CD flow (see .github/workflows/tests.yml)
```
- Entry point: `dosview:main()` defined in `pyproject.toml`
- Desktop integration: `dosview.desktop` installed to `/usr/local/share/applications` post-install
- Icon: `media/icon_ust.png` bundled via `setup.py` custom `PostInstallCommand`

### Running
```bash
dosview <filename>        # CLI entry point
```
- App auto-detects file format and loads appropriately
- Supports command-line file opening from system file manager

## Important Constraints & Decisions

### Why Parsers Don't Depend on Qt
Allows unit testing without initializing X11/display (critical for CI/CD headless environments). Import graph: `parsers.py` → `numpy/pandas` only; `__init__.py` imports `parsers` after Qt setup.

### Multi-Format Detection Strategy
- Linear first-line scan (fast for large files)
- `Airdos04CLogParser` detected first (specificity: `$DOS` + `AIRDOS04C`)
- `OldLogParser` catches everything else (fallback: `$DOS`, `$AIRDOS`, or `$HIST` prefixes)
- Raises `ValueError("Neznámý typ logu...")` if no match—never silently fails

### Known Limitations
- Telemetry fields defined but not wired to plots (see `PlotCanvas.telemetry_lines`)
- Spectrum plot hard-coded to 1024 channels (assumes all detectors standardize here)
- No support for real-time streaming (file-based only)

## When Adding Features

- **New detector format?** Extend `OldLogParser.detect()` or create `NewDetectorParser` subclass
- **New plot type?** Add to `PlotCanvas.plot()` before `self.show()` to avoid blocking
- **New metadata?** Update `metadata` dict in parser; PlotCanvas will have access via `self.data[3]`
- **New dependencies?** Add to `dependencies` list in `pyproject.toml` AND `requirements.txt` (both are used by CI)

## Testing New Code

Ensure parser tests pass with existing fixtures:
```bash
pytest tests/test_parser.py -v
```

For new parser format, commit sample log file to `data/` and verify:
- `test_any_parser_detects_fixture` finds your parser
- `test_parse_fixture_returns_consistent_shapes` validates output shapes
