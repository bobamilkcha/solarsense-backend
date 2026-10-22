"""Best-effort text extraction for TNB (Tenaga Nasional Berhad) electricity bills.

Patterns are built against a real 2026 domestic TNB bill (Malay layout, the
"Bil Elektrik Anda" / "Bil Terperinci Anda" two-page format) as extracted by
pdfplumber. pdfplumber flattens the bill's multi-column header into
interleaved lines, so labels and values are often not adjacent — the patterns
below anchor on spots that survive that flattening. Every field stays
optional: a bill whose layout doesn't match still gets stored with whatever
could be extracted, rather than being rejected outright.
"""

import io
import re
from dataclasses import dataclass
from datetime import date, datetime

import pdfplumber

_DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"

# "04.04.2026 - 03.05.2026 (30 Hari)" — the "(N Hari)" suffix distinguishes the
# billing period from other ranges on the bill (e.g. the AFA rate periods).
_PERIOD_WITH_DAYS_RE = re.compile(
    rf"({_DATE})\s*-\s*({_DATE})\s*\(\s*\d+\s*Hari\s*\)", re.IGNORECASE
)
# Fallback: the first date range anywhere (the header's TEMPOH BIL comes first).
_PERIOD_RE = re.compile(rf"({_DATE})\s*(?:-|hingga|sehingga)\s*({_DATE})", re.IGNORECASE)

# "Jumlah Penggunaan Anda kWh 600.00 695.00 1,295.00" — columns are
# without-service-tax, with-service-tax, total; the total is the last number.
# Not to be confused with "Purata Penggunaan Anda : 1,017 kWh" (6-month average).
_KWH_ROW_RE = re.compile(
    r"Jumlah\s+Penggunaan\s+Anda\s+kWh((?:[ \t]+[\d,]+(?:\.\d+)?(?=\s|$))+)", re.IGNORECASE
)
# Fallback: the kWh meter reading row, "M <meter no> <prev> <curr> <usage> kWh".
_KWH_METER_RE = re.compile(r"^M\s+\S+\s+[\d,]+\s+[\d,]+\s+([\d,]+)\s+kWh\b", re.MULTILINE)

# The "TARIF" heading ends a line (other columns may precede it); the value is
# on the next line. Case-sensitive on purpose: lowercase "tarif" also appears
# in running text ("perubahan tarif ...") and URLs (".../tariff").
_TARIFF_RE = re.compile(r"\bTARIF[ \t]*\n[ \t]*([^\n]+?)[ \t]*$", re.MULTILINE)

# Money amounts; TNB prints negatives with a Unicode minus ("−0.02").
_MONEY = r"[-\u2212]?[\d,]+\.\d{2}(?![\d.])"

# "Jumlah Bil Anda (RM)\n616.20" — total payable (previous balance + current
# charges + rounding adjustment). Can be negative when the account is in credit.
_AMOUNT_RE = re.compile(rf"Jumlah\s+Bil\s+Anda\s*\(RM\)\s*({_MONEY})", re.IGNORECASE)

# "Caj Semasa RM 616.22" (page 2 breakdown) — this period's charges only, no
# previous balance. Page 1's "Caj Semasa (RM)" heading is skipped: its value
# sits on a separate line alongside other columns, so it isn't reliable.
_CURRENT_CHARGES_RE = re.compile(rf"^Caj\s+Semasa\s+RM\s+({_MONEY})", re.MULTILINE | re.IGNORECASE)


@dataclass
class ParsedBillFields:
    billing_period_start: date | None = None
    billing_period_end: date | None = None
    kwh_used: float | None = None
    tariff_category: str | None = None
    amount_due: float | None = None
    current_charges: float | None = None


def _parse_date(raw: str) -> date | None:
    normalized = raw.strip().replace(".", "/").replace("-", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _parse_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "").replace("\u2212", "-"))
    except ValueError:
        return None


def extract_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_bill_text(text: str) -> ParsedBillFields:
    fields = ParsedBillFields()

    if match := _PERIOD_WITH_DAYS_RE.search(text) or _PERIOD_RE.search(text):
        fields.billing_period_start = _parse_date(match.group(1))
        fields.billing_period_end = _parse_date(match.group(2))

    if match := _KWH_ROW_RE.search(text):
        fields.kwh_used = _parse_number(match.group(1).split()[-1])
    elif match := _KWH_METER_RE.search(text):
        fields.kwh_used = _parse_number(match.group(1))

    if match := _TARIFF_RE.search(text):
        fields.tariff_category = match.group(1)

    if match := _AMOUNT_RE.search(text):
        fields.amount_due = _parse_number(match.group(1))

    if match := _CURRENT_CHARGES_RE.search(text):
        fields.current_charges = _parse_number(match.group(1))

    return fields


def parse_bill_pdf(pdf_bytes: bytes) -> ParsedBillFields:
    text = extract_text(pdf_bytes)
    return parse_bill_text(text)
