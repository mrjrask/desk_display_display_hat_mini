import math

from screens.draw_inside import (
    _build_metric_entries,
    _build_voc_tile,
    _normalize_pressure,
)


def test_normalize_pressure_returns_hpa_and_inhg():
    pres_hpa, pres_inhg = _normalize_pressure(101325)
    assert math.isclose(pres_hpa, 1013.25, rel_tol=1e-4)
    assert math.isclose(pres_inhg, 29.92, rel_tol=1e-3)


def test_build_metric_entries_prefers_inhg():
    data = {
        "pressure_hpa": 1013.2,
        "pressure_inhg": 29.92,
    }

    metrics = _build_metric_entries(data)
    assert metrics, "Expected at least one metric entry"
    first_metric = metrics[0]
    assert first_metric["label"] == "Pressure"
    assert "inHg" in first_metric["value"]


def test_build_voc_tile_includes_bme680_providers():
    data = {"voc_ohms": 12_000.0}

    voc_tile = _build_voc_tile(data, "Adafruit BME680")

    assert voc_tile, "Expected VOC tile to be built when VOC data is present"
    assert voc_tile["label"] == "VOC"
    assert "kΩ" in voc_tile["value"]


def test_build_voc_tile_uses_bsec_voc_index():
    data = {"voc_index": 125.0}

    voc_tile = _build_voc_tile(data, "Pimoroni BME688")

    assert voc_tile, "Expected VOC tile to render from BSEC VOC index"
    assert voc_tile["label"] == "VOC Index"
    assert voc_tile["value"].startswith("125")
