/**
 * Turns Q2C_Change__e events into Sync_Message__c rows (the outbox).
 *
 * Key decisions:
 *  - The message snapshots the contract as it is NOW, at its current version, not the version on the
 *    event. Two quick edits (v4, v5) that arrive together both resolve to v5, and the unique
 *    Idempotency_Key__c collapses them into one message.
 *  - Inserts use allOrNone=false. A DUPLICATE_VALUE error on the key means "already queued" and is
 *    success. Any other error makes the whole batch retryable: because every insert is idempotent,
 *    Salesforce redelivering the same events can't create a second message.
 */
public inherited sharing class OutboxService {
    public static final Integer MAX_EVENT_RETRIES = 9;

    public class Outcome {
        public Integer inserted = 0;
        public Integer duplicates = 0;
        public List<String> errors = new List<String>();
    }

    public static Outcome enqueueFromEvents(List<Q2C_Change__e> events) {
        Set<Id> contractIds = new Set<Id>();
        Map<Id, String> correlation = new Map<Id, String>();
        for (Q2C_Change__e e : events) {
            if (e.Entity__c == 'Q2C_Contract__c' && e.Record_Id__c != null) {
                Id recordId = Id.valueOf(e.Record_Id__c);
                contractIds.add(recordId);
                correlation.put(recordId, e.EventUuid);
            }
        }
        Outcome outcome = enqueueContracts(contractIds, correlation, null);
        if (!outcome.errors.isEmpty()) {
            EventBus.TriggerContext ctx = EventBus.TriggerContext.currentContext();
            if (ctx != null && ctx.retries < MAX_EVENT_RETRIES) {
                throw new EventBus.RetryableException(String.join(outcome.errors, '; '));
            }
        }
        return outcome;
    }

    /**
     * Shared by the event subscriber and the reconciliation repair path (repairRunId != null), which
     * needs a fresh key so the target re-applies instead of replaying its cached answer.
     */
    public static Outcome enqueueContracts(Set<Id> contractIds, Map<Id, String> correlation, String repairRunId) {
        Outcome outcome = new Outcome();
        if (contractIds.isEmpty()) {
            return outcome;
        }
        List<Sync_Message__c> messages = new List<Sync_Message__c>();
        for (Q2C_Contract__c c : OutboxPayloads.loadContracts(contractIds)) {
            for (ContractStateMachine.Route r : ContractStateMachine.outboundFor(c.Status__c)) {
                String key = IdempotencyKeys.outbound(r.target, r.operation, c.Id, c.Version__c);
                if (repairRunId != null) {
                    key = IdempotencyKeys.repair(key, repairRunId);
                }
                messages.add(new Sync_Message__c(
                    Idempotency_Key__c = key,
                    Direction__c = 'Outbound',
                    Target__c = r.target,
                    Operation__c = r.operation,
                    Record_Id__c = c.Id,
                    Entity_Version__c = c.Version__c,
                    Payload__c = OutboxPayloads.build(c, r.target, r.operation),
                    Status__c = 'Pending',
                    Attempts__c = 0,
                    Next_Attempt_At__c = System.now(),
                    Correlation_Id__c = correlation == null ? null : correlation.get(c.Id)
                ));
            }
        }
        if (messages.isEmpty()) {
            return outcome;
        }
        List<Database.SaveResult> results = Database.insert(messages, false);
        for (Integer i = 0; i < results.size(); i++) {
            if (results[i].isSuccess()) {
                outcome.inserted++;
            } else if (results[i].getErrors()[0].getStatusCode() == StatusCode.DUPLICATE_VALUE) {
                outcome.duplicates++;
            } else {
                outcome.errors.add(messages[i].Idempotency_Key__c + ': ' + results[i].getErrors()[0].getMessage());
            }
        }
        if (outcome.inserted > 0) {
            OutboxDispatcher.kick();
        }
        return outcome;
    }
}
