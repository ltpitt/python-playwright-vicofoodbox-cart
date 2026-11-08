from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from vicocart import cli
from vicocart.config import Credentials
from vicocart.shopping_list import Item
from vicocart.site import CartLine, CartSnapshot, Product, WishlistLine

LIST_FILE = '[[items]]\nsearch = "rigatoni"\nquantity = 2\n'


class FakeShop:
    def __init__(self) -> None:
        self.wishlist: list[WishlistLine] = []
        self.cart: list[CartLine] = []
        self._current = ""

    def open_product(self, item: Item) -> Product:
        self._current = item.name
        url = "https://vicofoodbox.com/en/191-rigatoni.html"
        return Product(title="Rigatoni", url=url, price="€1.85")

    def add_to_wishlist(self) -> None:
        self.wishlist.append(WishlistLine(191, "Rigatoni", "https://x/191-r.html", "€1.85"))

    def add_to_cart(self, quantity: int) -> None:
        self.cart.append(CartLine(191, "Rigatoni", quantity))

    def read_wishlist(self) -> list[WishlistLine]:
        return self.wishlist

    def read_cart(self) -> CartSnapshot:
        return CartSnapshot(self.cart, [])


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.shop = FakeShop()
        self.opened: list[tuple[bool, Credentials | None]] = []
        self.list_file = tmp_path / "list.toml"
        self.list_file.write_text(LIST_FILE)
        monkeypatch.chdir(tmp_path)  # keep the developer's real .env out of the test
        for name in ("VICO_EMAIL", "VICO_PASSWORD", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(cli, "_open_site", self._open_site)

    @contextmanager
    def _open_site(self, *, headed: bool, credentials: Credentials | None) -> Iterator[FakeShop]:
        self.opened.append((headed, credentials))
        yield self.shop


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Harness:
    return Harness(monkeypatch, tmp_path)


def _login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VICO_EMAIL", "me@example.com")
    monkeypatch.setenv("VICO_PASSWORD", "pw")


def test_list_saves_to_the_wishlist_and_prints_links_and_next_step(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _login(monkeypatch)

    assert cli.main(["list", str(harness.list_file)]) == 0

    out = capsys.readouterr().out
    link = "https://vicofoodbox.com/en/191-rigatoni.html"
    assert f"wishlisted Rigatoni (€1.85), want 2: {link}" in out
    assert "Wishlist now contains:" in out
    assert "https://vicofoodbox.com/en/wishlist" in out
    assert harness.shop.cart == []


def test_list_without_an_account_is_refused(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["list", str(harness.list_file)]) == 2

    assert "the wishlist needs your account" in capsys.readouterr().err
    assert harness.opened == []


def test_list_dry_run_needs_no_account_and_logs_in_nowhere(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["list", "--dry-run", str(harness.list_file)]) == 0

    assert "found Rigatoni" in capsys.readouterr().out
    assert harness.opened == [(False, None)]
    assert harness.shop.wishlist == []


def test_cart_needs_a_visible_browser(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _login(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_API_KEY", "k")

    assert cli.main(["list", "--cart", str(harness.list_file)]) == 2
    assert "--headed" in capsys.readouterr().err
    assert cli.main(["ask", "pasta for two"]) == 2
    assert "--headed" in capsys.readouterr().err
    assert harness.opened == []


def test_headed_cart_run_fills_the_cart(
    harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _login(monkeypatch)

    assert cli.main(["list", "--cart", "--headed", str(harness.list_file)]) == 0

    assert "added 2 x Rigatoni" in capsys.readouterr().out
    assert harness.shop.cart == [CartLine(191, "Rigatoni", 2)]
    assert harness.shop.wishlist == []
