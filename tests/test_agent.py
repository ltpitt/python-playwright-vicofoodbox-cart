from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from vicocart.agent import AssistantTurn, Limits, ToolCall, run_agent
from vicocart.site import CartLine, CartSnapshot, Listing, SiteError


def _listing(product_id: int, title: str, price: str | None, regular: str | None = None) -> Listing:
    return Listing(
        id=product_id,
        title=title,
        url=f"https://vicofoodbox.com/en/x/{product_id}-slug.html",
        price=None if price is None else Decimal(price),
        regular_price=None if regular is None else Decimal(regular),
    )


class FakeShop:
    def __init__(self, catalogue: list[Listing], cart: list[CartLine] | None = None) -> None:
        self.catalogue = catalogue
        self.cart = cart or []
        self.added: list[tuple[str, int]] = []
        self.refuse: dict[str, str] = {}

    def search(self, query: str) -> list[Listing]:
        return [item for item in self.catalogue if query.lower() in item.title.lower()]

    def add_product(self, url: str, quantity: int) -> None:
        if url in self.refuse:
            raise SiteError(self.refuse[url])
        self.added.append((url, quantity))

    def read_cart(self) -> CartSnapshot:
        return CartSnapshot(lines=self.cart, notices=[])


class ScriptedLlm:
    """Replays prepared turns and records every request it receives."""

    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = iter(turns)
        self.requests: list[list[dict[str, Any]]] = []

    def complete(
        self, messages: Sequence[Mapping[str, Any]], tools: Sequence[Mapping[str, Any]]
    ) -> AssistantTurn:
        self.requests.append([dict(message) for message in messages])
        return next(self._turns)


def call(name: str, **arguments: Any) -> AssistantTurn:
    return AssistantTurn(None, [ToolCall("c1", name, json.dumps(arguments))])


def done(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text, [])


def last_tool_result(llm: ScriptedLlm) -> dict[str, Any]:
    tool_messages = [m for m in llm.requests[-1] if m["role"] == "tool"]
    result: dict[str, Any] = json.loads(tool_messages[-1]["content"])
    return result


MUTTI = _listing(1, "Mutti Passata 700 g", "1.40", "1.80")
PLAIN = _listing(2, "Mutti Polpa 400 g", "1.20")


def test_agent_searches_then_adds_and_reports() -> None:
    shop = FakeShop([MUTTI, PLAIN])
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=1, quantity=12),
            done(),
        ]
    )
    result = run_agent(llm, shop, "12 bottles of mutti if on offer")
    assert result.finished
    assert result.summary == "done"
    assert shop.added == [(MUTTI.url, 12)]
    assert [(a.listing.id, a.quantity) for a in result.added] == [(1, 12)]


def test_search_results_expose_offer_information() -> None:
    llm = ScriptedLlm([call("search_products", query="mutti"), done()])
    run_agent(llm, FakeShop([MUTTI, PLAIN]), "goal")
    results = {r["id"]: r for r in last_tool_result(llm)["results"]}
    assert results[1]["on_sale"] is True
    assert results[1]["discount_percent"] == 22
    assert results[2]["on_sale"] is False
    assert results[2]["discount_percent"] is None


def test_goal_and_existing_cart_reach_the_model() -> None:
    shop = FakeShop([], cart=[CartLine("Spaghetti", 2)])
    llm = ScriptedLlm([done()])
    run_agent(llm, shop, "make carbonara")
    prompt = llm.requests[0][1]["content"]
    assert "make carbonara" in prompt
    assert "2 x Spaghetti" in prompt


def test_cannot_add_a_product_that_was_never_searched() -> None:
    shop = FakeShop([MUTTI])
    llm = ScriptedLlm([call("add_to_cart", product_id=1, quantity=1), done()])
    run_agent(llm, shop, "goal")
    assert "unknown product_id" in last_tool_result(llm)["error"]
    assert shop.added == []


def test_quantity_limit_is_enforced_in_code() -> None:
    shop = FakeShop([MUTTI])
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=1, quantity=500),
            done(),
        ]
    )
    run_agent(llm, shop, "goal", limits=Limits(max_quantity=24))
    assert "between 1 and 24" in last_tool_result(llm)["error"]
    assert shop.added == []


def test_budget_is_enforced_across_adds() -> None:
    shop = FakeShop([MUTTI])
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=1, quantity=10),
            call("add_to_cart", product_id=1, quantity=1),
            done(),
        ]
    )
    run_agent(llm, shop, "goal", limits=Limits(budget=Decimal(15)))
    assert shop.added == [(MUTTI.url, 10)]
    assert "already added 10" in last_tool_result(llm)["error"]


def test_over_budget_add_is_refused() -> None:
    shop = FakeShop([MUTTI])
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=1, quantity=20),
            done(),
        ]
    )
    run_agent(llm, shop, "goal", limits=Limits(budget=Decimal(15)))
    assert "over budget" in last_tool_result(llm)["error"]
    assert shop.added == []


def test_product_without_price_is_refused() -> None:
    shop = FakeShop([_listing(3, "Mutti Special", None)])
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=3, quantity=1),
            done(),
        ]
    )
    run_agent(llm, shop, "goal")
    assert "no price" in last_tool_result(llm)["error"]
    assert shop.added == []


def test_shop_refusal_is_relayed_so_the_model_can_retry() -> None:
    shop = FakeShop([MUTTI])
    shop.refuse[MUTTI.url] = "You can buy a maximum of 2 pack at this price"
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=1, quantity=12),
            done(),
        ]
    )
    result = run_agent(llm, shop, "goal")
    assert last_tool_result(llm)["error"] == "You can buy a maximum of 2 pack at this price"
    assert result.added == []


def test_dry_run_never_touches_the_shop_and_view_cart_shows_the_plan() -> None:
    shop = FakeShop([MUTTI])
    llm = ScriptedLlm(
        [
            call("search_products", query="mutti"),
            call("add_to_cart", product_id=1, quantity=3),
            call("view_cart"),
            done(),
        ]
    )
    result = run_agent(llm, shop, "goal", dry_run=True)
    assert shop.added == []
    assert len(result.added) == 1
    assert last_tool_result(llm)["planned_not_in_cart"] == [
        {"title": "Mutti Passata 700 g", "quantity": 3}
    ]


def test_bad_tool_arguments_do_not_crash_the_loop() -> None:
    bad_json = AssistantTurn(None, [ToolCall("c1", "add_to_cart", "{not json")])
    unknown = AssistantTurn(None, [ToolCall("c2", "checkout", "{}")])
    llm = ScriptedLlm([bad_json, unknown, done()])
    result = run_agent(llm, FakeShop([]), "goal")
    assert result.finished
    assert "unknown tool" in last_tool_result(llm)["error"]


def test_step_limit_stops_a_runaway_model() -> None:
    llm = ScriptedLlm([call("view_cart") for _ in range(10)])
    result = run_agent(llm, FakeShop([]), "goal", limits=Limits(max_steps=3))
    assert not result.finished
    assert len(llm.requests) == 3


def test_events_are_reported() -> None:
    events: list[str] = []
    llm = ScriptedLlm([call("search_products", query="mutti"), done()])
    run_agent(llm, FakeShop([MUTTI]), "goal", on_event=events.append)
    assert events == ['search_products({"query": "mutti"}) -> 1 results']
