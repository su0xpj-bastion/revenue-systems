# Runbook

Audience: Business Systems on-call, with the `Q2C Sync Operator` permission set.

## Where to look

- **Contract record page → Q2C Sync card** (`syncConsole`): sync state ("Billing behind: Salesforce v6,
  last acknowledged v5"), the outbox and inbox history, and open reconciliation breaks.
- **Report on Sync_Message__c** grouped by `Status__c` and `Target__c`: queue health across all contracts.
- **Recon_Break__c** by `Run_Id__c`: the nightly reconciliation result.

## Healthy

- `Pending` and `Retrying` drain within minutes. `Retrying` rows have a future `Next_Attempt_At__c`.
- `Dead` and `Parked` counts are 0.
- Every reconciliation run has 0 unresolved breaks the next morning.

## Situations

| You see | Likely cause | Do |
|---|---|---|
| Many `Retrying`, all `Last_Status_Code__c` 503 or 0 | Billing or CLM outage | Nothing; backoff caps at 1h. If it's long, consider the kill switch so retries stop burning attempts |
| `Dead` with 401 / 403 | Expired or rotated credentials on the Named Credential | Fix the External Credential, then **Retry now** on each dead row |
| `Dead` with 400 / 422 | Payload breaks the data contract (a code or data bug) | Don't retry; open a bug with the message's payload and error. Retrying the same bytes won't work |
| `Superseded` | Normal: a newer version replaced this one | Nothing |
| Inbound `Parked` | CLM called before the contract existed or was visible to the integration user | Confirm the contract exists, then **Retry now** |
| Inbound `Dead` "Illegal transition" | CLM and Salesforce disagree (e.g. signed after we cancelled) | Decide with Deal Desk / Legal which is right; fix the record; then retry or leave it |
| `Ignored_Stale` | An older webhook arrived after a newer one | Nothing |
| Recon break `Quantity_Mismatch` / `Price_Mismatch` | Someone edited Billing directly, or a sync bug | The repair message re-sends Salesforce's snapshot. If Billing was right, fix Salesforce instead (that publishes a new version). Then **Resolve** the break |
| Recon break `Missing_In_Billing` (whole contract) | First sync never succeeded | Check the contract's outbox for a Dead row |
| Recon break `Missing_In_Salesforce` | A line was added in Billing by hand | Decide which system is right; Billing should not be the place lines are created |

## Kill switch

`Setup → Custom Settings → Q2C Integration Settings → Organization default → Outbound Enabled`.

- Off: messages keep being written to the outbox; nothing is sent; retries don't burn attempts.
- On: run `OutboxDispatcher.kick();` from Anonymous Apex, or wait for the scheduled sweeper.

## Schedules (set up once per org)

```apex
System.schedule('Q2C outbox sweeper :00', '0 0 * * * ?', new OutboxDispatcher());
System.schedule('Q2C outbox sweeper :30', '0 30 * * * ?', new OutboxDispatcher());
System.schedule('Q2C reconciliation nightly', '0 0 3 * * ?', new ReconciliationJob(true));
```

## Webhook secret rotation

1. Generate a new secret in the CLM admin console, set to "dual-sign" if the provider supports it.
2. Update `Webhook_Secret__c` (protected custom setting) in Salesforce.
3. Watch for 401s in the CLM delivery log. Any event rejected during the switch is redelivered by CLM
   and deduped by `eventId`.
