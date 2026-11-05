from __future__ import annotations

from typing import Any

import pytest

from vicocart.shopping_list import Item, ShoppingListError, parse_shopping_list

URL = "https://vicofoodbox.com/en/durum-wheat-pasta/191-rummo-mezzi-rigatoni-n51.html"


def test_parses_search_and_url_items() -> None:
    items = parse_shopping_list(
        {
            "items": [
                {"search": "rummo linguine", "require": ["500"], "quantity": 2},
                {"url": URL, "name": "Rigatoni"},
            ]
        }
    )
    assert items == [
        Item(name="rummo linguine", quantity=2, search="rummo linguine", require=("500",)),
        Item(name="Rigatoni", quantity=1, url=URL),
    ]


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"items": []},
        {"items": ["not a table"]},
        {"items": [{"quantity": 1}]},
        {"items": [{"url": URL, "search": "x"}]},
        {"items": [{"url": "https://evil.example/p.html"}]},
        {"items": [{"url": "https://vicofoodbox.com.evil.example/p.html"}]},
        {"items": [{"search": "  "}]},
        {"items": [{"search": "x", "quantity": 0}]},
        {"items": [{"search": "x", "quantity": True}]},
        {"items": [{"search": "x", "quantity": "2"}]},
        {"items": [{"search": "x", "require": "500"}]},
        {"items": [{"search": "x", "require": [500]}]},
    ],
)
def test_rejects_malformed_lists(raw: dict[str, Any]) -> None:
    with pytest.raises(ShoppingListError):
        parse_shopping_list(raw)


def test_matches_is_case_insensitive_and_requires_all_terms() -> None:
    item = Item(name="x", search="x", require=("linguine", "500"))
    assert item.matches("Rummo 13 LINGUINE - 500 gr")
    assert not item.matches("Rummo 13 Linguine - 1 kg")


def test_no_require_matches_anything() -> None:
    assert Item(name="x", search="x").matches("whatever")
