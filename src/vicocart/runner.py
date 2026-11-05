from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from playwright.sync_api import Error as PlaywrightError

from vicocart.shopping_list import Item
from vicocart.site import Product, SiteError


class Site(Protocol):
    def open_product(self, item: Item) -> Product: ...

    def add_to_cart(self, quantity: int) -> None: ...


@dataclass(frozen=True)
class Outcome:
    item: Item
    product: Product | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def fill_cart(site: Site, items: Sequence[Item], *, dry_run: bool = False) -> list[Outcome]:
    """Add every item; a failing item is recorded and does not stop the rest."""
    outcomes: list[Outcome] = []
    for item in items:
        product: Product | None = None
        try:
            product = site.open_product(item)
            if not dry_run:
                site.add_to_cart(item.quantity)
        except (SiteError, PlaywrightError) as exc:
            outcomes.append(Outcome(item, product, error=str(exc).splitlines()[0]))
        else:
            outcomes.append(Outcome(item, product))
    return outcomes
