# revenue-systems

The systems a company runs between "the customer said yes" and "the money is booked": pricing a new product, quoting it, approving discounts, signing contracts, billing usage, recognising revenue, and keeping Salesforce, contract and billing systems in agreement. Plus the release pipeline that decides how much human review each change to them needs.

Five projects, each in its own folder with its own README, dependencies and tests. **gtm-release-control is this repository's release pipeline**: its workflows run on every pull request and decide whether a change can merge with automated checks only, with one reviewer, or with a reviewer plus business sign-off. The other four have their own workflows, which run only when their folder changes.

| Project | What it is, in plain terms | Tests |
|---|---|---|
| [gtm-release-control](gtm-release-control/) | The release pipeline: an AI classifier sorts every change into a lane by risk (it can only raise the lane, never lower it), a gate enforces the reviews that lane needs, and each production deploy writes its own audit evidence. Salesforce security and revenue objects always need a human | 47 |
| [npi-launch-kit](npi-launch-kit/) | Launching a new product or price from one pricing spec: checks the spec, builds the catalog and quoting setup, runs pricing scenarios, and gives a go / no-go for launch | 43 |
| [meter-to-revenue](meter-to-revenue/) | The money path after a deal is signed: usage, rating, invoices, tax, revenue recognition and the general ledger, with a SOX-style control at every handoff | 35 |
| [cpq-q2c-extensions](cpq-q2c-extensions/) | Custom code for Salesforce CPQ where configuration alone falls short: renewal pricing, floor-price protection, approval routing, quote and contract rules | 61 + 22 Apex files syntax-checked |
| [q2c-integration-hub](q2c-integration-hub/) | Keeps contracts and subscriptions consistent across Salesforce, a contract system and a billing system when messages are retried, duplicated, reordered or lost | 24 + 16 component tests |

Salesforce code in this repository is syntax-checked and unit-tested; it has not been deployed to a Salesforce org. The pipeline's org jobs need org credentials that aren't configured: deploy and rollback skip, and `validate-sf` cannot pass on a pull request that changes Salesforce metadata until an org is connected.
