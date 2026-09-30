"""QuickBooks CSV export: one row per claim line.

Each row carries what's needed to book it in QuickBooks: payee, QB account
(from the category), QB class (from the show), amounts split into subtotal and
HST with the QB tax code, plus the audit trail (who approved, signed off and
paid).

QuickBooks calculates tax from the subtotal at the code's rate, so "HST check"
flags lines whose receipt HST isn't 13% of the subtotal (e.g. a receipt mixing
taxed and untaxed items) — those need the tax adjusted by hand in QB.
"""

import csv
import io

from flask import current_app

from expenses.models import KINDS, PAYMENT_METHODS, ExpenseClaim as Claim, person_name
from expenses.parsing import local_time

TAX_CODE_HST = 'HST ON - PSB Rebate (Purchases)'
TAX_CODE_NO_HST = 'Exempt'
HST_RATE_PERCENT = 13

COLUMNS = [
    "Claim #", "Type", "Status", "Payee", "Payee email",
    "Show", "QB class", "Date", "Merchant", "Description", "Category", "QB account",
    "Subtotal", "HST", "Total", "QB tax code", "HST check",
    "Invoice #", "Invoice date", "Due date",
    "Submitted by", "Approved by", "Signed off by", "Signed off at",
    "Paid on", "Payment method", "Payment reference", "Paid by",
]

# Spreadsheet apps run cells starting with these as formulas.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _text(value) -> str:
    """Stringify, neutralising spreadsheet formula injection."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def _amount(cents: int) -> str:
    return f"{cents / 100:.2f}"


def _tax_code(hst_cents: int) -> str:
    config = current_app.config
    if hst_cents:
        return config.get('EXPENSES_QB_TAX_CODE_HST', TAX_CODE_HST)
    return config.get('EXPENSES_QB_TAX_CODE_NO_HST', TAX_CODE_NO_HST)


def hst_check(subtotal_cents: int, hst_cents: int) -> str:
    """Blank if the HST matches the standard rate (±1¢), otherwise a note."""
    if not hst_cents:
        return ""
    rate = HST_RATE_PERCENT
    expected = (subtotal_cents * rate + 50) // 100
    if abs(hst_cents - expected) <= 1:
        return ""
    return f"HST isn't {rate}% of subtotal (expected {_amount(expected)}) - adjust tax in QB"


def rows(claims: list[Claim]):
    for claim in claims:
        approved = claim.last_event("approved")
        signed = claim.last_event("signed off")
        payment = claim.payment
        head = {
            "Claim #": claim.id,
            "Type": KINDS[claim.kind],
            "Status": claim.status,
            "Payee": _text(claim.payee_name),
            "Payee email": _text(claim.payee_email),
            "Show": _text(claim.show.name if claim.show else "General"),
            "QB class": _text(claim.show.qb_class if claim.show else ""),
            "Invoice #": _text(claim.invoice_number),
            "Invoice date": claim.invoice_date or "",
            "Due date": claim.due_date or "",
            "Submitted by": _text(person_name(claim.submitter)),
            "Approved by": _text(person_name(approved.actor) if approved else ""),
            "Signed off by": _text(person_name(signed.actor) if signed else ""),
            "Signed off at": local_time(signed.created_at) if signed else "",
            "Paid on": payment.paid_on if payment else "",
            "Payment method": PAYMENT_METHODS.get(payment.method, "") if payment else "",
            "Payment reference": _text(payment.reference) if payment else "",
            "Paid by": _text(person_name(payment.paid_by)) if payment else "",
        }
        for line in claim.lines:
            yield {
                **head,
                "Date": line.spent_on,
                "Merchant": _text(line.merchant),
                "Description": _text(line.description),
                "Category": _text(line.category.label),
                "QB account": _text(line.category.qb_account),
                "Subtotal": _amount(line.subtotal_cents),
                "HST": _amount(line.hst_cents),
                "Total": _amount(line.total_cents),
                "QB tax code": _tax_code(line.hst_cents),
                "HST check": hst_check(line.subtotal_cents, line.hst_cents),
            }


def to_csv(claims: list[Claim]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows(claims))
    # BOM so Excel opens accented names (e.g. "Montréal") correctly.
    return "﻿" + buffer.getvalue()
