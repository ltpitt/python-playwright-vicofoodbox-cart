# vicocart

Fills the [vicofoodbox.com](https://vicofoodbox.com/en) cart. It stops at the cart and never checks out.

- `vicocart ask "<goal>"`: an LLM agent searches the shop and adds what the goal needs.
- `vicocart list`: adds the items of a TOML shopping list, no LLM involved.

## Setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m playwright install chromium
cp .env.example .env    # VICO_EMAIL / VICO_PASSWORD, plus LLM_* for `ask`
```

## Run

```sh
.venv/bin/vicocart ask "I want to make carbonara for 4" --dry-run   # plan only, cart untouched
.venv/bin/vicocart ask "12 bottles of mutti passata, only if there is an offer"
.venv/bin/vicocart ask "..." --budget 60 --headed                   # watch it, keep the browser open

cp shopping_list.example.toml shopping_list.toml
.venv/bin/vicocart list --dry-run
```

The agent has three tools: search, add to cart, view cart. Limits are enforced in code, not by the prompt: a spend cap (`--budget`, default EUR 150), at most 24 per product, a step cap (`--max-steps`), and only products returned by a search can be added. The model's summary can be wrong, so the CLI also prints what was actually added.

`ask` needs a model that handles tool calling well. Small local models (a 7B on Ollama) invent results.

Exit code is 0 on success, 1 when an item failed or the agent did not finish, 2 for bad config.

## Checks

```sh
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src tests && .venv/bin/pytest
```
