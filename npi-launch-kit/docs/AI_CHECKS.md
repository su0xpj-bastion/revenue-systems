# Where Claude is used, and how its output is checked

Rule: **Claude drafts and proposes. Deterministic code checks and computes. A named human signs off.**
Nothing Claude produces reaches a system of record without passing through all three.

| Use | What Claude does | What it never does | How the output is checked |
|---|---|---|---|
| `npi draft` | Turns a prose pricing brief into a spec draft | Invent a price, date, tier, tax code or usage source not in the brief | 1. Structured output: the response must match the spec's JSON schema. 2. `parse_spec`: types and dates. 3. `lint`: business rules; every gap Claude raised as an `open_question` **blocks**. 4. Human review of the diff against the brief |
| `npi propose-scenarios` | Proposes edge-case quote inputs (tier boundaries, commit exhaustion, band edges) | Compute money | The pricing engine computes every amount. A human promotes a scenario into the suite only after Finance agrees the computed value is right |
| Day-to-day build | Writing validation-rule formulas, Flow logic, test data, dev specs | Deploy to production | Same pipeline as any change: review, scenario suite, sandbox tests |

## Why this split

- **Arithmetic is not a language task.** Tiered and ramped pricing has exact answers. The engine is
  tested against hand-worked examples (see [PRICING_MODELS.md](PRICING_MODELS.md)), so its numbers can be trusted.
- **Missing information must stay visible.** A model asked to fill a schema will fill it. The prompt
  requires nulls plus open questions for anything not in the brief, and the linter refuses to pass a spec
  with open questions, so a guess can't slip through as a fact.
- **Tax codes are never generated.** A plausible-looking wrong tax code is worse than a blank one: the
  blank fails validation, the wrong one fails an audit.

## Where it saves time

- **Brief → first spec draft**: minutes instead of a working session, and the open questions come out
  as a list of owners to chase.
- **Edge-case scenarios**: more boundary cases than a person writes by hand, and the engine computes
  them for free.
- **Dev specs and enablement drafts**: generated from the spec, edited by a human.
