"""Unit tests for the TNB bill text parser.

`REAL_BILL_TEXT` is an excerpt of pdfplumber's output for a real 2026 domestic
TNB bill (account/meter/invoice numbers replaced), keeping the interleaved
multi-column lines and the distractors the parser must skip: AFA rate-period
date ranges, the 6-month average kWh, lowercase "tarif" in running text, and
the page-1 "Caj Semasa (RM)" heading whose value isn't on its own line.
"""

from datetime import date

from app.modules.bills.parser import parse_bill_text

REAL_BILL_TEXT = """\
Bil Elektrik Anda
ALAMAT POS TARIKH BIL NO. AKAUN
XXXXXXXXXXXXXXXXXX 04.05.2026 0000000000XX
XXXXXXXX,RESIDENSI SETIAWANGSA
TEMPOH BIL JENIS BACAAN
XXXXXX, JALAN 1/56
04.04.2026 - 03.05.2026 Bacaan Sebenar
TAMAN SETIAWANGSA
(30 Hari)
54200 KUALA LUMPUR TARIF
Domestik Am
WP KUALA LUMPUR
BAYARAN BAGI TEMPOH
DEPOSIT SEKURITI 04.04.2026 - 03.05.2026
RM550.80 RM501.05
Ringkasan Bil Anda:
Jumlah Bil Anda (RM)
616.20 Baki Terdahulu (RM) Caj Semasa (RM) Pelarasan Penggenapan
0.00 616.22 −0.02
Mulai 1 Julai 2025, terdapat perubahan tarif di dalam pengiraan bil anda.
03 Jun 2026 Untuk maklumat lanjut, sila layari www.mytnb.com.my/tariff
(BS) RM616.20 kWh 980 812 972 945 1,097 1,295
Purata Penggunaan Anda : 1,017 kWh
Bil Terperinci Anda
Tempoh Bil
04.04.2026 - 03.05.2026 (30 Hari)
Jenis Caj Tanpa ST Dengan ST Jumlah
Jumlah Penggunaan Anda kWh 600.00 695.00 1,295.00
Tenaga (RM0.2703/kWh) RM 162.18 187.86 350.04
AFA (129kWh, RM0.0138/kWh) mulai 01/05/26 RM 0.83 0.95 1.78
Caj Semasa RM 616.22
M HOL0000000000000 65,121 66,416 1,295 kWh (AFA) bagi tempoh bil:
• 01.04.2026 - 30.04.2026:
M HOL0000000000000 467 472 5 kW -RM0.0047/kWh
"""


def test_parses_real_bill_layout() -> None:
    fields = parse_bill_text(REAL_BILL_TEXT)

    assert fields.billing_period_start == date(2026, 4, 4)
    assert fields.billing_period_end == date(2026, 5, 3)
    assert fields.kwh_used == 1295.0
    assert fields.tariff_category == "Domestik Am"
    assert fields.amount_due == 616.20
    assert fields.current_charges == 616.22


def test_period_ignores_afa_range_when_header_range_missing() -> None:
    # Only the page-2 range (with "(N Hari)") survives; AFA range comes earlier.
    text = "• 01.04.2026 - 30.04.2026:\nTempoh Bil\n04.04.2026 - 03.05.2026 (30 Hari)\n"
    fields = parse_bill_text(text)

    assert fields.billing_period_start == date(2026, 4, 4)
    assert fields.billing_period_end == date(2026, 5, 3)


def test_kwh_falls_back_to_meter_row() -> None:
    text = "Purata Penggunaan Anda : 1,017 kWh\nM HOL0000000000000 65,121 66,416 1,295 kWh\n"

    assert parse_bill_text(text).kwh_used == 1295.0


def test_kwh_row_ignores_trailing_side_panel_text() -> None:
    text = "Jumlah Penggunaan Anda kWh 600.00 695.00 1,295.00 1-300-88-5454\n"

    assert parse_bill_text(text).kwh_used == 1295.0


def test_kwh_row_under_600_kwh() -> None:
    text = "Jumlah Penggunaan Anda kWh 450.00 450.00\n"

    assert parse_bill_text(text).kwh_used == 450.0


def test_credit_balance_with_unicode_minus() -> None:
    text = "Jumlah Bil Anda (RM)\n\u221212.30 Baki Terdahulu (RM)\n"

    assert parse_bill_text(text).amount_due == -12.30


def test_page_one_caj_semasa_heading_is_not_current_charges() -> None:
    text = "Caj Semasa (RM)\n0.00 616.22 \u22120.02\n"

    assert parse_bill_text(text).current_charges is None


def test_lowercase_tarif_in_running_text_is_not_a_tariff() -> None:
    text = "terdapat perubahan tarif\ndi dalam pengiraan bil anda.\nwww.mytnb.com.my/tariff\n"

    assert parse_bill_text(text).tariff_category is None


def test_unmatched_text_leaves_fields_none() -> None:
    fields = parse_bill_text("this text matches none of the expected labels")

    assert fields.billing_period_start is None
    assert fields.billing_period_end is None
    assert fields.kwh_used is None
    assert fields.tariff_category is None
    assert fields.amount_due is None
    assert fields.current_charges is None


def test_partial_match_leaves_other_fields_none() -> None:
    fields = parse_bill_text("Jumlah Bil Anda (RM)\n616.20")

    assert fields.amount_due == 616.20
    assert fields.kwh_used is None
    assert fields.billing_period_start is None
