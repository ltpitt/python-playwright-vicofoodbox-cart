from __future__ import annotations

from vicocart.runner import Target, add_items
from vicocart.shopping_list import Item
from vicocart.site import Product, SiteError


class FakeSite:
    def __init__(self, failing: set[str]) -> None:
        self.failing = failing
        self.added: list[tuple[str, int]] = []
        self.wishlisted: list[str] = []
        self._current = ""

    def open_product(self, item: Item) -> Product:
        self._current = item.name
        return Product(title=item.name, url="https://vicofoodbox.com/p", price="€1.00")

    def add_to_cart(self, quantity: int) -> None:
        if self._current in self.failing:
            raise SiteError("You can buy a maximum of 2 pack at this price")
        self.added.append((self._current, quantity))

    def add_to_wishlist(self) -> None:
        if self._current in self.failing:
            raise SiteError("the wishlist needs a logged-in account")
        self.wishlisted.append(self._current)


def _items() -> list[Item]:
    return [
        Item(name="a", quantity=1, search="a"),
        Item(name="b", quantity=5, search="b"),
        Item(name="c", quantity=3, search="c"),
    ]


def test_one_failure_does_not_stop_the_rest() -> None:
    site = FakeSite(failing={"b"})
    outcomes = add_items(site, _items(), target="cart")
    assert [o.ok for o in outcomes] == [True, False, True]
    assert outcomes[1].error == "You can buy a maximum of 2 pack at this price"
    assert site.added == [("a", 1), ("c", 3)]


def test_dry_run_never_adds() -> None:
    site = FakeSite(failing=set())
    targets: tuple[Target, ...] = ("wishlist", "cart")
    for target in targets:
        outcomes = add_items(site, _items(), target=target, dry_run=True)
        assert all(o.ok and o.product for o in outcomes)
    assert site.added == []
    assert site.wishlisted == []


def test_wishlist_target_saves_products_and_leaves_the_cart_alone() -> None:
    site = FakeSite(failing={"b"})
    outcomes = add_items(site, _items(), target="wishlist")
    assert [o.ok for o in outcomes] == [True, False, True]
    assert site.wishlisted == ["a", "c"]
    assert site.added == []
