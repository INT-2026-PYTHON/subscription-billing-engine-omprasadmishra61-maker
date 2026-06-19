"""
PaymentGateway — abstract + two mock implementations.

In real life this would talk to Stripe / Razorpay / Adyen. For the project
we use mocks so tests are deterministic and the demo never hits the network.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from billing_engine.models import Invoice


@dataclass(frozen=True)
class PaymentResult:
    success: bool
    failure_reason: Optional[str] = None


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, invoice: Invoice) -> PaymentResult:
        raise NotImplementedError


# ----------------------------------------------------------------
# Scripted — for deterministic tests
# ----------------------------------------------------------------
class ScriptedGateway(PaymentGateway):
    """Returns pre-set results from a queue. Used in tests.

    Example:
        gateway = ScriptedGateway([
            PaymentResult(False, "INSUFFICIENT_FUNDS"),
            PaymentResult(False, "INSUFFICIENT_FUNDS"),
            PaymentResult(True),
        ])
    """

    def __init__(self, results: list[PaymentResult]) -> None:
        self._queue = list(results)

    def charge(self, invoice: Invoice) -> PaymentResult:
        if not self._queue:
            raise RuntimeError(
                f"ScriptedGateway exhausted — no result queued for invoice {invoice.id}"
            )
        return self._queue.pop(0)

# ----------------------------------------------------------------
# Fake-random — for the CLI demo
# ----------------------------------------------------------------
class FakeRandomGateway(PaymentGateway):
    """Succeeds at a configurable rate; seeded for reproducibility."""

    def __init__(self, success_rate: float = 0.7, seed: Optional[int] = None) -> None:
        if not 0.0 <= success_rate <= 1.0:
            raise ValueError("success_rate must be between 0.0 and 1.0")
        self.success_rate = success_rate
        self._rng = random.Random(seed)
    def charge(self, invoice: Invoice) -> PaymentResult:
        if self._rng.random() < self.success_rate:
            return PaymentResult(success=True)
        return PaymentResult(success=False, failure_reason="INSUFFICIENT_FUNDS")