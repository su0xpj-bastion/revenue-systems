/**
 * Covers the non-CPQ paths of the renewal job (owner notification, expiring, expiry) with real
 * Contract DML. The auto-renew path calls the CPQ Contract Renewer and is exercised in a CPQ org
 * with real subscriptions.
 */
@IsTest
private class RenewalNoticeJobTest {

    private static Contract activeContract(Boolean autoRenew) {
        Account account = new Account(Name = 'Renewal Job Co');
        insert account;
        Contract c = new Contract(AccountId = account.Id, StartDate = Date.newInstance(2027, 1, 1),
                                  ContractTerm = 12, Auto_Renew__c = autoRenew, Notice_Days__c = 60);
        insert c;
        for (String status : new List<String>{ 'In Negotiation', 'Signed', 'Active' }) {
            c.Lifecycle_Status__c = status;
            update c;
        }
        return [SELECT Id, EndDate, Lifecycle_Status__c FROM Contract WHERE Id = :c.Id];
    }

    private static void runAsOf(Date asOf) {
        Test.startTest();
        Database.executeBatch(new RenewalNoticeJob(asOf), 1);
        Test.stopTest();
    }

    @IsTest
    static void nonAutoRenewInWindowNotifiesOwnerOnce() {
        Contract c = activeContract(false);
        Date inWindow = c.EndDate.addDays(-70);
        runAsOf(inWindow);

        Assert.areEqual('Expiring', [SELECT Lifecycle_Status__c FROM Contract WHERE Id = :c.Id].Lifecycle_Status__c);
        Assert.areEqual(1, [SELECT COUNT() FROM Task WHERE WhatId = :c.Id AND Subject = :RenewalNoticeJob.TASK_SUBJECT]);

        new RenewalNoticeJob(inWindow).execute(null, [
            SELECT Id, OwnerId, EndDate, Notice_Days__c, Auto_Renew__c, Renewal_Quote_Created__c, Lifecycle_Status__c
            FROM Contract WHERE Id = :c.Id
        ]);
        Assert.areEqual(1, [SELECT COUNT() FROM Task WHERE WhatId = :c.Id AND Subject = :RenewalNoticeJob.TASK_SUBJECT],
                        'second run does not duplicate the task');
    }

    @IsTest
    static void beforeWindowDoesNothing() {
        Contract c = activeContract(false);
        runAsOf(c.EndDate.addDays(-120));
        Assert.areEqual('Active', [SELECT Lifecycle_Status__c FROM Contract WHERE Id = :c.Id].Lifecycle_Status__c);
        Assert.areEqual(0, [SELECT COUNT() FROM Task WHERE WhatId = :c.Id]);
    }

    @IsTest
    static void expiringContractExpiresAfterEndDate() {
        Contract c = activeContract(false);
        c.Lifecycle_Status__c = 'Expiring';
        update c;
        runAsOf(c.EndDate.addDays(1));
        Assert.areEqual('Expired', [SELECT Lifecycle_Status__c FROM Contract WHERE Id = :c.Id].Lifecycle_Status__c);
    }
}
