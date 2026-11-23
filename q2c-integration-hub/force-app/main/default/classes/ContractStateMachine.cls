/**
 * Contract lifecycle rules, kept in one place so the trigger, the CLM webhook and the operator
 * console all enforce the same transitions. Pure: no queries, no DML.
 *
 *   Draft -> Out_For_Signature -> Signed -> Active
 *     ^            |                |         |
 *     +------------+                v         v
 *   (any non-terminal state)  ---> Cancelled (terminal)
 *
 * Same rules as vectors/sync-vectors.json -> "transitions", "outbound", "inbound".
 */
public inherited sharing class ContractStateMachine {
    public static final String DRAFT = 'Draft';
    public static final String OUT_FOR_SIGNATURE = 'Out_For_Signature';
    public static final String SIGNED = 'Signed';
    public static final String ACTIVE = 'Active';
    public static final String CANCELLED = 'Cancelled';

    static final Map<String, Set<String>> NEXT = new Map<String, Set<String>>{
        DRAFT => new Set<String>{ OUT_FOR_SIGNATURE, CANCELLED },
        OUT_FOR_SIGNATURE => new Set<String>{ DRAFT, SIGNED, CANCELLED },
        SIGNED => new Set<String>{ ACTIVE, CANCELLED },
        ACTIVE => new Set<String>{ CANCELLED },
        CANCELLED => new Set<String>()
    };

    static final Map<String, String> CLM_EVENT_TO_STATUS = new Map<String, String>{
        'agreement.sent' => OUT_FOR_SIGNATURE,
        'agreement.signed' => SIGNED,
        'agreement.voided' => CANCELLED
    };

    /** Where a contract in this status must be sent, and with which operation. */
    public class Route {
        public String target;
        public String operation;
        public Route(String target, String operation) {
            this.target = target;
            this.operation = operation;
        }
    }

    public static Boolean canTransition(String fromStatus, String toStatus) {
        if (fromStatus == toStatus) {
            return true;
        }
        Set<String> allowed = NEXT.get(fromStatus);
        return allowed != null && allowed.contains(toStatus);
    }

    /** Null for event types this org doesn't act on (accepted and ignored, for forward compatibility). */
    public static String statusForClmEvent(String eventType) {
        return CLM_EVENT_TO_STATUS.get(eventType);
    }

    /**
     * Billing only learns about contracts once they're signed; drafts are CLM's business.
     * Every operation is an upsert or an idempotent state change keyed by the Salesforce record Id,
     * so sending the latest snapshot again is always safe.
     */
    public static List<Route> outboundFor(String status) {
        if (status == OUT_FOR_SIGNATURE) {
            return new List<Route>{ new Route('CLM', 'upsert_agreement') };
        }
        if (status == SIGNED || status == ACTIVE) {
            return new List<Route>{ new Route('Billing', 'upsert_contract') };
        }
        if (status == CANCELLED) {
            return new List<Route>{ new Route('Billing', 'cancel_contract'), new Route('CLM', 'void_agreement') };
        }
        return new List<Route>();
    }
}
