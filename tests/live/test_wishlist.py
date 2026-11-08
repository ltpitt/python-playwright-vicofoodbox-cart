"""Proof that the wishlist, unlike a cart, survives into a brand-new browser session.

Run with `pytest -m live`. Nothing here orders: checkout is blocked at the network level.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress

import pytest

from vicocart.config import Credentials
from vicocart.site import SiteError, VicoSite

pytestmark = pytest.mark.live

PRODUCT_ID = 191
PRODUCT_URL = "https://vicofoodbox.com/en/durum-wheat-pasta/191-rummo-mezzi-rigatoni-n51.html"


def _ids(site: VicoSite) -> set[int]:
    return {line.product_id for line in site.read_wishlist()}


def test_guest_cannot_use_the_wishlist(open_site: Callable[[], VicoSite]) -> None:
    site = open_site()
    site.page.goto(PRODUCT_URL, wait_until="domcontentloaded")
    with pytest.raises(SiteError, match="logged-in account"):
        site.add_to_wishlist()


def test_wishlist_is_visible_after_a_new_login(
    open_site: Callable[[], VicoSite], credentials: Credentials
) -> None:
    first = open_site()
    first.login(credentials)
    if PRODUCT_ID in _ids(first):
        pytest.skip("the test product is already on this account's wishlist; not touching it")

    try:
        first.page.goto(PRODUCT_URL, wait_until="domcontentloaded")
        first.add_to_wishlist()
        first.add_to_wishlist()  # saving twice must not fail
        assert PRODUCT_ID in _ids(first)

        second = open_site()  # a fresh browser: a cart would be gone here
        second.login(credentials)
        assert PRODUCT_ID in _ids(second)
    finally:
        with suppress(SiteError):  # nothing to remove if the add never happened
            first.remove_from_wishlist(PRODUCT_ID)

    assert PRODUCT_ID not in _ids(first)
