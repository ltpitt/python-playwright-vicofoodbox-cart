from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from openai import OpenAIError
from playwright.sync_api import sync_playwright

from vicocart.agent import Limits, run_agent
from vicocart.config import ConfigError, Credentials, load_credentials, load_llm_settings
from vicocart.llm import OpenAiChat
from vicocart.runner import Outcome, Target, add_items
from vicocart.shopping_list import Item, ShoppingListError, load_shopping_list
from vicocart.site import WISHLIST_URL, CartSnapshot, SiteError, VicoSite, WishlistLine

Job = Callable[[VicoSite], int]

_MAIN_EPILOG = """\
Run from the repo directory: .env (VICO_EMAIL, VICO_PASSWORD) is read from the working
directory or a parent.

`list` is the one to script and needs no LLM. It saves products to the account wishlist,
which any browser can open after logging in. A cart only lives inside the browser session
that filled it, so a headless run cannot leave one behind: `ask` and `list --cart` need
--headed for that reason. Always try --dry-run first.

Exit code: 0 ok, 1 an item failed or the agent did not finish, 2 bad config.
"""

_LIST_EPILOG = f"""\
Saves each product to the account wishlist (login required). The wishlist keeps no quantities:
each "[ok]" line shows the quantity wanted and the product link. Afterwards tell the user to
open {WISHLIST_URL}, set quantities and click "Add to Box".
--cart fills the cart instead (needs --headed).

shopping_list.toml: one [[items]] table per product, exactly one of url/search.
  [[items]]
  search = "rummo linguine"      # or: url = "https://vicofoodbox.com/en/....html"
  require = ["linguine", "500"]  # optional: every term must be in the product title
  quantity = 2                   # optional, default 1
  name = "Rummo Linguine"        # optional label for the output
"""


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    load_dotenv(find_dotenv(usecwd=True))
    try:
        credentials = load_credentials(os.environ)
        job = _build_job(args)
    except (OSError, ConfigError, ShoppingListError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    problem = _setup_problem(args, credentials)
    if problem:
        print(f"error: {problem}", file=sys.stderr)
        return 2

    try:
        with _open_site(
            headed=args.headed, credentials=None if args.dry_run else credentials
        ) as site:
            return job(site)
    except SiteError as exc:
        print(f"error: {exc}", file=sys.stderr)
    except OpenAIError as exc:
        print(f"error: LLM request failed: {exc}", file=sys.stderr)
    return 1


def _setup_problem(args: argparse.Namespace, credentials: Credentials | None) -> str | None:
    if args.dry_run:
        return None
    if args.command == "ask" or args.cart:
        if args.headed:
            return None
        return (
            "a cart only lives inside the browser session that filled it, so a headless run "
            "leaves nothing to see: add --headed to keep the browser open on the cart, "
            "or use `list` without --cart to save to the wishlist"
        )
    if credentials is None:
        return "the wishlist needs your account: set VICO_EMAIL and VICO_PASSWORD in .env"
    return None


def _build_job(args: argparse.Namespace) -> Job:
    if args.command == "list":
        items = load_shopping_list(args.shopping_list)
        target: Target = "cart" if args.cart else "wishlist"
        return lambda site: _run_list(site, items, target=target, dry_run=args.dry_run)
    llm = OpenAiChat(load_llm_settings(os.environ))
    limits = Limits(max_steps=args.max_steps, budget=Decimal(str(args.budget)))
    return lambda site: _run_ask(site, llm, args.goal, limits, dry_run=args.dry_run)


@contextmanager
def _open_site(*, headed: bool, credentials: Credentials | None) -> Iterator[VicoSite]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not headed)
        try:
            context = browser.new_context(locale="en-GB", viewport={"width": 1400, "height": 900})
            site = VicoSite(context.new_page())
            site.dismiss_cookies()
            if credentials:
                site.login(credentials)
            yield site
            if headed and sys.stdin.isatty():
                input("Browser left open on the last page. Press Enter to close it. ")
        finally:
            browser.close()


