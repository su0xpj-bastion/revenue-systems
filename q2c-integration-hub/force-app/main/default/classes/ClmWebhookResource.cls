/**
 * POST /services/apexrest/q2c/clm/v1/events, called by the CLM provider through a dedicated
 * integration user (never a guest site).
 *
 * Response codes are chosen for the sender's retry logic:
 *   401  bad or stale signature    sender should NOT retry; a person fixes the secret
 *   400  malformed body            sender should NOT retry
 *   200  accepted (applied, duplicate, stale, parked, dead or ignored type). Once stored, the event
 *        is our problem: a non-2xx would make the sender retry something we already hold.
 *   500  could not store the event sender SHOULD retry (same eventId, so the retry is deduped)
 */
@RestResource(urlMapping='/q2c/clm/v1/events')
global with sharing class ClmWebhookResource {
    @HttpPost
    global static void receive() {
        RestRequest req = RestContext.request;
        RestResponse res = RestContext.response;
        String body = req.requestBody == null ? null : req.requestBody.toString();

        Boolean signed = WebhookSignature.verify(
            SyncConfig.webhookSecret(),
            req.headers.get('X-CLM-Timestamp'),
            req.headers.get('X-CLM-Signature'),
            body,
            System.now().getTime() / 1000
        );
        if (!signed) {
            respond(res, 401, 'bad_signature', null);
            return;
        }

        Map<String, Object> evt;
        try {
            evt = (Map<String, Object>) JSON.deserializeUntyped(body);
        } catch (Exception e) {
            respond(res, 400, 'bad_json', null);
            return;
        }
        String eventId = (String) evt.get('eventId');
        String type = (String) evt.get('type');
        if (String.isBlank(eventId) || String.isBlank(type) || evt.get('externalReference') == null || evt.get('agreementVersion') == null) {
            respond(res, 400, 'missing_fields', 'eventId, type, externalReference and agreementVersion are required');
            return;
        }
        if (ContractStateMachine.statusForClmEvent(type) == null) {
            respond(res, 200, 'ignored_type', type);
            return;
        }

        Sync_Message__c msg = new Sync_Message__c(
            Idempotency_Key__c = IdempotencyKeys.inbound('clm', eventId),
            Direction__c = 'Inbound',
            Target__c = 'CLM',
            Operation__c = type,
            Record_Id__c = String.valueOf(evt.get('externalReference')).left(18),
            Entity_Version__c = Decimal.valueOf(String.valueOf(evt.get('agreementVersion'))),
            Payload__c = body,
            Status__c = 'Pending',
            Attempts__c = 1,
            Correlation_Id__c = eventId.left(64)
        );
        Database.SaveResult sr = Database.insert(msg, false);
        if (!sr.isSuccess()) {
            if (sr.getErrors()[0].getStatusCode() == StatusCode.DUPLICATE_VALUE) {
                respond(res, 200, 'duplicate', eventId);
            } else {
                respond(res, 500, 'store_failed', sr.getErrors()[0].getMessage());
            }
            return;
        }
        InboundApplier.apply(msg);
        respond(res, 200, msg.Status__c, msg.Last_Error__c);
    }

    static void respond(RestResponse res, Integer status, String outcome, String detail) {
        res.statusCode = status;
        res.addHeader('Content-Type', 'application/json');
        res.responseBody = Blob.valueOf(JSON.serialize(new Map<String, Object>{ 'outcome' => outcome, 'detail' => detail }));
    }
}
