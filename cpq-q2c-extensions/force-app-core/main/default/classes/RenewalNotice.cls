/**
 * What to do about an upcoming contract end, as of a given day.
 *
 *   notice date = EndDate − Notice_Days__c   (EndDate is inclusive)
 *   prep window opens 30 days before the notice date
 *
 *   before window            → none
 *   in window (≤ EndDate)    → auto-renew: create renewal quote · otherwise: notify owner
 *                              (none if a renewal quote already exists); contract is Expiring
 *   after EndDate            → auto-renew: create renewal quote if still missing · otherwise: expire
 */
public with sharing class RenewalNotice {

    public static final Integer PREP_DAYS = 30;

    public class Decision {
        public String action;
        public Boolean expiring;

        public Decision(String action, Boolean expiring) {
            this.action = action;
            this.expiring = expiring;
        }
    }

    public static Decision evaluate(Date endDate, Integer noticeDays, Boolean autoRenew,
                                    Boolean renewalQuoted, Date asOf) {
        Date prep = endDate.addDays(-((noticeDays == null ? 0 : noticeDays) + PREP_DAYS));
        if (asOf < prep) {
            return new Decision('none', false);
        }
        if (asOf <= endDate) {
            if (renewalQuoted == true) {
                return new Decision('none', true);
            }
            return new Decision(autoRenew == true ? 'create_renewal_quote' : 'notify_owner', true);
        }
        if (autoRenew != true) {
            return new Decision('expire', false);
        }
        return new Decision(renewalQuoted == true ? 'none' : 'create_renewal_quote', false);
    }
}
