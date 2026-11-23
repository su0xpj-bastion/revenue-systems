# For business approvers

You're on the business approver list because some Salesforce changes affect how the business runs:
who can see deals, how quotes are priced, what happens when an opportunity closes. Engineers
check that a change is *built* correctly. You decide whether it *should* happen.

## When you'll be asked

Only for `human_in_loop` changes. Today those are:

- who can see or edit data (profiles, permission sets, sharing)
- Opportunity, Quote, Order, Contract, and CPQ objects and their automation
- anything that deletes configuration
- changes to the release pipeline itself

Routine work (labels, layouts, reports, most code fixes) doesn't need you.

## What you'll see

The PR shows, in plain language:

- **What changes**: the summary written by the author
- **Why it was routed to you**: the rule that matched, plus the AI risk note
- **What was tested**: test results and a dry run against production
- **Who already reviewed the code**

## How to approve

Add the label **`signoff:business`** to the PR. That's the sign-off: it's recorded with your name
and time, and it's kept in the permanent change record.

You can't sign off on a change you wrote, and you can't be the only person who reviewed the code.
Someone else has to check the build.

## If you're not sure

Don't add the label. Comment with your question. Nothing ships until you add it.

## If something goes wrong after release

The pipeline automatically restores the previous version and pauses all releases until the team
reviews what happened. You'll see a "Deploy freeze" issue. Data entered while the bad version was
live is not automatically restored. That's the main reason these changes come to you first.
