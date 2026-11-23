"""Claude in the launch loop: it drafts, deterministic code checks, a human signs off.

1. draft_spec: pricing brief (prose) → spec draft. Claude is told never to invent a number,
   date or tax code that isn't in the brief; gaps become `open_questions`, which the linter
   treats as blocking. The draft is then parsed and linted like a hand-written spec.
2. propose_scenarios: spec → edge-case quote scenarios (inputs only). Claude never computes
   money; the pricing engine does, and a human promotes computed values to `expect`.

How the output is checked: schema-constrained output (structured outputs), parse_spec for types
and dates, lint for business rules, scenario engine for arithmetic, human review for intent.
"""
from __future__ import annotations

import json

import anthropic

MODEL = "claude-opus-5-5"

NUM = {"anyOf": [{"type": "number"}, {"type": "null"}]}
STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}


def _enum_or_null(values: list[str]) -> dict:
    return {"anyOf": [{"type": "string", "enum": values}, {"type": "null"}]}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


SPEC_SCHEMA = _obj({
    "launch": _obj({
        "code": {"type": "string"}, "name": {"type": "string"},
        "launch_date": {"type": "string"}, "first_bill_run": {"type": "string"},
        "currency": {"type": "string"},
    }),
    "products": {"type": "array", "items": _obj({
        "sku": {"type": "string"}, "name": {"type": "string"}, "family": {"type": "string"},
        "model": {"type": "string", "enum": ["flat", "per_seat", "usage_tiered", "committed"]},
        "billing_frequency": _enum_or_null(["monthly", "quarterly", "annual"]),
        "tax_code": STR,
        "revenue": _enum_or_null(["ratable", "usage", "point_in_time"]),
        "term_months": {"type": "integer"},
        "list_price": NUM, "min_quantity": {"type": "integer"},
        "unit": STR, "usage_source": STR,
        "tier_mode": _enum_or_null(["graduated", "volume"]),
        "tiers": {"type": "array", "items": _obj({"up_to": NUM, "price": {"type": "number"}})},
        "ramp": {"type": "array", "items": _obj({"year": {"type": "integer"}, "commit": {"type": "number"}})},
        "drawdown_rate": NUM, "overage_rate": NUM, "usage_sku": STR,
    })},
    "bundles": {"type": "array", "items": _obj({
        "sku": {"type": "string"}, "name": {"type": "string"},
        "required": {"type": "array", "items": {"type": "string"}},
        "optional": {"type": "array", "items": {"type": "string"}},
    })},
    "approvals": {"type": "array", "items": _obj({
        "max_discount_pct": {"type": "number"}, "approver": {"type": "string"},
    })},
    "retirements": {"type": "array", "items": _obj({
        "sku": {"type": "string"}, "replacement": {"type": "string"},
        "end_of_sale": {"type": "string"}, "end_of_renewal": {"type": "string"},
        "policy": {"type": "string", "enum": [
            "grandfather_until_end_of_renewal", "migrate_at_renewal", "migrate_now_coterm"]},
    })},
    "signoffs": {"type": "array", "items": {"type": "string", "enum": [
        "product", "pricing", "deal_desk", "sales", "finance", "accounting", "tax", "legal", "billing_eng"]}},
    "open_questions": {"type": "array", "items": {"type": "string"}},
})

DRAFT_SYSTEM = """You turn a pricing and packaging brief into a structured launch spec for a \
quote-to-cash systems team (CPQ, billing, tax, finance reporting).

Rules:
- Use only facts stated in the brief. Never invent a price, tier boundary, date, tax code, \
term, discount band or usage source. If the brief does not say, set the field to null (or an \
empty list) and add a specific question to open_questions naming who must answer it.
- Tax codes come from the Tax team, never from you: leave tax_code null unless the brief states one.
- Dates are ISO YYYY-MM-DD. Money is a plain number in the launch currency.
- term_months for committed products is 12 x number of ramp years.
- Flag anything that cannot be quoted, billed, taxed or reported cleanly as an open question.
- signoffs always include finance, tax, legal, deal_desk and billing_eng, plus any other team \
the brief says is affected."""

SCENARIO_SCHEMA = _obj({
    "scenarios": {"type": "array", "items": _obj({
        "name": {"type": "string"},
        "why": {"type": "string"},
        "start": {"type": "string"},
        "lines": {"type": "array", "items": _obj({
            "sku": {"type": "string"}, "quantity": {"type": "number"}, "discount_pct": {"type": "number"},
        })},
        "usage": {"type": "array", "items": _obj({
            "sku": {"type": "string"}, "monthly": {"type": "array", "items": {"type": "number"}},
        })},
    })},
})

SCENARIO_SYSTEM = """You design quote and billing test scenarios for a product launch, aimed at \
the cases most likely to break: tier boundaries (exactly at, one above), minimum quantities, \
discounts at each approval band edge, commit exhausted mid-month, ramp year rollover, zero \
usage, and mixing products on one quote. Provide inputs only; do not compute prices. \
Explain in `why` what each scenario is meant to catch. Use only SKUs from the spec."""


class DraftError(RuntimeError):
    pass


def _structured_call(client: anthropic.Anthropic, system: str, user: str, schema: dict) -> dict:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason != "end_turn":
        raise DraftError(f"Claude stopped with stop_reason={response.stop_reason}; nothing written")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise DraftError("no text in response")
    return json.loads(text)


def draft_spec(client: anthropic.Anthropic, brief: str) -> dict:
    return _structured_call(client, DRAFT_SYSTEM, f"<brief>\n{brief}\n</brief>", SPEC_SCHEMA)


def propose_scenarios(client: anthropic.Anthropic, spec_yaml: str, count: int = 10) -> list[dict]:
    data = _structured_call(
        client, SCENARIO_SYSTEM,
        f"<spec>\n{spec_yaml}\n</spec>\nPropose {count} scenarios.", SCENARIO_SCHEMA,
    )
    return [
        {
            "name": s["name"], "why": s["why"], "start": s["start"], "lines": s["lines"],
            "usage": {u["sku"]: u["monthly"] for u in s["usage"]},
        }
        for s in data["scenarios"]
    ]
