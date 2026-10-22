"""Convert the reference cell's measured current into irradiance (W/m^2).

The cell feeds a 10 ohm shunt, which is well below its maximum-power load, so
it runs close to short-circuit. A solar cell's short-circuit current rises in
proportion to the sunlight hitting it, so:

    irradiance = cell_current / Isc_at_STC * 1000 W/m^2

where Isc_at_STC is the cell's short-circuit current at standard test
conditions (1000 W/m^2). Ignores the small temperature effect on Isc
(roughly +0.05%/C for silicon).
"""

from app.core.config.app_config import app_config

STC_IRRADIANCE_WM2 = 1000.0


def irradiance_wm2(cell_current: float, isc_stc_a: float | None = None) -> float:
    isc = isc_stc_a if isc_stc_a is not None else app_config.REFERENCE_CELL_ISC_A
    # Small negative currents are ADC noise in the dark, not real readings.
    return max(cell_current, 0.0) / isc * STC_IRRADIANCE_WM2
