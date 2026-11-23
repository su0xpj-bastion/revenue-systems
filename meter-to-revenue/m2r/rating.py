"""Usage rating, plus an independently written re-rater the accuracy control uses.

`rate_usage` walks the tiers in order. `rerate_independently` computes each tier's band with
min/max arithmetic and no shared code, so a bug in one is unlikely to be repeated in the other.
"""
from __future__ import annotations

from decimal import Decimal

from .model import Product


def rate_usage(product: Product, quantity: Decimal) -> Decimal:
    if quantity <= 0:
        return Decimal(0)
    if product.tier_mode == "volume":
        for tier in product.tiers:
            if tier.up_to is None or quantity <= tier.up_to:
                return quantity * tier.unit_price
    total, lower = Decimal(0), Decimal(0)
    for tier in product.tiers:
        if tier.up_to is None or quantity <= tier.up_to:
            return total + (quantity - lower) * tier.unit_price
        total += (tier.up_to - lower) * tier.unit_price
        lower = tier.up_to
    raise ValueError("quantity beyond last tier")


def rerate_independently(product: Product, quantity: Decimal) -> Decimal:
    bounds = [t.up_to for t in product.tiers]
    lowers = [Decimal(0)] + [b for b in bounds[:-1]]
    if product.tier_mode == "volume":
        index = next(i for i, b in enumerate(bounds) if b is None or quantity <= b)
        return max(quantity, Decimal(0)) * product.tiers[index].unit_price
    return sum(
        (max(Decimal(0), min(quantity, upper if upper is not None else quantity) - lower) * t.unit_price
         for t, lower, upper in zip(product.tiers, lowers, bounds)),
        Decimal(0),
    )
