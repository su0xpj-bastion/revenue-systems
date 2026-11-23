/**
 * Contract lifecycle with real DML on standard Contract records. Runs in any org; no CPQ needed.
 * Vector-driven checks for the same rules live in PricingVectorsTest.
 */
@IsTest
private class ContractLifecycleTest {

    @TestSetup
    static void setup() {
        Account account = new Account(Name = 'Lifecycle Test Co');
        insert account;
        insert new Contract(AccountId = account.Id, StartDate = Date.today(), ContractTerm = 12);
    }

    private static Contract contract() {
        return [SELECT Id, Lifecycle_Status__c, CustomerSignedDate, Termination_Reason__c FROM Contract LIMIT 1];
    }

    private static Database.SaveResult moveTo(String status) {
        Contract c = contract();
        c.Lifecycle_Status__c = status;
        return Database.update(c, false);
    }

    @IsTest
    static void startsInDraft() {
        Assert.areEqual('Draft', contract().Lifecycle_Status__c);
    }

    @IsTest
    static void happyPathStampsSignedDate() {
        Test.startTest();
        Assert.isTrue(moveTo('In Negotiation').isSuccess());
        Assert.isTrue(moveTo('Signed').isSuccess());
        Assert.isTrue(moveTo('Active').isSuccess());
        Test.stopTest();
        Assert.areEqual(Date.today(), contract().CustomerSignedDate);
    }

    @IsTest
    static void cannotActivateUnsignedContract() {
        Database.SaveResult result = moveTo('Active');
        Assert.isFalse(result.isSuccess());
        Assert.isTrue(result.getErrors()[0].getMessage().contains('Draft to Active'));
    }

    @IsTest
    static void terminationNeedsReason() {
        moveTo('In Negotiation');
        moveTo('Signed');
        moveTo('Active');
        Assert.isFalse(moveTo('Terminated').isSuccess(), 'no reason given');

        Contract c = contract();
        c.Lifecycle_Status__c = 'Terminated';
        c.Termination_Reason__c = 'Customer acquired; mutual termination';
        Assert.isTrue(Database.update(c, false).isSuccess());
    }

    @IsTest
    static void bulkUpdatesAreChecked() {
        Account account = [SELECT Id FROM Account LIMIT 1];
        List<Contract> contracts = new List<Contract>();
        for (Integer i = 0; i < 200; i++) {
            contracts.add(new Contract(AccountId = account.Id, StartDate = Date.today(), ContractTerm = 12));
        }
        insert contracts;
        for (Contract c : contracts) {
            c.Lifecycle_Status__c = 'Signed';            // skips In Negotiation
        }
        Test.startTest();
        List<Database.SaveResult> results = Database.update(contracts, false);
        Test.stopTest();
        for (Database.SaveResult r : results) {
            Assert.isFalse(r.isSuccess());
        }
    }
}
