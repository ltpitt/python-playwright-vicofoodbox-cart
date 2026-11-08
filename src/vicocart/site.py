from __future__ import annotations

import re
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import Locator, Page, Response
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from vicocart.config import Credentials
from vicocart.shopping_list import Item

BASE_URL = "https://vicofoodbox.com/en"
WISHLIST_URL = f"{BASE_URL}/wishlist"
TIMEOUT_MS = 15_000
# Checkout lives at /en/order. Aborting it makes "never orders" a guarantee, not a promise.
CHECKOUT_URL = re.compile(r"/en/order(\?|#|$)")


class SiteError(RuntimeError):
    """The shop refused an action or did not look the way we expect."""


@dataclass(frozen=True)
class Product:
    title: str
    url: str
    price: str


@dataclass(frozen=True)
class Listing:
    """One search result. `price` is None when the shop shows none (usually unavailable)."""

    id: int
    title: str
    url: str
    price: Decimal | None
    regular_price: Decimal | None

    @property
    def on_sale(self) -> bool:
        return (
            self.price is not None
            and self.regular_price is not None
            and self.regular_price > self.price
        )


@dataclass(frozen=True)
class CartLine:
    product_id: int
    name: str
    quantity: int


@dataclass(frozen=True)
class CartSnapshot:
    lines: list[CartLine]
    notices: list[str]


@dataclass(frozen=True)
class WishlistLine:
    product_id: int
    name: str
    url: str
    price: str


class VicoSite:
    """Drives vicofoodbox.com (PrestaShop). Stops at the cart; it never checks out."""

    def __init__(self, page: Page) -> None:
        self.page = page
        page.set_default_timeout(TIMEOUT_MS)
        page.context.route(CHECKOUT_URL, lambda route: route.abort())

    def dismiss_cookies(self) -> None:
        self.page.goto(BASE_URL, wait_until="domcontentloaded")
        with suppress(PlaywrightTimeout):  # banner is absent once consent is stored
            self.page.get_by_role("button", name="Reject All").first.click(timeout=5_000)

    def login(self, credentials: Credentials) -> None:
        page = self.page
        page.goto(f"{BASE_URL}/my-account", wait_until="domcontentloaded")
        page.click("#opc-login-link")
        # Clicking the link clones the form; the original stays hidden in the DOM.
        page.fill("#txt-login_email:visible", credentials.email)
        page.fill("#txt-login_password:visible", credentials.password)
        page.click("#btn-opc_login:visible")
        try:
            page.locator("a[href*='mylogout']").first.wait_for(state="attached")
        except PlaywrightTimeout as exc:
            alert = page.locator(".alert-danger:visible").first
            reason = (
                _squash(alert.inner_text())
                if alert.count()
                else "check VICO_EMAIL and VICO_PASSWORD"
            )
            raise SiteError(f"login failed: {reason}") from exc

    def open_product(self, item: Item) -> Product:
        """Navigate to the product page for an item and return what is on it."""
        url = item.url or self._search(item)
        self.page.goto(url, wait_until="domcontentloaded")
        title = _squash(self.page.locator("h1").first.inner_text())
        price_box = self.page.locator(".current-price-value").first
        price = _squash(price_box.inner_text()) if price_box.count() else "?"
        return Product(title=title, url=url, price=price)

    def search(self, query: str, limit: int = 10) -> list[Listing]:
        self.page.goto(
            f"{BASE_URL}/search?controller=search&s={quote_plus(query)}",
            wait_until="domcontentloaded",
        )
        cards = self.page.locator("article.product-miniature")
        try:
            cards.first.wait_for()
        except PlaywrightTimeout:
            return []
        raw_cards = cards.evaluate_all(_READ_CARDS_JS)
        listings = []
        for raw in raw_cards[:limit]:
            product_id = _product_id(raw["href"])
            if product_id is not None:
                listings.append(
                    Listing(
                        id=product_id,
                        title=_squash(raw["title"]),
                        url=raw["href"],
                        price=_parse_price(raw["price"]),
                        regular_price=_parse_price(raw["regular"]),
                    )
                )
        return listings

    def add_product(self, url: str, quantity: int) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        self.add_to_cart(quantity)

    def add_to_cart(self, quantity: int) -> None:
        """Add the product on the current page; raises SiteError with the shop's reason."""
        page = self.page
        button = page.locator("#add-to-cart-or-refresh button.add-to-cart")
        if button.count() == 0 or button.is_disabled():
            raise SiteError("cannot be added (out of stock, or not a product page)")
        page.fill("#quantity_wanted", str(quantity))
        with page.expect_response(_is_cart_update) as response_info:
            button.click()
        _raise_unless_success(response_info.value)

    def set_quantity(self, product_id: int, quantity: int) -> None:
        """Set an existing cart line to `quantity` (>= 1) on the cart page."""
        if quantity < 1:
            raise ValueError("quantity must be >= 1; use remove_from_cart to drop a line")
        field = self._cart_row(product_id).locator("input.js-cart-line-product-quantity").first
        if field.input_value() == str(quantity):
            return
        field.fill(str(quantity))
        with self.page.expect_response(_is_cart_line_update) as response_info:
            field.press("Tab")  # the shop updates the cart on the input's change event
        _raise_unless_success(response_info.value)

    def remove_from_cart(self, product_id: int) -> None:
        row = self._cart_row(product_id)
        with self.page.expect_response(_is_cart_line_delete) as response_info:
            row.locator("a.remove-from-cart").first.click()
        _raise_unless_success(response_info.value)

    def read_cart(self) -> CartSnapshot:
        page = self.page
        page.goto(f"{BASE_URL}/cart?action=show", wait_until="domcontentloaded")
        lines = []
        # The shop injects a free "Vico Gift" line; it is not something we added.
        for row in page.locator("li.cart-item:not(.mdgift-item)").all():
            product_id = int(
                row.locator("a.remove-from-cart").first.get_attribute("data-id-product") or 0
            )
            name = _squash(row.locator("a.label").first.inner_text())
            quantity = int(row.locator("input.js-cart-line-product-quantity").first.input_value())
            lines.append(CartLine(product_id=product_id, name=name, quantity=quantity))
        notices = [
            _squash(box.inner_text())
            for box in page.locator("#cgma_errors").all()
            if box.is_visible()
        ]
        return CartSnapshot(lines=lines, notices=notices)

    def add_to_wishlist(self) -> None:
        """Save the product on the current page to the account wishlist (saving twice is fine)."""
        page = self.page
        button = page.locator(".btn-iqitwishlist-add").first
        if button.count() == 0:
            raise SiteError("cannot be saved (not a product page)")
        with page.expect_response(_is_wishlist_action) as response_info:
            button.click()
        _check_wishlist_add(response_info.value.json())

    def read_wishlist(self) -> list[WishlistLine]:
        self.page.goto(WISHLIST_URL, wait_until="networkidle")
        lines = []
        for row in self.page.locator(".iqitwishlist-product").all():
            link = row.locator("._name a").first
            url = link.get_attribute("href") or ""
            product_id = _product_id(url)
            if product_id is None:
                continue
            price_box = row.locator(".product-price")
            price = _squash(price_box.first.inner_text()) if price_box.count() else "?"
            lines.append(
                WishlistLine(
                    product_id=product_id, name=_squash(link.inner_text()), url=url, price=price
                )
            )
        return lines

    def remove_from_wishlist(self, product_id: int) -> None:
        self.page.goto(WISHLIST_URL, wait_until="networkidle")
        row = self.page.locator(f".iqitwishlist-product:has(a[href*='/{product_id}-'])")
        if row.count() == 0:
            raise SiteError(f"product {product_id} is not on the wishlist")
        with self.page.expect_response(_is_wishlist_action) as response_info:
            row.first.locator(".js-iqitwishlist-remove").click()
        _check_wishlist_remove(response_info.value.json())

    def _cart_row(self, product_id: int) -> Locator:
        self.page.goto(f"{BASE_URL}/cart?action=show", wait_until="domcontentloaded")
        row = self.page.locator(
            "li.cart-item:not(.mdgift-item)"
            f":has(a.remove-from-cart[data-id-product='{product_id}'])"
        )
        if row.count() == 0:
            raise SiteError(f"product {product_id} is not in the cart")
        return row.first

    def _search(self, item: Item) -> str:
        query = item.search or ""
        listings = self.search(query, limit=30)
        if not listings:
            raise SiteError(f"no search results for {query!r}")
        for listing in listings:
            if item.matches(listing.title):
                return listing.url
        raise SiteError(f"no result for {query!r} contains all of {list(item.require)}")


