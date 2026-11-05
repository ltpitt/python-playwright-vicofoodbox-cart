from __future__ import annotations

from decimal import Decimal

import pytest

from vicocart.site import Listing, _parse_price, _product_id


@pytest.mark.parametrize(
    ("text", "expected"),
    [("€1.45", Decimal("1.45")), ("€ 12.80", Decimal("12.80")), ("€1,234.50", Decimal("1234.50"))],
)
def test_parse_price(text: str, expected: Decimal) -> None:
    assert _parse_price(text) == expected


@pytest.mark.parametrize("text", ["", "  ", "Price"])
def test_parse_price_without_a_number(text: str) -> None:
    assert _parse_price(text) is None


def test_product_id_comes_from_the_url() -> None:
    url = "https://vicofoodbox.com/en/tomato-passata-chopped-whole/2024-rosso-gargano-pomodori-pelati-400-gr.html"
    assert _product_id(url) == 2024


def test_product_id_missing() -> None:
    assert _product_id("https://vicofoodbox.com/en/cart") is None


def test_on_sale_needs_a_higher_regular_price() -> None:
    def listing(price: str | None, regular: str | None) -> Listing:
        return Listing(
            1,
            "x",
            "u",
            None if price is None else Decimal(price),
            None if regular is None else Decimal(regular),
        )

    assert listing("1.45", "1.85").on_sale
    assert not listing("1.45", None).on_sale
    assert not listing("1.45", "1.45").on_sale
    assert not listing(None, "1.85").on_sale
