@IsTest
public class SyncTestData {
    public static final String SECRET = 'test-webhook-secret';

    public static void settings(Boolean outboundEnabled) {
        SyncConfig.testOverride = new Q2C_Integration_Settings__c(
            Outbound_Enabled__c = outboundEnabled,
            Max_Attempts__c = 3,
            Dispatch_Batch_Size__c = 50,
            Webhook_Secret__c = SECRET
        );
    }

    public static Q2C_Contract__c contract(String status) {
        Q2C_Contract__c c = new Q2C_Contract__c(
            Billing_Account_Id__c = 'ba_123',
            Start_Date__c = Date.newInstance(2026, 1, 1),
            End_Date__c = Date.newInstance(2026, 12, 31)
        );
        insert c;
        insert new List<Q2C_Subscription__c>{
            new Q2C_Subscription__c(Contract__c = c.Id, Product_Code__c = 'SEATS', Quantity__c = 10, Unit_Price__c = 12),
            new Q2C_Subscription__c(Contract__c = c.Id, Product_Code__c = 'API', Quantity__c = 1, Unit_Price__c = 500)
        };
        // Walk the legal path to the requested status.
        List<String> path = new List<String>{ 'Draft', 'Out_For_Signature', 'Signed', 'Active' };
        if (status == 'Cancelled') {
            c.Status__c = 'Cancelled';
            update c;
        } else {
            for (Integer i = 1; i <= path.indexOf(status); i++) {
                c.Status__c = path[i];
                update c;
            }
        }
        return [SELECT Id, Status__c, Version__c, Last_Synced_Version__c, CLM_Version__c FROM Q2C_Contract__c WHERE Id = :c.Id];
    }

    public static Sync_Message__c outbound(Q2C_Contract__c c, String target, String operation, Decimal version) {
        return new Sync_Message__c(
            Idempotency_Key__c = IdempotencyKeys.outbound(target, operation, c.Id, version),
            Direction__c = 'Outbound',
            Target__c = target,
            Operation__c = operation,
            Record_Id__c = c.Id,
            Entity_Version__c = version,
            Payload__c = '{}',
            Status__c = 'Pending',
            Attempts__c = 0,
            Next_Attempt_At__c = System.now().addSeconds(-1)
        );
    }

    /** Answers every callout with the next queued status (the last one repeats), or throws a timeout. */
    public class SequenceMock implements HttpCalloutMock {
        public List<Integer> statuses;
        public List<HttpRequest> requests = new List<HttpRequest>();
        public String body = '{}';
        public SequenceMock(List<Integer> statuses) {
            this.statuses = statuses;
        }
        public HttpResponse respond(HttpRequest req) {
            requests.add(req);
            Integer status = statuses.size() > 1 ? statuses.remove(0) : statuses[0];
            if (status == -1) {
                throw new CalloutException('Read timed out');
            }
            HttpResponse res = new HttpResponse();
            res.setStatusCode(status);
            res.setBody(body);
            return res;
        }
    }
}
