"""
Repositories — the ONLY place SQL lives.

Each repository wraps the Database connection and exposes methods that
take/return domain dataclasses (defined in billing_engine/models/).

⚠️ YOU IMPLEMENT every method body marked TODO.
   The signatures, docstrings, and the LedgerRepository's append-only
   guarantee are already in place — do not change them.

Conventions:
  - Always use parameterized queries (`?` placeholders) — NEVER f-string SQL.
  - Money values are persisted as TEXT using `money.to_storage()`.
  - Dates are persisted as ISO strings (`date.isoformat()`).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from billing_engine.db.database import Database
from billing_engine.money import Money
from billing_engine.models import (
    Customer,
    Plan, PricingType, BillingPeriod,
    Subscription, SubscriptionStatus,
    Invoice, InvoiceStatus, InvoiceLineItem, LineItemKind,
    LedgerEntry, LedgerDirection,
)


# ============================================================
# CUSTOMERS
# ============================================================
class CustomerRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, customer: Customer) -> Customer:
        """Insert and return the customer with `id` populated."""
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO customers (name, email, country, state) VALUES (?, ?, ?, ?)",
                (customer.name, customer.email, customer.country, customer.state),
            )
            return Customer(cur.lastrowid, customer.name, customer.email, customer.country, customer.state)

    def get(self, customer_id: int) -> Optional[Customer]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, name, email, country, state FROM customers WHERE id = ?",
                (customer_id,),
            ).fetchone()
        if row is None:
            return None
        return Customer(*row)
    def find_by_email(self, email: str) -> Optional[Customer]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, name, email, country, state FROM customers WHERE email = ?",
                (email,),
            ).fetchone()
        if row is None:
            return None
        return Customer(*row)

    def list_all(self) -> list[Customer]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, email, country, state FROM customers"
            ).fetchall()
        return [Customer(*row) for row in rows]



# ============================================================
# PLANS  +  PLAN TIERS
# ============================================================
class PlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, plan: Plan) -> Plan:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO plans (name, pricing_type, billing_period, currency) VALUES (?, ?, ?, ?)",
                (plan.name, plan.pricing_type.value, plan.billing_period.value, plan.currency),
            )
            return Plan(cur.lastrowid, plan.name, plan.pricing_type, plan.billing_period, plan.currency)
    def get(self, plan_id: int) -> Optional[Plan]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, name, pricing_type, billing_period, currency FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
        if row is None:
            return None
        return Plan(row[0], row[1], PricingType(row[2]), BillingPeriod(row[3]), row[4])

    def list_all(self) -> list[Plan]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT id, name, pricing_type, billing_period, currency FROM plans"
            ).fetchall()
        return [Plan(r[0], r[1], PricingType(r[2]), BillingPeriod(r[3]), r[4]) for r in rows]

class PlanTierRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, plan_id: int, from_units: int, to_units: Optional[int], unit_price: Money) -> int:
        """Insert a tier; return new id."""
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO plan_tiers (plan_id, from_units, to_units, unit_price) VALUES (?, ?, ?, ?)",
                (plan_id, from_units, to_units, unit_price.to_storage()),
            )
            return cur.lastrowid

    def list_for_plan(self, plan_id: int, currency: str) -> list[tuple[int, Optional[int], Money]]:
        """Return [(from_units, to_units, unit_price)] ordered by from_units.

        Currency is passed in (the plan_tiers table stores only the amount;
        currency lives on the parent plan).
        """
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT from_units, to_units, unit_price FROM plan_tiers WHERE plan_id = ? ORDER BY from_units",
                (plan_id,),
            ).fetchall()
        return [(r[0], r[1], Money(r[2], currency)) for r in rows]



# ============================================================
# DISCOUNTS
# ============================================================
class DiscountRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, code: str, discount_type: str, value: str, currency: Optional[str] = None) -> int:
         with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO discounts (code, discount_type, value, currency) VALUES (?, ?, ?, ?)",
                (code, discount_type, value, currency),
            )
            return cur.lastrowid

    def get_by_code(self, code: str) -> Optional[dict]:
        """Return raw row as dict, or None. (Discount has no dataclass yet — we use a dict for now.)"""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT id, code, discount_type, value, currency FROM discounts WHERE code = ?",
                (code,),
            ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "code": row[1], "discount_type": row[2], "value": row[3], "currency": row[4]}



# ============================================================
# SUBSCRIPTIONS
# ============================================================
class SubscriptionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, subscription: Subscription) -> Subscription:
       with self.db.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO subscriptions
                   (customer_id, plan_id, status, current_period_start, current_period_end,
                    trial_end, discount_id, past_due_since)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    subscription.customer_id,
                    subscription.plan_id,
                    subscription.status.value,
                    subscription.current_period_start.isoformat(),
                    subscription.current_period_end.isoformat(),
                    subscription.trial_end.isoformat() if subscription.trial_end else None,
                    subscription.discount_id,
                    subscription.past_due_since.isoformat() if subscription.past_due_since else None,
                ),
            )
            return Subscription(
                cur.lastrowid,
                subscription.customer_id,
                subscription.plan_id,
                subscription.status,
                subscription.current_period_start,
                subscription.current_period_end,
                subscription.trial_end,
                subscription.discount_id,
                subscription.past_due_since,
            )

    def get(self, subscription_id: int) -> Optional[Subscription]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT id, customer_id, plan_id, status, current_period_start,
                          current_period_end, trial_end, discount_id, past_due_since
                   FROM subscriptions WHERE id = ?""",
                (subscription_id,),
            ).fetchone()
        return self._row_to_subscription(row) if row else None

    def list_all(self) -> list[Subscription]:
        """All subscriptions, regardless of status. Used by BillingCycle trial scan."""
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, customer_id, plan_id, status, current_period_start,
                          current_period_end, trial_end, discount_id, past_due_since
                   FROM subscriptions"""
            ).fetchall()
        return [self._row_to_subscription(r) for r in rows]


    def get_due_for_billing(self, as_of: date) -> list[Subscription]:
        """Subscriptions whose current_period_end <= as_of AND status is ACTIVE.
        (Hint: trial subscriptions whose trial_end <= as_of should also become billable —
         either handle that here or transition them to ACTIVE first in BillingCycle.)
        """
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, customer_id, plan_id, status, current_period_start,
                          current_period_end, trial_end, discount_id, past_due_since
                   FROM subscriptions
                   WHERE status = ? AND current_period_end <= ?""",
                (SubscriptionStatus.ACTIVE.value, as_of.isoformat()),
            ).fetchall()
        return [self._row_to_subscription(r) for r in rows]

    def update_period(self, subscription_id: int, new_start: date, new_end: date) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE subscriptions SET current_period_start = ?, current_period_end = ? WHERE id = ?",
                (new_start.isoformat(), new_end.isoformat(), subscription_id),
            )

    def update_status(
        self,
        subscription_id: int,
        new_status: SubscriptionStatus,
        past_due_since: Optional[date] = None,
    ) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE subscriptions SET status = ?, past_due_since = ? WHERE id = ?",
                (
                    new_status.value,
                    past_due_since.isoformat() if past_due_since else None,
                    subscription_id,
                ),
            )

    def update_plan(self, subscription_id: int, new_plan_id: int) -> None:
        """Switch the subscription to a different plan (used by upgrade flow)."""
        raise NotImplementedError("Day 4: implement SubscriptionRepository.update_plan")



