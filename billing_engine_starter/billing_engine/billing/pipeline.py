"""
build_invoice — PURE function that turns inputs into an Invoice dataclass.

⚠️ NO database calls here. No `datetime.now()`. No PDF. Just math.

The order is FIXED:
    1. base       = strategy.calculate(usage)
    2. discount   = discount.apply(base) if discount else 0
    3. taxable    = base - discount
    4. tax        = tax_calc.apply(taxable)
    5. total      = taxable + tax.total
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from billing_engine.money import Money
from billing_engine.models import (
    Invoice, InvoiceStatus, InvoiceLineItem, LineItemKind, Subscription, Plan,
)
from billing_engine.pricing.base import PricingStrategy
from billing_engine.discounts.base import Discount, DiscountContext
from billing_engine.taxes.base import TaxCalculator, TaxContext


def build_invoice(
    subscription: Subscription,
    plan: Plan,
    strategy: PricingStrategy,
    discount: Optional[Discount],
    tax_calc: TaxCalculator,
    tax_context: TaxContext,
    usage_quantity: int,
    period_start: date,
    period_end: date,
    invoice_count_so_far: int,
) -> Invoice:
    """Pure function. Returns an Invoice (id=None, status=DRAFT) ready to be persisted."""

    base = strategy.calculate(usage_quantity)

    discount_context = DiscountContext(invoice_count_so_far=invoice_count_so_far)
    discount_amount = (
        discount.apply(base, discount_context)
        if discount is not None
        else Money.zero(base.currency)
    )

    taxable = base - discount_amount


    tax_breakdown = tax_calc.apply(taxable, tax_context)

    total = taxable + tax_breakdown.total

    line_items = []

    line_items.append(InvoiceLineItem(
        id=None,
        invoice_id=None,
        kind=LineItemKind.BASE,
        description=f"{plan.name} — {period_start} to {period_end}",
        amount=base,
    ))

    if discount_amount != Money.zero(base.currency):
        line_items.append(InvoiceLineItem(
            id=None,
            invoice_id=None,
            kind=LineItemKind.DISCOUNT,
            description="Discount",
            amount=discount_amount,
        ))

    for label, amount in tax_breakdown.components:
        line_items.append(InvoiceLineItem(
            id=None,
            invoice_id=None,
            kind=LineItemKind.TAX,
            description=label,
            amount=amount,
        ))

    return Invoice(
        id=None,
        subscription_id=subscription.id,
        period_start=period_start,
        period_end=period_end,
        status=InvoiceStatus.DRAFT,
        subtotal=base,
        discount_amount=discount_amount,
        tax_amount=tax_breakdown.total,
        total=total,
        currency=base.currency,
        issued_at=None,
        line_items=line_items,
    )