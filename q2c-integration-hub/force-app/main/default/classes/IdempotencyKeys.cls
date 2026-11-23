/**
 * Idempotency keys are the whole duplicate-handling strategy, so their format lives in one place.
 *
 * Outbound  billing:upsert_contract:<recordId>:v<version>
 *           One message per (target, operation, record, version). Two Platform Events for the same
 *           version collapse into one row because Sync_Message__c.Idempotency_Key__c is unique.
 *           The same string goes out as the Idempotency-Key header, so the target dedupes our retries.
 * Repair    <outbound key>:repair:<runId>
 *           A reconciliation re-send must NOT reuse the original key: the target would replay its
 *           earlier answer instead of fixing the drift.
 * Inbound   clm-in:<eventId>
 *           The sender's event id. A redelivered webhook hits the unique index and is answered
 *           "duplicate" without touching the contract.
 */
public inherited sharing class IdempotencyKeys {
    public static String outbound(String target, String operation, String recordId, Decimal version) {
        return target.toLowerCase() + ':' + operation + ':' + recordId + ':v' + String.valueOf(version.intValue());
    }

    public static String repair(String outboundKey, String runId) {
        return outboundKey + ':repair:' + runId;
    }

    public static String inbound(String source, String eventId) {
        return source + '-in:' + eventId;
    }
}
