@IsTest
private class OutboxDispatcherTest {
    static Sync_Message__c reload(Id msgId) {
        return [SELECT Status__c, Attempts__c, Last_Status_Code__c, Next_Attempt_At__c, Last_Error__c FROM Sync_Message__c WHERE Id = :msgId];
    }

    @IsTest
    static void ackSendsHeadersAndMarksContractSynced() {
        SyncTestData.settings(true);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert m;
        SyncTestData.SequenceMock mock = new SyncTestData.SequenceMock(new List<Integer>{ 200 });
        Test.setMock(HttpCalloutMock.class, mock);

        Test.startTest();
        OutboxDispatcher.DispatchSummary s = OutboxDispatcher.dispatchDue();
        Test.stopTest();

        Assert.areEqual(1, s.acked);
        Assert.areEqual('Acked', reload(m.Id).Status__c);
        HttpRequest sent = mock.requests[0];
        Assert.areEqual('PUT', sent.getMethod());
        Assert.areEqual(m.Idempotency_Key__c, sent.getHeader('Idempotency-Key'));
        Assert.isTrue(sent.getEndpoint().startsWith('callout:Billing_Core/v1/contracts/'));
        Assert.areEqual(c.Version__c, [SELECT Last_Synced_Version__c FROM Q2C_Contract__c WHERE Id = :c.Id].Last_Synced_Version__c);
    }

    @IsTest
    static void transientFailureRetriesWithBackoff() {
        SyncTestData.settings(true); // Max_Attempts__c = 3
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert m;
        Test.setMock(HttpCalloutMock.class, new SyncTestData.SequenceMock(new List<Integer>{ 503 }));

        Test.startTest();
        OutboxDispatcher.dispatchDue();
        Test.stopTest();

        Sync_Message__c after = reload(m.Id);
        Assert.areEqual('Retrying', after.Status__c);
        Assert.areEqual(1, after.Attempts__c);
        Assert.areEqual(503, after.Last_Status_Code__c);
        Assert.isTrue(after.Next_Attempt_At__c > System.now().addSeconds(14), 'first retry waits at least base/2');
    }

    @IsTest
    static void lastAllowedAttemptGoesDead() {
        SyncTestData.settings(true); // Max_Attempts__c = 3
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        m.Status__c = 'Retrying';
        m.Attempts__c = 2;
        insert m;
        Test.setMock(HttpCalloutMock.class, new SyncTestData.SequenceMock(new List<Integer>{ 503 }));

        Test.startTest();
        OutboxDispatcher.dispatchDue();
        Test.stopTest();

        Sync_Message__c after = reload(m.Id);
        Assert.areEqual('Dead', after.Status__c);
        Assert.areEqual(3, after.Attempts__c);
        Assert.isNull(after.Next_Attempt_At__c);
    }

    @IsTest
    static void timeoutIsRetried() {
        SyncTestData.settings(true);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert m;
        Test.setMock(HttpCalloutMock.class, new SyncTestData.SequenceMock(new List<Integer>{ -1 }));
        Test.startTest();
        OutboxDispatcher.dispatchDue();
        Test.stopTest();
        Assert.areEqual('Retrying', reload(m.Id).Status__c);
    }

    @IsTest
    static void contractErrorIsDeadImmediately() {
        SyncTestData.settings(true);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert m;
        Test.setMock(HttpCalloutMock.class, new SyncTestData.SequenceMock(new List<Integer>{ 422 }));
        Test.startTest();
        OutboxDispatcher.dispatchDue();
        Test.stopTest();
        Sync_Message__c after = reload(m.Id);
        Assert.areEqual('Dead', after.Status__c);
        Assert.isNull([SELECT Last_Synced_Version__c FROM Q2C_Contract__c WHERE Id = :c.Id].Last_Synced_Version__c);
    }

    @IsTest
    static void olderVersionIsSupersededWithoutSending() {
        SyncTestData.settings(true);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c older = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c - 1);
        Sync_Message__c newer = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert new List<Sync_Message__c>{ older, newer };
        SyncTestData.SequenceMock mock = new SyncTestData.SequenceMock(new List<Integer>{ 200 });
        Test.setMock(HttpCalloutMock.class, mock);
        Test.startTest();
        OutboxDispatcher.DispatchSummary s = OutboxDispatcher.dispatchDue();
        Test.stopTest();
        Assert.areEqual(1, mock.requests.size(), 'only the newest version goes out');
        Assert.areEqual('Superseded', reload(older.Id).Status__c);
        Assert.areEqual('Acked', reload(newer.Id).Status__c);
        Assert.areEqual(1, s.superseded);
    }

    @IsTest
    static void conflictFromTargetMeansSuperseded() {
        SyncTestData.settings(true);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert m;
        Test.setMock(HttpCalloutMock.class, new SyncTestData.SequenceMock(new List<Integer>{ 409 }));
        Test.startTest();
        OutboxDispatcher.dispatchDue();
        Test.stopTest();
        Assert.areEqual('Superseded', reload(m.Id).Status__c);
    }

    @IsTest
    static void killSwitchSendsNothing() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert m;
        SyncTestData.SequenceMock mock = new SyncTestData.SequenceMock(new List<Integer>{ 200 });
        Test.setMock(HttpCalloutMock.class, mock);
        Test.startTest();
        OutboxDispatcher.dispatchDue();
        Test.stopTest();
        Assert.areEqual(0, mock.requests.size());
        Assert.areEqual('Pending', reload(m.Id).Status__c);
    }

    @IsTest
    static void routesEachOperationToItsEndpoint() {
        SyncTestData.settings(true);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Map<String, String> expected = new Map<String, String>{
            'upsert_contract' => 'PUT callout:Billing_Core/v1/contracts/' + c.Id,
            'cancel_contract' => 'POST callout:Billing_Core/v1/contracts/' + c.Id + '/cancel',
            'upsert_agreement' => 'PUT callout:CLM/v1/agreements/by-reference/' + c.Id,
            'void_agreement' => 'POST callout:CLM/v1/agreements/by-reference/' + c.Id + '/void'
        };
        for (String op : expected.keySet()) {
            String target = op.contains('agreement') ? 'CLM' : 'Billing';
            HttpRequest req = HttpSyncTransport.buildRequest(SyncTestData.outbound(c, target, op, 1));
            Assert.areEqual(expected.get(op), req.getMethod() + ' ' + req.getEndpoint());
        }
    }
}
