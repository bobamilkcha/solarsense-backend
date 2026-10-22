"""Default checklist for a Malaysian rooftop solar site survey.

Every new visit starts with a copy of these items (unless the caller opts
out); installers can then add, edit, or remove items on that visit.
"""

DEFAULT_CHECKLIST: list[tuple[str, list[str]]] = [
    (
        "Roof",
        [
            "Roof type (metal deck / clay tile / concrete / other)",
            "Roof condition: no leaks, rust, or cracked tiles",
            "Roof orientation and pitch",
            "Usable roof area (m²)",
            "Structure can carry panel load (~15 kg/m²)",
        ],
    ),
    (
        "Shading",
        [
            "Nearby obstructions (trees, buildings, water tanks)",
            "Shading in the morning and late afternoon",
        ],
    ),
    (
        "Electrical",
        [
            "Supply type (single phase / three phase)",
            "Main switchboard condition and spare ways",
            "Main breaker rating (A)",
            "Earthing system present and in good condition",
            "TNB meter type and location (for meter change)",
        ],
    ),
    (
        "Installation",
        [
            "Inverter location: shaded, ventilated, near switchboard",
            "DC/AC cable route",
            "Roof access for installation and maintenance",
            "Safety hazards (fragile roof, no edge protection)",
        ],
    ),
    (
        "SolarSense device",
        [
            "Device mounted flat and unshaded",
            "Device online and sending readings",
        ],
    ),
    (
        "Customer",
        [
            "Latest TNB bill collected",
            "Customer briefed on next steps",
        ],
    ),
]


def default_items() -> list[tuple[str, str]]:
    """(category, label) pairs in checklist order."""
    return [(category, label) for category, labels in DEFAULT_CHECKLIST for label in labels]
