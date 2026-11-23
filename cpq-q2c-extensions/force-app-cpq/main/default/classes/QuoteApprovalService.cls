/**
 * Approval automation on top of CPQ Advanced Approvals (sbaa).
 *
 * The QCP writes Approval_Level__c on every calculation. Advanced Approvals rules route on it
 * (level 1 Deal Desk, 2 Finance, 3 CFO, each a chained rule). This service decides whether a
 * submission needs approvers at all:
 *   level 0 → Draft → Approved directly (no approval record; the status machine allows it only at 0)
 *   level ≥ 1 → SBAA.ApprovalAPI.submit, which evaluates the rules and sets status to In Review
 *
 * Requires a lookup field Quote__c on sbaa__Approval__c (standard Advanced Approvals setup).
 */
public with sharing class QuoteApprovalService {

    public class Request {
        @InvocableVariable(required=true label='Quote Id') public Id quoteId;
    }

    @InvocableMethod(label='Submit quote for approval' category='CPQ')
    public static void submitFromFlow(List<Request> requests) {
        for (Request r : requests) {
            submit(r.quoteId);
        }
    }

    public static void submit(Id quoteId) {
        SBQQ__Quote__c quote = [
            SELECT Id, SBQQ__Status__c, Approval_Level__c
            FROM SBQQ__Quote__c WHERE Id = :quoteId WITH USER_MODE
        ];
        if (quote.SBQQ__Status__c != 'Draft') {
            throw new QuoteStatusMachine.TransitionException('Only Draft quotes can be submitted; this one is '
                                                             + quote.SBQQ__Status__c + '.');
        }
        if (quote.Approval_Level__c == null) {
            throw new QuoteStatusMachine.TransitionException('Calculate the quote before submitting it.');
        }
        if (quote.Approval_Level__c == 0) {
            quote.SBQQ__Status__c = 'Approved';
            update as user quote;
            return;
        }
        SBAA.ApprovalAPI.submit(quoteId, SBAA__Approval__c.Quote__c);
    }

    public static void recall(Id quoteId) {
        SBAA.ApprovalAPI.recall(quoteId, SBAA__Approval__c.Quote__c);
    }
}