def _run_list(site: VicoSite, items: list[Item], *, target: Target, dry_run: bool) -> int:
    outcomes = add_items(site, items, target=target, dry_run=dry_run)
    _print_outcomes(outcomes, target=target, dry_run=dry_run)
    if not dry_run:
        if target == "wishlist":
            _print_wishlist(site.read_wishlist())
        else:
            _print_cart(site.read_cart())
    return 0 if all(outcome.ok for outcome in outcomes) else 1


def _run_ask(site: VicoSite, llm: OpenAiChat, goal: str, limits: Limits, *, dry_run: bool) -> int:
    result = run_agent(
        llm, site, goal, limits=limits, dry_run=dry_run, on_event=lambda line: print(f"  {line}")
    )
    print(f"\nAgent says:\n{result.summary}")
    # The summary is model-written and can be wrong; this list comes from the tool results.
    print("\nWould add (dry run):" if dry_run else "\nAdded by the agent:")
    for item in result.added:
        print(f"  {item.quantity} x {item.listing.title} (EUR {item.listing.price} each)")
    if not result.added:
        print("  nothing")
    if not dry_run:
        _print_cart(site.read_cart())
    return 0 if result.finished else 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="vicocart",
        description="Save vicofoodbox.com products to your wishlist or cart. It never checks out.",
        epilog=_MAIN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run", action="store_true", help="do everything except touch the wishlist or cart"
    )
    common.add_argument("--headed", action="store_true", help="show the browser and keep it open")

    commands = parser.add_subparsers(dest="command", required=True)

    ask = commands.add_parser(
        "ask", parents=[common], help="describe a goal; an LLM fills the cart (needs --headed)"
    )
    ask.add_argument("goal", help='e.g. "I want to make carbonara for 4"')
    ask.add_argument("--budget", type=float, default=150, help="max EUR to add (default: 150)")
    ask.add_argument("--max-steps", type=int, default=15, help="max LLM turns (default: 15)")

    shopping_list = commands.add_parser(
        "list",
        parents=[common],
        help="save the products of a TOML shopping list to your wishlist",
        epilog=_LIST_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    shopping_list.add_argument(
        "--cart", action="store_true", help="fill the cart instead of the wishlist (needs --headed)"
    )
    shopping_list.add_argument(
        "shopping_list",
        nargs="?",
        type=Path,
        default=Path("shopping_list.toml"),
        help="path to the shopping list (default: shopping_list.toml)",
    )
    return parser.parse_args(argv)


def _print_outcomes(outcomes: list[Outcome], *, target: Target, dry_run: bool) -> None:
    for outcome in outcomes:
        product = outcome.product
        label = f"{product.title} ({product.price})" if product else outcome.item.name
        quantity = outcome.item.quantity
        if not outcome.ok:
            print(f"[FAIL] {quantity} x {label}: {outcome.error}")
        elif target == "wishlist":
            verb = "found" if dry_run else "wishlisted"
            link = f": {product.url}" if product else ""
            print(f"[ok]   {verb} {label}, want {quantity}{link}")
        else:
            verb = "found" if dry_run else "added"
            print(f"[ok]   {verb} {quantity} x {label}")


def _print_wishlist(lines: list[WishlistLine]) -> None:
    print("\nWishlist now contains:")
    for line in lines:
        print(f"  {line.name} ({line.price})")
    print(
        f"\nNext: log in and open {WISHLIST_URL}, set the quantities and click Add to Box. "
        "The wishlist keeps no quantities, so use the 'want' numbers above."
    )


def _print_cart(snapshot: CartSnapshot) -> None:
    print("\nCart now contains:")
    for line in snapshot.lines:
        print(f"  {line.quantity} x {line.name}")
    for notice in snapshot.notices:
        print(f"  ! {notice}")
