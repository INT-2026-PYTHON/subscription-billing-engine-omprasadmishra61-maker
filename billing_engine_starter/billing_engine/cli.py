"""
CLI entrypoint.

Subcommands to implement (Day 4):
    billing init                              -- create / migrate the DB
    billing customer add <name> <email> <country> [--state CODE]
    billing plan list
    billing subscribe <customer_id> <plan_id> [--trial-days N] [--discount CODE]
    billing bill run [--date YYYY-MM-DD]
    billing invoice show <invoice_id>          -- prints PLAIN TEXT invoice
    billing upgrade <subscription_id> <new_plan_id> [--date YYYY-MM-DD]   (STRETCH)
    billing demo                              -- run the scripted scenario

Use argparse with subparsers. Keep each subcommand handler in its own function.

PDF rendering is OUT OF SCOPE for the core project — `invoice show` should
print a clean PLAIN-TEXT invoice (see helper `format_invoice_text` below).
PDF generation is BONUS: see `billing_engine/pdf/renderer.py`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from billing_engine.models import Invoice


def format_invoice_text(invoice: Invoice, customer_name: str, plan_name: str) -> str:
    """Render an invoice as a plain-text receipt. Pure function — easy to test."""
    WIDTH = 60
    CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€"}
    sym = CURRENCY_SYMBOLS.get(invoice.currency, invoice.currency + " ")

    def money_col(amount: Money) -> str:
        return f"{sym} {str(amount.amount):>10}"

    lines = []
    lines.append(f"INVOICE #{invoice.id}")
    lines.append("=" * WIDTH)
    lines.append(f"{'Customer:':<12}{customer_name}")
    lines.append(f"{'Plan:':<12}{plan_name}")
    lines.append(f"{'Period:':<12}{invoice.period_start} to {invoice.period_end}")
    lines.append("-" * WIDTH)

    for item in invoice.line_items:
        lines.append(f"{item.description:<45}{money_col(item.amount)}")

    lines.append("-" * WIDTH)
    lines.append(f"{'TOTAL':<45}{money_col(invoice.total)}")
    lines.append(f"Status: {invoice.status.value}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="billing", description="Subscription Billing CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)
    parser = argparse.ArgumentParser(prog="billing", description="Subscription Billing CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="initialise the database")


    p_cust = sub.add_parser("customer", help="customer commands")
    cust_sub = p_cust.add_subparsers(dest="customer_cmd", required=True)
    p_add = cust_sub.add_parser("add", help="add a new customer")
    p_add.add_argument("name")
    p_add.add_argument("email")
    p_add.add_argument("country")
    p_add.add_argument("--state", default="")


    p_plan = sub.add_parser("plan", help="plan commands")
    plan_sub = p_plan.add_subparsers(dest="plan_cmd", required=True)
    plan_sub.add_parser("list", help="list all plans")

    
    p_sub = sub.add_parser("subscribe", help="subscribe a customer to a plan")
    p_sub.add_argument("customer_id", type=int)
    p_sub.add_argument("plan_id", type=int)
    p_sub.add_argument("--trial-days", type=int, default=0)
    p_sub.add_argument("--discount", default=None)

    
    p_bill = sub.add_parser("bill", help="billing commands")
    bill_sub = p_bill.add_subparsers(dest="bill_cmd", required=True)
    p_run = bill_sub.add_parser("run", help="run the billing cycle")
    p_run.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")

    
    p_inv = sub.add_parser("invoice", help="invoice commands")
    inv_sub = p_inv.add_subparsers(dest="invoice_cmd", required=True)
    p_show = inv_sub.add_parser("show", help="print an invoice")
    p_show.add_argument("invoice_id", type=int)


    sub.add_parser("demo", help="run the scripted demo scenario")

    args = parser.parse_args(argv)

    dispatch = {
        "init":    cmd_init,
        "demo":    lambda _: run_demo(),
    }

    if args.cmd == "customer" and args.customer_cmd == "add":
        return cmd_customer_add(args)
    if args.cmd == "plan" and args.plan_cmd == "list":
        return cmd_plan_list(args)
    if args.cmd == "subscribe":
        return cmd_subscribe(args)
    if args.cmd == "bill" and args.bill_cmd == "run":
        return cmd_bill_run(args)
    if args.cmd == "invoice" and args.invoice_cmd == "show":
        return cmd_invoice_show(args)
    if args.cmd in dispatch:
        return dispatch[args.cmd](args)

    print(f"Unknown command: {args.cmd}", file=sys.stderr)
    return 2
   

def run_demo() -> int:
    """Scripted end-to-end scenario for the `demo` subcommand.

    Should mirror `tests/test_demo_scenario.py::TestEndToEndScenario::test_full_lifecycle`
    and print a human-readable summary to stdout.
    """
    db_path = tempfile.mktemp(suffix=".db")
    db = Database(db_path)
    db.init_schema()

    customer_repo  = CustomerRepository(db)
    plan_repo      = PlanRepository(db)
    plan_tier_repo = PlanTierRepository(db)
    sub_repo       = SubscriptionRepository(db)
    usage_repo     = UsageRecordRepository(db)
    invoice_repo   = InvoiceRepository(db)
    line_item_repo = InvoiceLineItemRepository(db)
    ledger_repo    = LedgerRepository(db)
    discount_repo  = DiscountRepository(db)

    print("=" * 60)
    print("BILLING ENGINE — DEMO SCENARIO")
    print("=" * 60)

    customer = customer_repo.add(Customer(None, "Priya Sharma", "priya@example.com", "IN", "MH"))
    plan     = plan_repo.add(Plan(None, "Pro", PricingType.FLAT, BillingPeriod.MONTHLY, "INR"))
    plan_tier_repo.add(plan.id, 0, None, Money("999", "INR"))
    print(f"Customer : #{customer.id} {customer.name}")
    print(f"Plan     : #{plan.id} {plan.name} — ₹999/month")

    today = date(2026, 1, 1)
    sub = sub_repo.add(Subscription(
        None, customer.id, plan.id, SubscriptionStatus.ACTIVE,
        today, date(2026, 2, 1), None, None, None,
    ))
    print(f"Subscription #{sub.id} created (ACTIVE)")

    cycle  = _make_cycle(db, customer_repo, plan_repo, plan_tier_repo,
                         sub_repo, usage_repo, invoice_repo, line_item_repo,
                         ledger_repo, discount_repo)
    result = cycle.run(today)
    print(f"\nBilling run → created={result.invoices_created}  skipped={result.invoices_skipped_duplicate}")

    invs = [invoice_repo.get(i) for i in range(1, 10) if invoice_repo.get(i)
            and invoice_repo.get(i).subscription_id == sub.id]
    if invs:
        inv = invs[0]
        inv.line_items = line_item_repo.list_for_invoice(inv.id)
        print("\n" + format_invoice_text(inv, customer.name, plan.name))

    result2 = cycle.run(today)
    print(f"\nRe-run (idempotency) → created={result2.invoices_created}  skipped={result2.invoices_skipped_duplicate}")

    os.unlink(db_path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