_READ_CARDS_JS = """cards => cards.map(card => {
    const text = selector => {
        const el = card.querySelector(selector);
        return el ? el.innerText : '';
    };
    const link = card.querySelector('.product-title a');
    return {
        title: text('.product-title a'),
        href: link ? link.href : '',
        price: text('.product-price'),
        regular: text('.regular-price'),
    };
})"""


def _product_id(url: str) -> int | None:
    match = re.search(r"/(\d+)-[^/]*\.html", url)
    return int(match.group(1)) if match else None


def _parse_price(text: str) -> Decimal | None:
    match = re.search(r"\d+(?:\.\d+)?", text.replace(",", ""))
    return Decimal(match.group()) if match else None


def _is_cart_line_update(response: Response) -> bool:
    return response.request.method == "POST" and "update=1" in response.url


def _is_cart_line_delete(response: Response) -> bool:
    return response.request.method == "POST" and "delete=1" in response.url


def _raise_unless_success(response: Response) -> None:
    body = response.json()
    if body.get("success") is not True:
        raise SiteError(_format_errors(body.get("errors")))


def _is_wishlist_action(response: Response) -> bool:
    return response.request.method == "POST" and "/module/iqitwishlist/actions" in response.url


def _check_wishlist_add(body: Mapping[str, Any]) -> None:
    if body.get("success") is True:
        return
    data = body.get("data") or {}
    kind = data.get("type")
    if kind == "inWishlit":  # the shop's own spelling; its message is wrong, the product is saved
        return
    if kind == "notLogged":
        raise SiteError("the wishlist needs a logged-in account (VICO_EMAIL and VICO_PASSWORD)")
    raise SiteError(str(data.get("message") or "the shop rejected the request"))


def _check_wishlist_remove(body: Mapping[str, Any]) -> None:
    if body.get("success") is not True:
        raise SiteError(str((body.get("data") or {}).get("message") or "the shop rejected it"))


def _is_cart_update(response: Response) -> bool:
    request = response.request
    return (
        request.method == "POST"
        and response.url.split("?")[0].rstrip("/").endswith("/cart")
        and "action=update" in (request.post_data or "")
    )


def _format_errors(errors: object) -> str:
    if isinstance(errors, list):
        errors = "; ".join(str(error) for error in errors)
    return str(errors) or "the shop rejected the request"


def _squash(text: str) -> str:
    return " ".join(text.split())
