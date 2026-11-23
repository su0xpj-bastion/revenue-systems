/**
 * Allowed SBQQ__Quote__c status transitions. Enforced by the quote trigger, so a quote cannot
 * skip approval by editing the Status picklist, inline, through Data Loader, or from an integration.
 *
 *   Draft → In Review → Approved → Presented → Accepted
 *             ↓  ↑          ↓          ↓
 *          Denied ↗       Draft     Rejected
 *
 * Draft → Approved is allowed only when the computed approval level is 0 (within rep authority).
 */
public with sharing class QuoteStatusMachine {

    public class TransitionException extends Exception {}

    private static final Map<String, Set<String>> TRANSITIONS = new Map<String, Set<String>>{
        'Draft'     => new Set<String>{ 'In Review' },
        'In Review' => new Set<String>{ 'Approved', 'Denied', 'Draft' },
        'Approved'  => new Set<String>{ 'Presented', 'Draft' },
        'Presented' => new Set<String>{ 'Accepted', 'Rejected', 'Draft' },
        'Denied'    => new Set<String>{ 'Draft' },
        'Accepted'  => new Set<String>(),
        'Rejected'  => new Set<String>()
    };

    public static Boolean canTransition(String fromStatus, String toStatus) {
        return canTransition(fromStatus, toStatus, null);
    }

    public static Boolean canTransition(String fromStatus, String toStatus, Decimal approvalLevel) {
        if (fromStatus == toStatus) {
            return true;
        }
        if (fromStatus == 'Draft' && toStatus == 'Approved') {
            return approvalLevel != null && approvalLevel == 0;
        }
        Set<String> allowed = TRANSITIONS.get(fromStatus);
        return allowed != null && allowed.contains(toStatus);
    }

    public static void assertTransition(String fromStatus, String toStatus, Decimal approvalLevel) {
        if (!canTransition(fromStatus, toStatus, approvalLevel)) {
            throw new TransitionException('Quote status cannot move from ' + fromStatus + ' to ' + toStatus + '.');
        }
    }
}
