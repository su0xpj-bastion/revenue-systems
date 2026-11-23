/**
 * Handler tests on in-memory quotes (no DML), so CPQ's own triggers and calculator are not involved.
 * Requires the CPQ package only because the SObject type is SBQQ__Quote__c.
 */
@IsTest
private class QuoteTriggerHandlerTest {

    private static Integer counter = 0;

    private static Id fakeId() {
        counter++;
        String prefix = SBQQ__Quote__c.SObjectType.getDescribe().getKeyPrefix();
        return Id.valueOf(prefix + String.valueOf(counter).leftPad(12, '0'));
    }

    private static SBQQ__Quote__c quote(Id id, String status, Decimal level) {
        return new SBQQ__Quote__c(Id = id, SBQQ__Status__c = status, Approval_Level__c = level, SBQQ__Ordered__c = false);
    }

    private static SBQQ__Quote__c run(SBQQ__Quote__c oldQuote, SBQQ__Quote__c newQuote) {
        QuoteTriggerHandler.beforeUpdate(new List<SBQQ__Quote__c>{ newQuote },
                                         new Map<Id, SBQQ__Quote__c>{ oldQuote.Id => oldQuote });
        return newQuote;
    }

    @IsTest
    static void legalTransitionPasses() {
        Id id = fakeId();
        SBQQ__Quote__c result = run(quote(id, 'Draft', 2), quote(id, 'In Review', 2));
        Assert.isFalse(result.hasErrors());
    }

    @IsTest
    static void skippingApprovalIsBlocked() {
        Id id = fakeId();
        SBQQ__Quote__c result = run(quote(id, 'Draft', 2), quote(id, 'Approved', 2));
        Assert.isTrue(result.hasErrors());
    }

    @IsTest
    static void autoApprovalAtLevelZero() {
        Id id = fakeId();
        SBQQ__Quote__c result = run(quote(id, 'Draft', 0), quote(id, 'Approved', 0));
        Assert.isFalse(result.hasErrors());
    }

    @IsTest
    static void repricingAfterApprovalReturnsToDraft() {
        Id id = fakeId();
        SBQQ__Quote__c result = run(quote(id, 'Approved', 1), quote(id, 'Approved', 2));
        Assert.areEqual('Draft', result.SBQQ__Status__c);
        Assert.isTrue(result.Approval_Reasons__c.startsWith('Returned to Draft'));
    }

    @IsTest
    static void repricingDownKeepsApproval() {
        Id id = fakeId();
        SBQQ__Quote__c result = run(quote(id, 'Approved', 2), quote(id, 'Approved', 1));
        Assert.areEqual('Approved', result.SBQQ__Status__c);
    }

    @IsTest
    static void acceptanceMarksOrdered() {
        Id id = fakeId();
        SBQQ__Quote__c result = run(quote(id, 'Presented', 1), quote(id, 'Accepted', 1));
        Assert.isTrue(result.SBQQ__Ordered__c);
    }

    @IsTest
    static void bypassSkipsAllChecks() {
        Id id = fakeId();
        QuoteTriggerHandler.bypass = true;
        SBQQ__Quote__c result = run(quote(id, 'Draft', 3), quote(id, 'Accepted', 3));
        Assert.isFalse(result.hasErrors());
    }
}
