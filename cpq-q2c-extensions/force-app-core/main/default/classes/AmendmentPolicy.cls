/**
 * Mid-term amendment policy, checked before the CPQ Contract Amender is called.
 * Kept separate from the CPQ call so the policy is testable without the package.
 *
 *  - Quantity decreases mid-term are not allowed (they wait for renewal) unless explicitly permitted.
 *  - The effective date must fall inside the contract term.
 *  - Every requested product must already be on the contract (new products go through an add-on quote).
 */
public with sharing class AmendmentPolicy {

    public class PolicyException extends Exception {}

    public static List<String> violations(Map<Id, Decimal> currentQuantity, Map<Id, Decimal> requestedQuantity,
                                          Date effectiveDate, Date contractStart, Date contractEnd,
                                          Boolean allowDecrease) {
        List<String> problems = new List<String>();
        if (effectiveDate == null || effectiveDate < contractStart || effectiveDate >= contractEnd) {
            problems.add('Effective date ' + effectiveDate + ' is outside the contract term '
                         + contractStart + ' to ' + contractEnd + '.');
        }
        for (Id productId : requestedQuantity.keySet()) {
            Decimal requested = requestedQuantity.get(productId);
            if (!currentQuantity.containsKey(productId)) {
                problems.add('Product ' + productId + ' is not on the contract; use an add-on quote.');
            } else if (requested < currentQuantity.get(productId) && allowDecrease != true) {
                problems.add('Product ' + productId + ': decrease from ' + currentQuantity.get(productId)
                             + ' to ' + requested + ' must wait for renewal.');
            } else if (requested < 0) {
                problems.add('Product ' + productId + ': quantity cannot be negative.');
            }
        }
        return problems;
    }

    public static void enforce(Map<Id, Decimal> currentQuantity, Map<Id, Decimal> requestedQuantity,
                               Date effectiveDate, Date contractStart, Date contractEnd, Boolean allowDecrease) {
        List<String> problems = violations(currentQuantity, requestedQuantity, effectiveDate,
                                           contractStart, contractEnd, allowDecrease);
        if (!problems.isEmpty()) {
            throw new PolicyException(String.join(problems, ' '));
        }
    }
}
