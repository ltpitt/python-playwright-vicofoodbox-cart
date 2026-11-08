# vicocart

Finds products on [vicofoodbox.com](https://vicofoodbox.com/en) and saves them to your account wishlist. It never checks out.

- `vicocart list`: searches the products of a TOML shopping list and saves them to the wishlist, no LLM involved.
- `vicocart ask "<goal>"`: an LLM agent searches the shop and fills a cart (needs `--headed`).

## Why a wishlist

A cart only lives inside the browser session that filled it: a fresh login, even to the same account, starts with an empty cart. A headless run therefore cannot leave a cart behind. The wishlist is stored on the account, so you can open it from any browser, set the quantities and click Add to Box. The wishlist keeps no quantities: `list` prints the quantity wanted next to each product link.

## Setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m playwright install chromium
cp .env.example .env    # VICO_EMAIL / VICO_PASSWORD, plus LLM_* for `ask`
```

## Run

```sh
cp shopping_list.example.toml shopping_list.toml
.venv/bin/vicocart list --dry-run                # find the products, change nothing
.venv/bin/vicocart list                          # save them to your wishlist (needs VICO_EMAIL/VICO_PASSWORD)
.venv/bin/vicocart list --cart --headed          # fill the cart instead and leave the browser open

.venv/bin/vicocart ask "I want to make carbonara for 4" --dry-run   # plan only
.venv/bin/vicocart ask "12 bottles of mutti passata, only if there is an offer" --headed
.venv/bin/vicocart ask "..." --budget 60 --headed
```

After `list`, open https://vicofoodbox.com/en/wishlist while logged in, set the quantities and click Add to Box.

The agent behind `ask` has three tools: search, add to cart, view cart. Limits are enforced in code, not by the prompt: a spend cap (`--budget`, default EUR 150), at most 24 per product, a step cap (`--max-steps`), and only products returned by a search can be added. The model's summary can be wrong, so the CLI also prints what was actually added.

`ask` needs a model that handles tool calling well. Small local models (a 7B on Ollama) invent results.

Exit code is 0 on success, 1 when an item failed or the agent did not finish, 2 for bad config.

## Live proof

```sh
.venv/bin/pytest -m live -v
```

Drives the real shop headless: add a product, change its quantity, remove it; and save a product to the wishlist and see it from a second, fresh login. Checkout is blocked at the network level, so nothing can be ordered. The guest tests need nothing; the account tests log in with `VICO_EMAIL`/`VICO_PASSWORD` and leave the account as they found it. Plain `pytest` skips these.

## Checks

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src tests && .venv/bin/pytest
```