# ============================================================
# USAGE
# ============================================================
class UsageRecordRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, subscription_id: int, metric: str, quantity: int) -> int:
         with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO usage_records (subscription_id, metric, quantity) VALUES (?, ?, ?)",
                (subscription_id, metric, quantity),
            )
            return cur.lastrowid

    def sum_for_period(
        self, subscription_id: int, metric: str, period_start: date, period_end: date
    ) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT COALESCE(SUM(quantity), 0) FROM usage_records
                   WHERE subscription_id = ? AND metric = ?
                     AND recorded_at >= ? AND recorded_at < ?""",
                (subscription_id, metric, period_start.isoformat(), period_end.isoformat()),
            ).fetchone()
        return int(row[0])



# ============================================================
# INVOICES + LINE ITEMS
# ============================================================
class InvoiceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, invoice: Invoice) -> Invoice:
        """Insert invoice (NOT line items — that's the other repo).

        Must respect the UNIQUE(subscription_id, period_start) constraint.
        If a duplicate is attempted, raise sqlite3.IntegrityError naturally
        (caller is responsible for handling it — this gives idempotency).
        """
        with self.db.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO invoices
                   (subscription_id, period_start, period_end, status, subtotal, discount_amount,
                    tax_amount, total, currency, issued_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    invoice.subscription_id,
                    invoice.period_start.isoformat(),
                    invoice.period_end.isoformat(),
                    invoice.status.value,
                    invoice.subtotal.to_storage(),
                    invoice.discount_amount.to_storage(),
                    invoice.tax_amount.to_storage(),
                    invoice.total.to_storage(),
                    invoice.currency,
                    invoice.issued_at.isoformat() if invoice.issued_at else None,
                ),
            )
            return Invoice(
                cur.lastrowid,
                invoice.subscription_id,
                invoice.period_start,
                invoice.period_end,
                invoice.status,
                invoice.subtotal,
                invoice.discount_amount,
                invoice.tax_amount,
                invoice.total,
                invoice.currency,
                invoice.issued_at,
            )

    def get(self, invoice_id: int) -> Optional[Invoice]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT id, subscription_id, period_start, period_end, status,
                          subtotal, discount_amount, tax_amount, total, currency, issued_at
                   FROM invoices WHERE id = ?""",
                (invoice_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_invoice(row, row[9])

    def count_for_subscription(self, subscription_id: int) -> int:
        """Used by FirstMonthFree discount."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM invoices WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchone()
        return int(row[0])

    def mark_paid(self, invoice_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE invoices SET status = ? WHERE id = ?",
                (InvoiceStatus.PAID.value, invoice_id),
            )
    def mark_failed(self, invoice_id: int) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE invoices SET status = ? WHERE id = ?",
                (InvoiceStatus.FAILED.value, invoice_id),
            )

    def set_pdf_path(self, invoice_id: int, path: str) -> None:
        raise NotImplementedError("Day 4: implement InvoiceRepository.set_pdf_path")


class InvoiceLineItemRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, line_item: InvoiceLineItem) -> InvoiceLineItem:
        with self.db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO invoice_line_items (invoice_id, kind, description, amount) VALUES (?, ?, ?, ?)",
                (
                    line_item.invoice_id,
                    line_item.kind.value,
                    line_item.description,
                    line_item.amount.to_storage(),
                ),
            )
            return InvoiceLineItem(cur.lastrowid, line_item.invoice_id, line_item.kind, line_item.description, line_item.amount)
    def list_for_invoice(self, invoice_id: int) -> list[InvoiceLineItem]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, invoice_id, kind, description, amount
                   FROM invoice_line_items WHERE invoice_id = ?""",
                (invoice_id,),
            ).fetchall()
            # need currency — fetch from parent invoice
            inv_row = conn.execute(
                "SELECT currency FROM invoices WHERE id = ?", (invoice_id,)
            ).fetchone()
        currency = inv_row[0] if inv_row else "INR"
        return [
            InvoiceLineItem(r[0], r[1], LineItemKind(r[2]), r[3], Money(r[4], currency))
            for r in rows
        ]

# ============================================================
# LEDGER — APPEND-ONLY (do not implement update/delete)
# ============================================================
class LedgerRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, entry: LedgerEntry) -> LedgerEntry:
        with self.db.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO ledger_entries
                   (customer_id, invoice_id, direction, amount, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry.customer_id,
                    entry.invoice_id,
                    entry.direction.value,
                    entry.amount.to_storage(),
                    entry.description,
                    entry.created_at.isoformat() if entry.created_at else None,
                ),
            )
            return LedgerEntry(
                cur.lastrowid,
                entry.customer_id,
                entry.invoice_id,
                entry.direction,
                entry.amount,
                entry.description,
                entry.created_at,
            )
    def list_for_customer(self, customer_id: int) -> list[LedgerEntry]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, customer_id, invoice_id, direction, amount, description, created_at
                   FROM ledger_entries WHERE customer_id = ? ORDER BY id""",
                (customer_id,),
            ).fetchall()
            # fetch a currency sample from the customer's invoices
            cur_row = conn.execute(
                """SELECT i.currency FROM invoices i
                   JOIN subscriptions s ON s.id = i.subscription_id
                   WHERE s.customer_id = ? LIMIT 1""",
                (customer_id,),
            ).fetchone()
        currency = cur_row[0] if cur_row else "INR"
        return [
            LedgerEntry(r[0], r[1], r[2], LedgerDirection(r[3]), Money(r[4], currency), r[5],
                        datetime.fromisoformat(r[6]) if r[6] else None)
            for r in rows
        ]

    # ✅ These two methods are intentionally implemented to REJECT — do not override.
    def update(self, *args, **kwargs):
        raise NotImplementedError("Ledger is append-only. Post a reversing entry instead.")

    def delete(self, *args, **kwargs):
        raise NotImplementedError("Ledger is append-only. Post a reversing entry instead.")


# ============================================================
# PAYMENT ATTEMPTS
# ============================================================
class PaymentAttemptRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        invoice_id: int,
        attempt_no: int,
        status: str,
        failure_reason: Optional[str],
        next_retry_at: Optional[datetime],
    ) -> int:
        raise NotImplementedError("Day 3: implement PaymentAttemptRepository.add")

    def list_for_invoice(self, invoice_id: int) -> list[dict]:
        raise NotImplementedError("Day 3: implement PaymentAttemptRepository.list_for_invoice")


    def count_for_invoice(self, invoice_id: int) -> int:
        raise NotImplementedError("Day 3: implement PaymentAttemptRepository.count_for_invoice")
