/**
 * Quote lifecycle guard on SBQQ__Quote__c (before update).
 *
 *  1. Status changes must follow QuoteStatusMachine, whatever path the update came from.
 *  2. An Approved or Presented quote whose recalculated approval level goes UP returns to Draft.
 *     Approval was given for a smaller ask, so re-pricing after approval can't keep the approval.
 *  3. Accepting a quote marks it Ordered, so CPQ generates the order with no manual step.
 *
 * Works on in-memory records (no queries, no DML), so it is unit-testable without CPQ calculation.
 */
public with sharing class QuoteTriggerHandler {

    public static Boolean bypass = false;

    public static void beforeUpdate(List<SBQQ__Quote__c> newQuotes, Map<Id, SBQQ__Quote__c> oldQuotes) {
        if (bypass) {
            return;
        }
        for (SBQQ__Quote__c quote : newQuotes) {
            SBQQ__Quote__c old = oldQuotes.get(quote.Id);
            String fromStatus = old.SBQQ__Status__c;

            Boolean approvedState = fromStatus == 'Approved' || fromStatus == 'Presented';
            if (approvedState && quote.SBQQ__Status__c == fromStatus
                    && quote.Approval_Level__c != null && old.Approval_Level__c != null
                    && quote.Approval_Level__c > old.Approval_Level__c) {
                quote.SBQQ__Status__c = 'Draft';
                quote.Approval_Reasons__c = 'Returned to Draft: approval level rose from '
                    + old.Approval_Level__c + ' to ' + quote.Approval_Level__c + ' after approval. '
                    + (quote.Approval_Reasons__c == null ? '' : quote.Approval_Reasons__c);
                continue;
            }

            if (!QuoteStatusMachine.canTransition(fromStatus, quote.SBQQ__Status__c, quote.Approval_Level__c)) {
                quote.SBQQ__Status__c.addError('Quote status cannot move from ' + fromStatus + ' to '
                                               + quote.SBQQ__Status__c + '.');
                continue;
            }

            if (quote.SBQQ__Status__c == 'Accepted' && fromStatus != 'Accepted' && quote.SBQQ__Ordered__c != true) {
                quote.SBQQ__Ordered__c = true;
            }
        }
    }
}
