/**
 * Contract lifecycle on Contract.Lifecycle_Status__c (kept separate from the standard Status
 * picklist, whose Activated value carries platform activation semantics).
 *
 *   Draft → In Negotiation → Signed → Active → Expiring → Renewed
 *              ↓                         ↓          ↓  → Expired
 *            Draft                   Terminated  Terminated
 */
public with sharing class ContractLifecycle {

    private static final Map<String, Set<String>> TRANSITIONS = new Map<String, Set<String>>{
        'Draft'          => new Set<String>{ 'In Negotiation' },
        'In Negotiation' => new Set<String>{ 'Signed', 'Draft' },
        'Signed'         => new Set<String>{ 'Active' },
        'Active'         => new Set<String>{ 'Expiring', 'Terminated' },
        'Expiring'       => new Set<String>{ 'Renewed', 'Expired', 'Terminated' },
        'Renewed'        => new Set<String>(),
        'Expired'        => new Set<String>(),
        'Terminated'     => new Set<String>()
    };

    public static Boolean canTransition(String fromStatus, String toStatus) {
        if (fromStatus == toStatus) {
            return true;
        }
        Set<String> allowed = TRANSITIONS.get(fromStatus);
        return allowed != null && allowed.contains(toStatus);
    }
}
