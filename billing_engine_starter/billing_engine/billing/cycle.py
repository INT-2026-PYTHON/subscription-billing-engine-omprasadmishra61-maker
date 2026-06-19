"""
BillingCycle — finds due subscriptions, generates invoices, posts ledger DEBITs,
advances the subscription period. Must be IDEMPOTENT (safe to run twice).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from billing_engine.db import (
    Database,
    CustomerRepository, PlanRepository, SubscriptionRepository,
    UsageRecordRepository, InvoiceRepository, InvoiceLineItemRepository,
    LedgerRepository,
)
from billing_engine.models import Subscription


@dataclass
class BillingResult:
    invoices_created: int
    invoices_skipped_duplicate: int
    trials_activated: int


class BillingCycle:
    """Day-3 deliverable. Day-4 stretch: add `upgrade_subscription(...)`."""

    def __init__(
        self,
        db: Database,
        customer_repo: CustomerRepository,
        plan_repo: PlanRepository,
        subscription_repo: SubscriptionRepository,
        usage_repo: UsageRecordRepository,
        invoice_repo: InvoiceRepository,
        line_item_repo: InvoiceLineItemRepository,
        ledger_repo: LedgerRepository,
        strategy_factory: Callable,    # given a Plan, returns a PricingStrategy
        discount_factory: Callable,    # given a discount_id or None, returns a Discount or None
        tax_factory: Callable,         # given a Customer, returns (TaxCalculator, TaxContext)
    ) -> None:
        self.db = db
        self.customer_repo = customer_repo
        self.plan_repo = plan_repo
        self.subscription_repo = subscription_repo
        self.usage_repo = usage_repo
        self.invoice_repo = invoice_repo
        self.line_item_repo = line_item_repo
        self.ledger_repo = ledger_repo
        self.strategy_factory = strategy_factory
        self.discount_factory = discount_factory
        self.tax_factory = tax_factory

    # --------------------------------------------------------
    def run(self, as_of: date) -> BillingResult:
        """Bill all subscriptions whose current period ends on or before `as_of`."""
        invoices_created = 0
        invoices_skipped_duplicate = 0
        trials_activated = 0

        # Step 1 — promote expired trials to ACTIVE
        for sub in self.subscription_repo.list_all():
            if (
                sub.status == SubscriptionStatus.TRIAL
                and sub.trial_end is not None
                and sub.trial_end <= as_of
            ):
                self.subscription_repo.update_status(sub.id, SubscriptionStatus.ACTIVE)
                trials_activated += 1

        # Step 2 — bill all due active subscriptions
        for sub in self.subscription_repo.get_due_for_billing(as_of):
            plan     = self.plan_repo.get(sub.plan_id)
            customer = self.customer_repo.get(sub.customer_id)

            strategy              = self.strategy_factory(plan)
            discount              = self.discount_factory(sub.discount_id)
            tax_calc, tax_context = self.tax_factory(customer)

            usage_quantity = self.usage_repo.sum_for_period(
                sub.id, "api_calls",
                sub.current_period_start,
                sub.current_period_end,
            )
            invoice_count = self.invoice_repo.count_for_subscription(sub.id)

            draft = build_invoice(
                subscription=sub,
                plan=plan,
                strategy=strategy,
                discount=discount,
                tax_calc=tax_calc,
                tax_context=tax_context,
                usage_quantity=usage_quantity,
                period_start=sub.current_period_start,
                period_end=sub.current_period_end,
                invoice_count_so_far=invoice_count,
            )

            try:
                with self.db.transaction() as conn:
                    saved = self.invoice_repo.add(draft)

                    for item in draft.line_items:
                        self.line_item_repo.add(InvoiceLineItem(
                            id=None,
                            invoice_id=saved.id,
                            kind=item.kind,
                            description=item.description,
                            amount=item.amount,
                        ))

                    self.ledger_repo.add(LedgerEntry(
                        id=None,
                        customer_id=sub.customer_id,
                        invoice_id=saved.id,
                        direction=LedgerDirection.DEBIT,
                        amount=saved.total,
                        description=f"Invoice #{saved.id} — {plan.name}",
                        created_at=as_of,
                    ))

                    new_start = sub.current_period_end
                    new_end   = new_start + relativedelta(months=1)
                    self.subscription_repo.update_period(sub.id, new_start, new_end)

                invoices_created += 1

            except sqlite3.IntegrityError:
                invoices_skipped_duplicate += 1
            return BillingResult(invoices_created, invoices_skipped_duplicate, trials_activated)


    # --------------------------------------------------------
    def upgrade_subscription(self, subscription_id: int, new_plan_id: int, switch_date: date) -> None:
        """Mid-cycle upgrade — Day 4 stretch."""
        sub      = self.subscription_repo.get(subscription_id)
        customer = self.customer_repo.get(sub.customer_id)
        old_plan = self.plan_repo.get(sub.plan_id)
        new_plan = self.plan_repo.get(new_plan_id)

        strategy_old   = self.strategy_factory(old_plan)
        strategy_new   = self.strategy_factory(new_plan)
        tax_calc, tax_context = self.tax_factory(customer)

        # Price for a full period of each plan (quantity=0 for flat-rate)
        old_price = strategy_old.calculate(0)
        new_price = strategy_new.calculate(0)

        proration = compute_proration(
            old_plan_price=old_price,
            new_plan_price=new_price,
            period_start=sub.current_period_start,
            period_end=sub.current_period_end,
            switch_date=switch_date,
            tax_calc=tax_calc,
            tax_context=tax_context,
        )

        # Net charge = (new charge + new tax) - (old credit + old credit tax)
        net_total = (
            (proration.charge_amount + proration.charge_tax)
            - (proration.credit_amount + proration.credit_tax)
        )

        line_items = [
            InvoiceLineItem(
                id=None, invoice_id=None,
                kind=LineItemKind.PRORATION_CREDIT,
                description=f"Unused time on {old_plan.name} from {switch_date} to {sub.current_period_end}",
                amount=proration.credit_amount,
            ),
            InvoiceLineItem(
                id=None, invoice_id=None,
                kind=LineItemKind.PRORATION_CHARGE,
                description=f"Remaining time on {new_plan.name} from {switch_date} to {sub.current_period_end}",
                amount=proration.charge_amount,
            ),
        ]

        proration_invoice = Invoice(
            id=None,
            subscription_id=sub.id,
            period_start=switch_date,
            period_end=sub.current_period_end,
            status=InvoiceStatus.DRAFT,
            subtotal=proration.charge_amount - proration.credit_amount,
            discount_amount=Money.zero(old_price.currency),
            tax_amount=proration.charge_tax - proration.credit_tax,
            total=net_total,
            currency=old_price.currency,
            issued_at=switch_date,
            line_items=line_items,
        )

        with self.db.transaction() as conn:
            saved = self.invoice_repo.add(proration_invoice)

            for item in line_items:
                self.line_item_repo.add(InvoiceLineItem(
                    id=None,
                    invoice_id=saved.id,
                    kind=item.kind,
                    description=item.description,
                    amount=item.amount,
                ))

            self.ledger_repo.add(LedgerEntry(
                id=None,
                customer_id=sub.customer_id,
                invoice_id=saved.id,
                direction=LedgerDirection.DEBIT,
                amount=saved.total,
                description=f"Proration: {old_plan.name} → {new_plan.name} on {switch_date}",
                created_at=switch_date,
            ))

            self.subscription_repo.update_plan(sub.id, new_plan_id)
