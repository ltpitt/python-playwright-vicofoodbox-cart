from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from dotenv import find_dotenv, load_dotenv
from playwright.sync_api import Browser, sync_playwright

from vicocart.config import Credentials, load_credentials
from vicocart.site import VicoSite


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def open_site(browser: Browser) -> Iterator[Callable[[], VicoSite]]:
    """Factory for isolated sessions (VicoSite blocks the checkout page itself)."""
    contexts = []

    def factory() -> VicoSite:
        context = browser.new_context(locale="en-GB", viewport={"width": 1400, "height": 900})
        contexts.append(context)
        site = VicoSite(context.new_page())
        site.dismiss_cookies()
        return site

    yield factory
    for context in contexts:
        context.close()


@pytest.fixture
def credentials() -> Credentials:
    load_dotenv(find_dotenv(usecwd=True))
    found = load_credentials(os.environ)
    if found is None:
        pytest.skip("VICO_EMAIL and VICO_PASSWORD are not set")
    return found
