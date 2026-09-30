"""Starter expense categories mapped to Theatre Aurora's QuickBooks accounts.

Show expenses use the generic ``Show Expenses:<Category>`` accounts; the show
itself is tracked by QB class. Account names must match QuickBooks exactly.
A ``None`` account means QuickBooks has no suitable account yet — the Payments
page flags it until one is set in Setup → Categories.

Run with ``flask expenses seed-categories`` (safe to repeat; existing
categories keep their settings, except that a blank QB account is filled in).
"""
from auth.models import db
from expenses.models import ExpenseCategory

CATEGORIES: list[tuple[str, str | None]] = [
    # --- Show expenses (show tracked by QB class) ---
    ("Costumes", "Show Expenses:Costumes"),
    ("Props", "Show Expenses:Props"),
    ("Set build & materials", None),            # no generic Show Expenses:Set Build yet
    ("Lighting & sound supplies", "Show Expenses:Technical Supplies"),
    ("Cast & crew hospitality", "Show Expenses:Hospitality"),
    ("Show advertising", "Show Expenses:Advertising"),
    ("Programs & show printing", "Show Expenses:Printing"),
    ("Equipment rental", "Show Expenses:Equipment Rental"),
    ("Rights & scripts", "Show Expenses:Rights"),
    ("Sheet music", "Show Expenses:Music Purchases"),
    ("Musicians", "Show Expenses:Musicians"),
    ("Honorariums", "Show Expenses:Honorariums"),
    ("Rehearsal space", None),                  # no generic Show Expenses:Rehearsal Space yet
    # --- General theatre expenses ---
    ("Office supplies", "Office expenses"),
    ("Stationery & printing", "Stationery and printing"),
    ("Front of house supplies", "Front of House Expenses"),
    ("Bar & liquor", "Front of House Expenses:Liquor"),
    ("Cleaning", "Cleaning"),
    ("Building repairs", "Repair and maintenance:Miscellaneous"),
    ("Tools", "Tools"),
    ("General supplies", "Supplies"),
    ("Technical supplies (theatre)", "Technical Supplies"),
    ("Marketing & promotion", "Marketing"),
    ("Celebrations", "Office expenses:Celebrations"),
    ("Flowers", "Office expenses:Flowers"),
    ("Holiday party food", "Holiday Party:Food"),
    ("Website & software", "Office expenses:Website Costs"),
    ("Postage & delivery", "Freight and Delivery"),
    ("Travel & mileage", "Travel"),
    ("Travel meals", "Travel meals"),
    ("Other (VP of Finance will categorize)", "Uncategorized Expense"),
]


def seed() -> list[str]:
    """Add missing categories and fill blank QB accounts. Returns labels changed."""
    existing = {c.label: c for c in ExpenseCategory.query}
    changed = []
    for label, account in CATEGORIES:
        category = existing.get(label)
        if category is None:
            db.session.add(ExpenseCategory(label=label, qb_account=account))
            changed.append(label)
        elif not category.qb_account and account:
            category.qb_account = account
            changed.append(label)
    db.session.commit()
    return changed
