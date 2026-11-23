/**
 * Contract terms review. Non-standard terms always go to Legal; the approval level reflects the
 * business risk. Mirrors termsReview() in the QCP; both run the "terms" vectors.
 */
public with sharing class ContractTerms {

    public static final String STANDARD_LIABILITY_CAP = '1x fees';

    public class Review {
        @AuraEnabled public Integer level = 0;
        @AuraEnabled public Boolean legal = false;
        @AuraEnabled public List<String> reasons = new List<String>();

        public void flag(Integer to, String reason) {
            reasons.add(reason);
            legal = true;
            level = Math.max(level, to);
        }
    }

    public static Review review(String liabilityCap, Boolean autoRenew, Boolean terminationForConvenience) {
        Review result = new Review();
        if (String.isNotBlank(liabilityCap) && liabilityCap != STANDARD_LIABILITY_CAP) {
            result.flag(liabilityCap == 'Uncapped' ? 3 : 1, 'liability cap ' + liabilityCap);
        }
        if (autoRenew == false) {
            result.flag(1, 'auto-renew off');
        }
        if (terminationForConvenience == true) {
            result.flag(2, 'termination for convenience');
        }
        return result;
    }
}
