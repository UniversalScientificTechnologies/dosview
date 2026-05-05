import csv
import json

from dosview.calibration_widget import (
    CALIBRATION_CSV_METADATA_KEY,
    CalibrationTab,
    make_project_relative_path,
    resolve_project_path,
)


def test_calibration_csv_metadata_is_loaded(tmp_path):
    payload = {
        "version": 1,
        "environment": {
            "temperature_celsius": 20.5,
            "relative_humidity_percent": 45.0,
            "pressure_hpa": 971.2,
        },
        "device": {
            "analog_module": {
                "type": "USTSIPIN03C",
                "serial_number": "09104108741008504c3ba080a0800056",
                "configuration": "ffff",
            }
        },
    }
    path = tmp_path / "spectrum.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([CALIBRATION_CSV_METADATA_KEY, json.dumps(payload)])
        writer.writerow(["channel", "counts"])
        writer.writerow([0, 10])
        writer.writerow([1, 20])

    tab = CalibrationTab.__new__(CalibrationTab)
    data = tab.load_spectrum_data(str(path))

    assert data["source_format"] == "csv"
    assert data["environment"]["pressure_hpa"] == 971.2
    assert data["device"]["analog_module"]["serial_number"] == "09104108741008504c3ba080a0800056"
    assert data["channels"].tolist() == [0.0, 1.0]
    assert data["counts"].tolist() == [10.0, 20.0]


def test_project_paths_are_relative_to_calib_file(tmp_path):
    project_path = tmp_path / "calibration" / "project.dosview_calib"
    csv_path = tmp_path / "calibration" / "spectra" / "source.csv"
    project_path.parent.mkdir()
    csv_path.parent.mkdir()
    csv_path.write_text("channel,counts\n0,1\n", encoding="utf-8")

    stored_path = make_project_relative_path(str(csv_path), str(project_path))

    assert stored_path == "spectra/source.csv"
    assert resolve_project_path(stored_path, str(project_path)) == str(csv_path)
