/**
 * Trigger -> Platform Event -> outbox, end to end inside one test.
 */
@IsTest
private class ContractSyncFlowTest {
    @IsTest
    static void billingFieldChangeBumpsVersionOnce() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Decimal before = c.Version__c;
        c.End_Date__c = Date.newInstance(2027, 6, 30);
        update c;
        Assert.areEqual(before + 1, [SELECT Version__c FROM Q2C_Contract__c WHERE Id = :c.Id].Version__c);
    }

    @IsTest
    static void nonBillingFieldDoesNotBump() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Decimal before = c.Version__c;
        update new Q2C_Contract__c(Id = c.Id, Last_Synced_Version__c = before);
        Assert.areEqual(before, [SELECT Version__c FROM Q2C_Contract__c WHERE Id = :c.Id].Version__c);
    }

    @IsTest
    static void illegalTransitionIsRejected() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Draft');
        c.Status__c = 'Active';
        Database.SaveResult sr = Database.update(c, false);
        Assert.isFalse(sr.isSuccess());
        Assert.isTrue(sr.getErrors()[0].getMessage().contains('cannot move from Draft to Active'));
    }

    @IsTest
    static void versionCannotMoveBackwards() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Draft');
        c.Version__c = c.Version__c - 1;
        Assert.isFalse(Database.update(c, false).isSuccess());
    }

    @IsTest
    static void bulkSubscriptionChangeBumpsParentOnce() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        List<Q2C_Subscription__c> subs = [SELECT Id, Quantity__c FROM Q2C_Subscription__c WHERE Contract__c = :c.Id];
        for (Q2C_Subscription__c s : subs) {
            s.Quantity__c = s.Quantity__c + 5;
        }
        update subs;
        Assert.areEqual(c.Version__c + 1, [SELECT Version__c FROM Q2C_Contract__c WHERE Id = :c.Id].Version__c);
    }

    @IsTest
    static void duplicateProductLineIsRejected() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Draft');
        Database.SaveResult sr = Database.insert(
            new Q2C_Subscription__c(Contract__c = c.Id, Product_Code__c = 'SEATS', Quantity__c = 1, Unit_Price__c = 1), false);
        Assert.isFalse(sr.isSuccess());
        Assert.areEqual(StatusCode.DUPLICATE_VALUE, sr.getErrors()[0].getStatusCode());
    }

    @IsTest
    static void eventsBecomeOneMessagePerVersionAndTarget() {
        SyncTestData.settings(false); // queue only, no dispatch
        Q2C_Contract__c c = SyncTestData.contract('Draft');
        Test.startTest();
        c.Status__c = 'Out_For_Signature';
        update c;
        c.Status__c = 'Signed';
        update c;
        Test.getEventBus().deliver();
        Test.stopTest();

        Q2C_Contract__c now = [SELECT Version__c FROM Q2C_Contract__c WHERE Id = :c.Id];
        List<Sync_Message__c> msgs = [
            SELECT Target__c, Operation__c, Entity_Version__c, Idempotency_Key__c, Payload__c
            FROM Sync_Message__c WHERE Record_Id__c = :String.valueOf(c.Id)
        ];
        // Both events resolve to the contract's current state (Signed, latest version) -> one Billing message.
        Assert.areEqual(1, msgs.size(), 'two events for one contract collapse into one message');
        Assert.areEqual('Billing', msgs[0].Target__c);
        Assert.areEqual(now.Version__c, msgs[0].Entity_Version__c);
        Map<String, Object> payload = (Map<String, Object>) JSON.deserializeUntyped(msgs[0].Payload__c);
        Assert.areEqual('q2c.contract.v1', payload.get('schema'));
        Assert.areEqual(2, ((List<Object>) payload.get('lines')).size());
    }

    @IsTest
    static void redeliveredEventsCreateNothingNew() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Q2C_Change__e evt = new Q2C_Change__e(Record_Id__c = c.Id, Entity__c = 'Q2C_Contract__c', Version__c = c.Version__c, Change__c = 'updated');
        OutboxService.Outcome first = OutboxService.enqueueFromEvents(new List<Q2C_Change__e>{ evt });
        OutboxService.Outcome second = OutboxService.enqueueFromEvents(new List<Q2C_Change__e>{ evt, evt });
        Assert.areEqual(1, first.inserted);
        Assert.areEqual(0, second.inserted);
        Assert.areEqual(1, [SELECT COUNT() FROM Sync_Message__c WHERE Record_Id__c = :String.valueOf(c.Id)]);
    }

    @IsTest
    static void cancelRoutesToBillingAndClm() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Cancelled');
        OutboxService.enqueueContracts(new Set<Id>{ c.Id }, null, null);
        Set<String> ops = new Set<String>();
        for (Sync_Message__c m : [SELECT Operation__c FROM Sync_Message__c WHERE Record_Id__c = :String.valueOf(c.Id)]) {
            ops.add(m.Operation__c);
        }
        Assert.areEqual(new Set<String>{ 'cancel_contract', 'void_agreement' }, ops);
    }
}
