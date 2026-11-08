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
from vicocart.runner import Outcome, fill_cart
from vicocart.shopping_list import Item, ShoppingListError, load_shopping_list
from vicocart.site import CartSnapshot, SiteError, VicoSite

Job = Callable[[VicoSite], int]

_MAIN_EPILOG = """\
Run from the repo directory: .env (VICO_EMAIL, VICO_PASSWORD) is read from the working
directory or a parent.
`list` needs no LLM and is the one to script; run it with --dry-run first.
Exit code: 0 ok, 1 an item failed or the agent did not finish, 2 bad config.
"""

_LIST_EPILOG = """\
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

    if credentials is None and not (args.dry_run or args.headed):
        print(
            "error: set VICO_EMAIL and VICO_PASSWORD in .env so the cart is saved to your account, "
            "or use --headed to keep a guest cart open in the browser",
            file=sys.stderr,
        )
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


def _build_job(args: argparse.Namespace) -> Job:
    if args.command == "list":
        items = load_shopping_list(args.shopping_list)
        return lambda site: _run_list(site, items, dry_run=args.dry_run)
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
                input("Browser left open on the cart page. Press Enter to close it. ")
        finally:
            browser.close()


def _run_list(site: VicoSite, items: list[Item], *, dry_run: bool) -> int:
    outcomes = fill_cart(site, items, dry_run=dry_run)
    _print_outcomes(outcomes, dry_run=dry_run)
    if not dry_run:
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
        description="Fill the vicofoodbox.com cart. It never checks out.",
        epilog=_MAIN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--dry-run", action="store_true", help="do everything except touch the cart"
    )
    common.add_argument("--headed", action="store_true", help="show the browser and keep it open")

    commands = parser.add_subparsers(dest="command", required=True)

    ask = commands.add_parser(
        "ask", parents=[common], help="describe a goal; an LLM fills the cart"
    )
    ask.add_argument("goal", help='e.g. "I want to make carbonara for 4"')
    ask.add_argument("--budget", type=float, default=150, help="max EUR to add (default: 150)")
    ask.add_argument("--max-steps", type=int, default=15, help="max LLM turns (default: 15)")

    shopping_list = commands.add_parser(
        "list",
        parents=[common],
        help="add the items of a TOML shopping list",
        epilog=_LIST_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    shopping_list.add_argument(
        "shopping_list",
        nargs="?",
        type=Path,
        default=Path("shopping_list.toml"),
        help="path to the shopping list (default: shopping_list.toml)",
    )
    return parser.parse_args(argv)


def _print_outcomes(outcomes: list[Outcome], *, dry_run: bool) -> None:
    verb = "found" if dry_run else "added"
    for outcome in outcomes:
        product = outcome.product
        label = f"{product.title} ({product.price})" if product else outcome.item.name
        if outcome.ok:
            print(f"[ok]   {verb} {outcome.item.quantity} x {label}")
        else:
            print(f"[FAIL] {outcome.item.quantity} x {label}: {outcome.error}")


def _print_cart(snapshot: CartSnapshot) -> None:
    print("\nCart now contains:")
    for line in snapshot.lines:
        print(f"  {line.quantity} x {line.name}")
    for notice in snapshot.notices:
        print(f"  ! {notice}")
