/**
 * Compares what Salesforce says a contract is with what Billing holds. Pure: no queries, no DML,
 * no callouts, so every rule is unit-tested and mirrored in the Python simulator.
 *
 * Joined on lineKey (<contractId>:<productCode>), which both sides store.
 * Quantity and price are compared as decimals at 2 places, so "10" vs "10.00" is not a break.
 */
public inherited sharing class ReconciliationService {
    public class Line {
        public String lineKey;
        public String productCode;
        public Decimal quantity;
        public Decimal unitPrice;
        public Line(String lineKey, String productCode, Decimal quantity, Decimal unitPrice) {
            this.lineKey = lineKey;
            this.productCode = productCode;
            this.quantity = quantity;
            this.unitPrice = unitPrice;
        }
    }

    public class Drift {
        public String kind;
        public String lineKey;
        public String salesforceValue;
        public String billingValue;
        public Drift(String kind, String lineKey, String salesforceValue, String billingValue) {
            this.kind = kind;
            this.lineKey = lineKey;
            this.salesforceValue = salesforceValue;
            this.billingValue = billingValue;
        }
    }

    /** The status Billing should hold for a Salesforce status; null = Billing shouldn't know it. */
    public static String expectedBillingStatus(String salesforceStatus) {
        if (salesforceStatus == ContractStateMachine.SIGNED || salesforceStatus == ContractStateMachine.ACTIVE) {
            return 'active';
        }
        if (salesforceStatus == ContractStateMachine.CANCELLED) {
            return 'cancelled';
        }
        return null;
    }

    /** billingStatus == null means Billing returned 404 for the contract. */
    public static List<Drift> compare(String sfStatus, List<Line> sfLines, String billingStatus, List<Line> billingLines) {
        List<Drift> out = new List<Drift>();
        String expected = expectedBillingStatus(sfStatus);
        if (billingStatus == null) {
            if (expected != null) {
                out.add(new Drift('Missing_In_Billing', null, sfStatus, '404'));
            }
            return out;
        }
        if (expected != billingStatus) {
            out.add(new Drift('Status_Mismatch', null, sfStatus, billingStatus));
        }
        if (billingStatus == 'cancelled' && expected == 'cancelled') {
            return out; // cancelled contracts aren't billed; line drift no longer matters
        }

        Map<String, Line> sfByKey = index(sfLines);
        Map<String, Line> billingByKey = index(billingLines);
        List<String> keys = new List<String>(sfByKey.keySet());
        keys.sort();
        for (String key : keys) {
            Line s = sfByKey.get(key);
            Line b = billingByKey.get(key);
            if (b == null) {
                out.add(new Drift('Missing_In_Billing', key, fmt(s.quantity) + ' @ ' + fmt(s.unitPrice), null));
                continue;
            }
            if (fmt(s.quantity) != fmt(b.quantity)) {
                out.add(new Drift('Quantity_Mismatch', key, fmt(s.quantity), fmt(b.quantity)));
            }
            if (fmt(s.unitPrice) != fmt(b.unitPrice)) {
                out.add(new Drift('Price_Mismatch', key, fmt(s.unitPrice), fmt(b.unitPrice)));
            }
        }
        List<String> billingKeys = new List<String>(billingByKey.keySet());
        billingKeys.sort();
        for (String key : billingKeys) {
            if (!sfByKey.containsKey(key)) {
                Line b = billingByKey.get(key);
                out.add(new Drift('Missing_In_Salesforce', key, null, fmt(b.quantity) + ' @ ' + fmt(b.unitPrice)));
            }
        }
        return out;
    }

    static Map<String, Line> index(List<Line> lines) {
        Map<String, Line> m = new Map<String, Line>();
        if (lines != null) {
            for (Line l : lines) {
                m.put(l.lineKey, l);
            }
        }
        return m;
    }

    @TestVisible
    static String fmt(Decimal d) {
        return d == null ? 'null' : d.setScale(2, RoundingMode.HALF_UP).toPlainString();
    }
}
