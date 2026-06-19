"""
TieredPricing — different price per unit depending on the tier the quantity falls into.

This is the "cumulative" / "stacked" tier model, NOT the "volume" model:
    Tiers: [(0, 1000, ₹2.00), (1000, 5000, ₹1.50), (5000, None, ₹1.00)]
    Quantity = 6000:
        First 1000 units  @ ₹2.00 = ₹2000
        Next  4000 units  @ ₹1.50 = ₹6000
        Last  1000 units  @ ₹1.00 = ₹1000
        ------------------------------------
        Total                     = ₹9000

A tier with `to_units = None` is the open-ended top tier.

Tier boundaries are HALF-OPEN on the right: a tier (from, to, price)
covers units strictly less than `to` (i.e. [from, to)).
"""

from dataclasses import dataclass
from typing import Optional

from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy


@dataclass(frozen=True)
class Tier:
    from_units: int
    to_units: Optional[int]   # None means "unlimited" / open-ended
    unit_price: Money


class TieredPricing(PricingStrategy):
    """Charges across multiple price tiers based on cumulative quantity."""

    def __init__(self, tiers: list[Tier]) -> None:
        if not tiers:
            raise ValueError("tiers must not be empty")
        for i in range(len(tiers) - 1):
            if tiers[i].to_units is None:
                raise ValueError("only the last tier can have to_units=None")
            if tiers[i + 1].from_units != tiers[i].to_units:
                raise ValueError(f"tiers are not contiguous at index {i}")
        if any(t.to_units is None for t in tiers[:-1]):
            raise ValueError("only the last tier can have to_units=None")
        currency = tiers[0].unit_price.currency
        for t in tiers:
            if t.unit_price.currency != currency:
                raise ValueError("all tier unit_prices must share the same currency")
        self.tiers = tiers

    def calculate(self, quantity: int) -> Money:
        if quantity < 0:
            raise ValueError("quantity must not be negative")
        currency = self.tiers[0].unit_price.currency
        total = Money.zero(currency)
        for tier in self.tiers:
            if quantity <= tier.from_units:
                break
            if tier.to_units is None:
                units_in_tier = quantity - tier.from_units
            else:
                units_in_tier = min(quantity, tier.to_units) - tier.from_units
            total = total + tier.unit_price * units_in_tier
        return total
