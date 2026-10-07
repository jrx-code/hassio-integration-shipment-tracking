"""Carrier badges: the file has to exist, and every carrier sensor has to wear it.

The failure this guards against is silent. `entity_picture` pointing at a missing
file gives no error anywhere in HA — the entity just draws a broken image, and a
new carrier added without a badge would ship that way. The other half is the
reverse: a badge sitting in the folder that no sensor ever points at.

Source-text checks, like the rest of tests/ — this environment has no
`homeassistant` package to import the modules against.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "shipment_tracking"
_LOGOS = _ROOT / "logos"

# carrier -> the sensor module that must carry its picture
_SENSORS = {
    "inpost": "sensor.py",
    "dpd": "sensor_dpd.py",
    "fedex": "sensor_fedex.py",
    "pocztex": "sensor_pocztex.py",
    "dhl": "sensor_dhl.py",
}


def _carriers_in_const() -> list[str]:
    src = (_ROOT / "const.py").read_text()
    line = next(ln for ln in src.splitlines() if ln.startswith("CARRIERS = "))
    return [
        {"CARRIER_INPOST": "inpost", "CARRIER_DPD": "dpd", "CARRIER_FEDEX": "fedex",
         "CARRIER_POCZTEX": "pocztex", "CARRIER_DHL": "dhl"}[n.strip()]
        for n in line.split("[", 1)[1].rstrip("]").split(",") if n.strip()
    ]


def test_every_supported_carrier_has_a_badge():
    for carrier in _carriers_in_const():
        assert (_LOGOS / f"{carrier}.png").is_file(), (
            f"no badge for {carrier} — entity_picture would 404 silently"
        )


def test_badges_are_declared_available():
    """A file nobody may reference is as useless as a reference with no file."""
    declared = (_ROOT / "logos.py").read_text().split("AVAILABLE = {", 1)[1].split("}")[0]
    on_disk = {p.stem for p in _LOGOS.glob("*.png")}
    for carrier in on_disk:
        assert f'"{carrier}"' in declared, f"{carrier}.png not listed in AVAILABLE"
    for carrier in _carriers_in_const():
        assert carrier in on_disk


def test_every_carrier_sensor_sets_entity_picture():
    for carrier, module in _SENSORS.items():
        src = (_ROOT / module).read_text()
        assert "_attr_entity_picture" in src, f"{module} lost its carrier badge"
        assert "logo_url" in src, f"{module} no longer imports logo_url"


def test_badges_are_square_and_small():
    """Round-safe means square: HA crops entity_picture to a circle."""
    import struct

    for png in _LOGOS.glob("*.png"):
        head = png.read_bytes()[:24]
        width, height = struct.unpack(">II", head[16:24])
        assert width == height == 256, f"{png.name} is {width}x{height}, want 256x256"
        assert png.stat().st_size < 60_000, f"{png.name} is heavy for a list icon"
