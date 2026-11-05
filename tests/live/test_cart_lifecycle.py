"""Deterministic proof that the browser automation works against the real shop.

Run with `pytest -m live`. Nothing here orders: checkout is blocked at the network level.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress

import pytest
from playwright.sync_api import Error as PlaywrightError

from vicocart.config import Credentials
from vicocart.site import SiteError, VicoSite

pytestmark = pytest.mark.live

PRODUCT_ID = 191
PRODUCT_URL = "https://vicofoodbox.com/en/durum-wheat-pasta/191-rummo-mezzi-rigatoni-n51.html"


def _quantities(site: VicoSite) -> dict[int, int]:
    return {line.product_id: line.quantity for line in site.read_cart().lines}


def test_checkout_is_blocked(open_site: Callable[[], VicoSite]) -> None:
    site = open_site()
    with pytest.raises(PlaywrightError):
        site.page.goto("https://vicofoodbox.com/en/order")


def test_guest_cart_add_change_quantity_remove(open_site: Callable[[], VicoSite]) -> None:
    site = open_site()

    site.add_product(PRODUCT_URL, 1)
    assert _quantities(site) == {PRODUCT_ID: 1}

    site.set_quantity(PRODUCT_ID, 3)
    assert _quantities(site) == {PRODUCT_ID: 3}

    site.remove_from_cart(PRODUCT_ID)
    assert _quantities(site) == {}


def test_account_login_and_cart_round_trip(
    open_site: Callable[[], VicoSite], credentials: Credentials
) -> None:
    site = open_site()
    site.login(credentials)
    before = _quantities(site)
    if PRODUCT_ID in before:
        pytest.skip("the test product is already in this account's cart; not touching it")

    try:
        site.add_product(PRODUCT_URL, 1)
        assert _quantities(site)[PRODUCT_ID] == 1

        site.set_quantity(PRODUCT_ID, 3)
        assert _quantities(site)[PRODUCT_ID] == 3

        site.remove_from_cart(PRODUCT_ID)
        assert PRODUCT_ID not in _quantities(site)
    finally:
        with suppress(SiteError):  # already removed on the happy path
            site.remove_from_cart(PRODUCT_ID)

    assert _quantities(site) == before
