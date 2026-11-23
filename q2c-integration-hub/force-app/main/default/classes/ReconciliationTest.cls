@IsTest
private class ReconciliationTest {
    static ReconciliationService.Line line(String key, Decimal qty, Decimal price) {
        return new ReconciliationService.Line(key, key.substringAfter(':'), qty, price);
    }

    static Set<String> kinds(List<ReconciliationService.Drift> breaks) {
        Set<String> out = new Set<String>();
        for (ReconciliationService.Drift b : breaks) {
            out.add(b.kind);
        }
        return out;
    }

    @IsTest
    static void matchingSidesHaveNoBreaks() {
        List<ReconciliationService.Line> sf = new List<ReconciliationService.Line>{ line('c:SEATS', 10, 12) };
        List<ReconciliationService.Line> billing = new List<ReconciliationService.Line>{ line('c:SEATS', 10.00, 12.0) };
        Assert.areEqual(0, ReconciliationService.compare('Active', sf, 'active', billing).size());
    }

    @IsTest
    static void everyKindOfDrift() {
        List<ReconciliationService.Line> sf = new List<ReconciliationService.Line>{
            line('c:SEATS', 10, 12), line('c:API', 1, 500), line('c:ONLY_SF', 1, 1)
        };
        List<ReconciliationService.Line> billing = new List<ReconciliationService.Line>{
            line('c:SEATS', 12, 12), line('c:API', 1, 450), line('c:ONLY_BILLING', 2, 2)
        };
        List<ReconciliationService.Drift> breaks = ReconciliationService.compare('Active', sf, 'cancelled', billing);
        Assert.areEqual(new Set<String>{
            'Status_Mismatch', 'Quantity_Mismatch', 'Price_Mismatch', 'Missing_In_Billing', 'Missing_In_Salesforce'
        }, kinds(breaks));
    }

    @IsTest
    static void notFoundInBilling() {
        Assert.areEqual(new Set<String>{ 'Missing_In_Billing' },
            kinds(ReconciliationService.compare('Signed', new List<ReconciliationService.Line>(), null, null)));
        Assert.areEqual(0, ReconciliationService.compare('Draft', new List<ReconciliationService.Line>(), null, null).size(),
            'drafts are not expected in Billing');
    }

    @IsTest
    static void jobRecordsBreaksAndQueuesRepair() {
        SyncTestData.settings(false); // repair is queued; nothing dispatched
        Q2C_Contract__c c = SyncTestData.contract('Active');
        update new Q2C_Contract__c(Id = c.Id, Last_Synced_Version__c = c.Version__c);
        SyncTestData.SequenceMock mock = new SyncTestData.SequenceMock(new List<Integer>{ 200 });
        mock.body = JSON.serialize(new Map<String, Object>{
            'status' => 'active',
            'version' => c.Version__c,
            'lines' => new List<Object>{
                new Map<String, Object>{ 'lineKey' => c.Id + ':SEATS', 'productCode' => 'SEATS', 'quantity' => 7, 'unitPrice' => 12 },
                new Map<String, Object>{ 'lineKey' => c.Id + ':API', 'productCode' => 'API', 'quantity' => 1, 'unitPrice' => 500 }
            }
        });
        Test.setMock(HttpCalloutMock.class, mock);

        Test.startTest();
        Database.executeBatch(new ReconciliationJob(true), 50);
        Test.stopTest();

        List<Recon_Break__c> breaks = [SELECT Kind__c, Salesforce_Value__c, Billing_Value__c FROM Recon_Break__c WHERE Contract__c = :c.Id];
        Assert.areEqual(1, breaks.size());
        Assert.areEqual('Quantity_Mismatch', breaks[0].Kind__c);
        Assert.areEqual('10.00', breaks[0].Salesforce_Value__c);
        Assert.areEqual('7.00', breaks[0].Billing_Value__c);
        Sync_Message__c repair = [SELECT Idempotency_Key__c, Status__c FROM Sync_Message__c WHERE Record_Id__c = :String.valueOf(c.Id)];
        Assert.isTrue(repair.Idempotency_Key__c.contains(':repair:recon-'), 'repair uses a fresh key');
    }

    @IsTest
    static void unsettledContractsAreSkipped() {
        SyncTestData.settings(false);
        SyncTestData.contract('Active'); // Last_Synced_Version__c is null: still in flight
        SyncTestData.SequenceMock mock = new SyncTestData.SequenceMock(new List<Integer>{ 404 });
        Test.setMock(HttpCalloutMock.class, mock);
        Test.startTest();
        Database.executeBatch(new ReconciliationJob(false), 50);
        Test.stopTest();
        Assert.areEqual(0, mock.requests.size());
        Assert.areEqual(0, [SELECT COUNT() FROM Recon_Break__c]);
    }
}
