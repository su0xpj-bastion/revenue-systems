/**
 * Sends one outbox message over HTTP through a Named Credential (Billing_Core or CLM), so no
 * endpoint or secret lives in code. Never throws: every outcome, including a timeout, comes back as
 * a Result for RetryPolicy to classify.
 */
public inherited sharing class HttpSyncTransport {
    public static final Integer TIMEOUT_MS = 10000;

    public class Result {
        public Integer status = 0;
        public Boolean timedOut = false;
        public String body;
        public String error;
    }

    static final Map<String, String> CREDENTIAL = new Map<String, String>{
        'Billing' => 'callout:Billing_Core',
        'CLM' => 'callout:CLM'
    };

    public static HttpRequest buildRequest(Sync_Message__c m) {
        String base = CREDENTIAL.get(m.Target__c);
        HttpRequest req = new HttpRequest();
        req.setTimeout(TIMEOUT_MS);
        req.setHeader('Content-Type', 'application/json');
        req.setHeader('Idempotency-Key', m.Idempotency_Key__c);
        req.setHeader('X-Entity-Version', String.valueOf(m.Entity_Version__c.intValue()));
        if (m.Correlation_Id__c != null) {
            req.setHeader('X-Correlation-Id', m.Correlation_Id__c);
        }
        switch on m.Operation__c {
            when 'upsert_contract' {
                req.setMethod('PUT');
                req.setEndpoint(base + '/v1/contracts/' + m.Record_Id__c);
            }
            when 'cancel_contract' {
                req.setMethod('POST');
                req.setEndpoint(base + '/v1/contracts/' + m.Record_Id__c + '/cancel');
            }
            when 'upsert_agreement' {
                req.setMethod('PUT');
                req.setEndpoint(base + '/v1/agreements/by-reference/' + m.Record_Id__c);
            }
            when 'void_agreement' {
                req.setMethod('POST');
                req.setEndpoint(base + '/v1/agreements/by-reference/' + m.Record_Id__c + '/void');
            }
            when else {
                throw new IllegalArgumentException('Unknown operation ' + m.Operation__c);
            }
        }
        req.setBody(m.Payload__c);
        return req;
    }

    public static Result send(Sync_Message__c m) {
        Result r = new Result();
        try {
            HttpResponse res = new Http().send(buildRequest(m));
            r.status = res.getStatusCode();
            r.body = res.getBody();
            if (r.status < 200 || r.status >= 300) {
                r.error = 'HTTP ' + r.status + ': ' + String.valueOf(r.body).left(2000);
            }
        } catch (CalloutException e) {
            r.timedOut = e.getMessage() != null && e.getMessage().containsIgnoreCase('timed out');
            r.error = e.getMessage();
        } catch (IllegalArgumentException e) {
            r.status = 400;
            r.error = e.getMessage();
        }
        return r;
    }
}
