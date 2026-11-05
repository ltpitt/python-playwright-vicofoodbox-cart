from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHOP_ORIGIN = "https://vicofoodbox.com/"


class ShoppingListError(ValueError):
    """The shopping list file is malformed."""


@dataclass(frozen=True)
class Item:
    name: str
    quantity: int = 1
    url: str | None = None
    search: str | None = None
    require: tuple[str, ...] = ()

    def matches(self, title: str) -> bool:
        """True when the product title contains every required term."""
        folded = title.casefold()
        return all(term.casefold() in folded for term in self.require)


def load_shopping_list(path: Path) -> list[Item]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ShoppingListError(f"{path}: invalid TOML: {exc}") from exc
    return parse_shopping_list(data)


def parse_shopping_list(data: Mapping[str, Any]) -> list[Item]:
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ShoppingListError("shopping list needs at least one [[items]] entry")
    return [_parse_item(index, raw) for index, raw in enumerate(raw_items, start=1)]


def _parse_item(index: int, raw: object) -> Item:
    where = f"items[{index}]"
    if not isinstance(raw, dict):
        raise ShoppingListError(f"{where}: must be a table")

    url = raw.get("url")
    search = raw.get("search")
    if (url is None) == (search is None):
        raise ShoppingListError(f"{where}: set exactly one of 'url' or 'search'")
    if url is not None and not (isinstance(url, str) and url.startswith(SHOP_ORIGIN)):
        raise ShoppingListError(f"{where}: 'url' must start with {SHOP_ORIGIN}")
    if search is not None and not (isinstance(search, str) and search.strip()):
        raise ShoppingListError(f"{where}: 'search' must be a non-empty string")

    quantity = raw.get("quantity", 1)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ShoppingListError(f"{where}: 'quantity' must be an integer >= 1")

    require = raw.get("require", [])
    if not _is_str_sequence(require):
        raise ShoppingListError(f"{where}: 'require' must be a list of strings")

    name = raw.get("name") or search or url
    return Item(
        name=str(name),
        quantity=quantity,
        url=url,
        search=search.strip() if search else None,
        require=tuple(require),
    )


def _is_str_sequence(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, str)
        and all(isinstance(v, str) for v in value)
    )
