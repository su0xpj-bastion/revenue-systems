@IsTest
private class ClmWebhookResourceTest {
    static Integer call(String body, Boolean goodSignature) {
        String ts = String.valueOf(System.now().getTime() / 1000);
        RestRequest req = new RestRequest();
        req.requestURI = '/services/apexrest/q2c/clm/v1/events';
        req.httpMethod = 'POST';
        req.requestBody = Blob.valueOf(body);
        req.addHeader('X-CLM-Timestamp', ts);
        req.addHeader('X-CLM-Signature', goodSignature ? WebhookSignature.sign(SyncTestData.SECRET, ts, body) : 'sha256=00');
        RestContext.request = req;
        RestContext.response = new RestResponse();
        ClmWebhookResource.receive();
        return RestContext.response.statusCode;
    }

    static String outcome() {
        return (String) ((Map<String, Object>) JSON.deserializeUntyped(RestContext.response.responseBody.toString())).get('outcome');
    }

    static String event(String eventId, String type, Id contractId, Integer version) {
        return JSON.serialize(new Map<String, Object>{
            'eventId' => eventId, 'type' => type, 'externalReference' => contractId,
            'agreementId' => 'agr_1', 'agreementVersion' => version
        });
    }

    @IsTest
    static void unsignedRequestIsRejected() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Out_For_Signature');
        Assert.areEqual(401, call(event('e1', 'agreement.signed', c.Id, 1), false));
        Assert.areEqual(0, [SELECT COUNT() FROM Sync_Message__c WHERE Direction__c = 'Inbound']);
    }

    @IsTest
    static void staleTimestampIsRejected() {
        String body = '{}';
        String old = String.valueOf(System.now().getTime() / 1000 - 3600);
        Assert.isFalse(WebhookSignature.verify('s', old, WebhookSignature.sign('s', old, body), body, System.now().getTime() / 1000));
    }

    @IsTest
    static void signedEventAppliesAndRedeliveryIsDuplicate() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Out_For_Signature');
        String body = event('evt_42', 'agreement.signed', c.Id, 1);

        Assert.areEqual(200, call(body, true));
        Assert.areEqual('Applied', outcome());
        Q2C_Contract__c after = [SELECT Status__c, CLM_Version__c, CLM_Agreement_Id__c, Signed_At__c, Version__c FROM Q2C_Contract__c WHERE Id = :c.Id];
        Assert.areEqual('Signed', after.Status__c);
        Assert.areEqual('agr_1', after.CLM_Agreement_Id__c);
        Assert.isNotNull(after.Signed_At__c);
        Assert.areEqual(c.Version__c + 1, after.Version__c, 'signing is a billing change');

        Assert.areEqual(200, call(body, true));
        Assert.areEqual('duplicate', outcome());
        Assert.areEqual(1, [SELECT COUNT() FROM Sync_Message__c WHERE Direction__c = 'Inbound']);
    }

    @IsTest
    static void outOfOrderOlderEventIsIgnored() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Out_For_Signature');
        call(event('evt_2', 'agreement.signed', c.Id, 2), true);
        Assert.areEqual(200, call(event('evt_1', 'agreement.sent', c.Id, 1), true));
        Assert.areEqual('Ignored_Stale', outcome());
        Assert.areEqual('Signed', [SELECT Status__c FROM Q2C_Contract__c WHERE Id = :c.Id].Status__c);
    }

    @IsTest
    static void illegalTransitionIsDeadNotApplied() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Cancelled');
        Assert.areEqual(200, call(event('evt_9', 'agreement.signed', c.Id, 5), true));
        Assert.areEqual('Dead', outcome());
        Assert.areEqual('Cancelled', [SELECT Status__c FROM Q2C_Contract__c WHERE Id = :c.Id].Status__c);
    }

    @IsTest
    static void unknownContractIsParked() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Draft');
        Id missing = c.Id;
        delete c;
        Assert.areEqual(200, call(event('evt_7', 'agreement.signed', missing, 1), true));
        Assert.areEqual('Parked', outcome());
    }

    @IsTest
    static void malformedAndUnknownTypes() {
        SyncTestData.settings(false);
        Assert.areEqual(400, call('not json', true));
        Assert.areEqual(400, call('{"type":"agreement.signed"}', true));
        Q2C_Contract__c c = SyncTestData.contract('Draft');
        Assert.areEqual(200, call(event('evt_x', 'agreement.commented', c.Id, 1), true));
        Assert.areEqual('ignored_type', outcome());
    }

    @IsTest
    static void constantTimeCompare() {
        Assert.isTrue(WebhookSignature.constantTimeEquals('abc', 'abc'));
        Assert.isFalse(WebhookSignature.constantTimeEquals('abc', 'abd'));
        Assert.isFalse(WebhookSignature.constantTimeEquals('abc', 'ab'));
    }
}
