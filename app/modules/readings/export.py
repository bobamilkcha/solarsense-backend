"""Raw readings export as CSV or Excel (FR8).

One row per reading, oldest first, with the derived irradiance alongside the
raw values. Timestamps are given in UTC and Malaysian local time.
"""

import csv
import io
from collections.abc import Sequence
from datetime import datetime
from zoneinfo import ZoneInfo

from app.models import SensorReading
from app.modules.readings.irradiance import irradiance_wm2
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")
# Excel's sheet limit is 1,048,576 rows, one of which is the header.
XLSX_MAX_ROWS = 1_048_575

COLUMNS = [
    "timestamp_utc",
    "timestamp_local",
    "cell_voltage_v",
    "cell_current_a",
    "irradiance_wm2",
    "ambient_temp_c",
    "humidity_pct",
    "tilt_x",
    "tilt_y",
    "tilt_z",
    "heading_deg",
    "received_at_utc",
]


def _utc(ts: datetime) -> datetime:
    return ts.astimezone(ZoneInfo("UTC"))


def _values(r: SensorReading) -> list[object]:
    return [
        _utc(r.device_timestamp),
        r.device_timestamp.astimezone(LOCAL_TZ),
        float(r.cell_voltage),
        float(r.cell_current),
        round(irradiance_wm2(float(r.cell_current)), 2),
        float(r.ambient_temp),
        float(r.humidity),
        float(r.tilt_x),
        float(r.tilt_y),
        float(r.tilt_z),
        float(r.heading),
        _utc(r.received_at),
    ]


def readings_to_csv(readings: Sequence[SensorReading]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for r in readings:
        writer.writerow(v.isoformat() if isinstance(v, datetime) else v for v in _values(r))
    # BOM so Excel detects UTF-8 when the CSV is double-clicked.
    return buf.getvalue().encode("utf-8-sig")


def readings_to_xlsx(readings: Sequence[SensorReading]) -> bytes:
    wb = Workbook(write_only=True)  # streams rows; much lighter for big exports
    ws = wb.create_sheet("Readings")
    ws.freeze_panes = "A2"
    for i, width in enumerate([20, 20] + [15] * (len(COLUMNS) - 3) + [20]):
        ws.column_dimensions[chr(ord("A") + i)].width = width

    header = []
    for name in COLUMNS:
        cell = WriteOnlyCell(ws, value=name)
        cell.font = Font(bold=True)
        header.append(cell)
    ws.append(header)

    for r in readings:
        row = []
        for v in _values(r):
            if isinstance(v, datetime):
                # Excel has no time zones: store the wall-clock time, with the
                # zone named in the column header.
                cell = WriteOnlyCell(ws, value=v.replace(tzinfo=None))
                cell.number_format = "yyyy-mm-dd hh:mm:ss"
            else:
                cell = WriteOnlyCell(ws, value=v)
            row.append(cell)
        ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
