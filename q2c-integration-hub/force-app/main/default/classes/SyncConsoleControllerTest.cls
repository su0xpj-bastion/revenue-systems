@IsTest
private class SyncConsoleControllerTest {
    static User operator(Boolean withPermission) {
        Profile p = [SELECT Id FROM Profile WHERE Name = 'Standard User' LIMIT 1];
        String uniq = String.valueOf(Crypto.getRandomInteger()).replace('-', '');
        User u = new User(
            ProfileId = p.Id, LastName = 'Operator', Alias = 'oper', Email = 'operator@example.invalid',
            Username = 'operator' + uniq + '@example.invalid', TimeZoneSidKey = 'America/Los_Angeles',
            LocaleSidKey = 'en_US', EmailEncodingKey = 'UTF-8', LanguageLocaleKey = 'en_US'
        );
        insert u;
        if (withPermission) {
            PermissionSet ps = [SELECT Id FROM PermissionSet WHERE Name = 'Q2C_Sync_Operator'];
            insert new PermissionSetAssignment(AssigneeId = u.Id, PermissionSetId = ps.Id);
        }
        return u;
    }

    @IsTest
    static void retryNeedsTheCustomPermission() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        m.Status__c = 'Dead';
        insert m;
        System.runAs(operator(false)) {
            try {
                SyncConsoleController.retry(m.Id);
                Assert.fail('expected AuraHandledException');
            } catch (AuraHandledException expected) {
                Assert.isTrue(true);
            }
        }
        Assert.areEqual('Dead', [SELECT Status__c FROM Sync_Message__c WHERE Id = :m.Id].Status__c);
    }

    @IsTest
    static void operatorRequeuesDeadMessageWithAuditNote() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        m.Status__c = 'Dead';
        m.Attempts__c = 8;
        m.Last_Error__c = 'HTTP 401';
        insert m;
        User u = operator(true);
        System.runAs(u) {
            Assert.areEqual('Pending', SyncConsoleController.retry(m.Id));
        }
        Sync_Message__c after = [SELECT Status__c, Attempts__c, Last_Error__c FROM Sync_Message__c WHERE Id = :m.Id];
        Assert.areEqual(0, after.Attempts__c);
        Assert.isTrue(after.Last_Error__c.startsWith('Re-queued by ' + u.Username));
        Assert.isTrue(after.Last_Error__c.contains('HTTP 401'), 'previous error is kept');
    }

    @IsTest
    static void ackedMessagesCannotBeRetried() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        Sync_Message__c m = SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        m.Status__c = 'Acked';
        insert m;
        System.runAs(operator(true)) {
            try {
                SyncConsoleController.retry(m.Id);
                Assert.fail('expected AuraHandledException');
            } catch (AuraHandledException expected) {
                Assert.isTrue(true);
            }
        }
    }

    @IsTest
    static void loadSummarizesSyncState() {
        SyncTestData.settings(false);
        Q2C_Contract__c c = SyncTestData.contract('Active');
        insert SyncTestData.outbound(c, 'Billing', 'upsert_contract', c.Version__c);
        insert new Recon_Break__c(Contract__c = c.Id, Kind__c = 'Price_Mismatch', Line_Key__c = c.Id + ':API');
        SyncConsoleController.Summary s = SyncConsoleController.load(c.Id);
        Assert.areEqual('Active', s.status);
        Assert.isFalse(s.inSync, 'nothing acked yet');
        Assert.areEqual(1, s.messages.size());
        Assert.areEqual(1, s.openBreaks.size());
    }
}
