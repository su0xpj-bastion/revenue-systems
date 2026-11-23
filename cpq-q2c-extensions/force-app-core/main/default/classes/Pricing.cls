/**
 * Pricing rules shared by the Quote Calculator Plugin (JavaScript) and server-side automation.
 * No CPQ package dependency: deploys to any org, so the logic is unit-tested on its own.
 * Both implementations run the same vectors (static resource PricingVectors).
 */
public with sharing class Pricing {

    public static final Set<String> STANDARD_PAYMENT_TERMS = new Set<String>{ 'Net 30' };
    private static final Integer PRECISION = 10;

    public class ApprovalResult {
        @AuraEnabled public Integer level = 0;
        @AuraEnabled public List<String> reasons = new List<String>();

        public void raise(Integer to, String reason) {
            if (to > 0) {
                reasons.add(reason);
            }
            level = Math.max(level, to);
        }
    }

    public static Decimal money(Decimal value) {
        return value.setScale(2, RoundingMode.HALF_UP);
    }

    public static Decimal effectiveDiscountPct(Decimal listPrice, Decimal netPrice) {
        if (listPrice == null || listPrice == 0 || netPrice == null) {
            return 0;
        }
        Decimal pct = money((1 - netPrice.divide(listPrice, PRECISION, RoundingMode.HALF_UP)) * 100);
        return pct < 0 ? 0 : pct;
    }

    /** Renew at min(list, prior × (1 + cap)); grandfathered lines keep the prior price. */
    public static Decimal renewalPrice(Decimal listPrice, Decimal priorPrice, Decimal capPct, Boolean grandfathered) {
        if (grandfathered == true && priorPrice != null) {
            return money(priorPrice);
        }
        if (priorPrice == null) {
            return money(listPrice);
        }
        Decimal capped = priorPrice * (1 + (capPct == null ? 0 : capPct) / 100);
        return money(Math.min(listPrice, capped));
    }

    /** Quote approval level: 0 rep, 1 Deal Desk, 2 Finance, 3 CFO. Strongest signal wins. */
    public static ApprovalResult approvalLevel(Decimal maxDiscountPct, Boolean floorBreach,
                                               String paymentTerms, Integer termMonths) {
        ApprovalResult result = new ApprovalResult();
        Decimal d = maxDiscountPct == null ? 0 : maxDiscountPct;
        if (d > 35) {
            result.raise(3, 'discount ' + d + '% > 35%');
        } else if (d > 20) {
            result.raise(2, 'discount ' + d + '% > 20%');
        } else if (d > 10) {
            result.raise(1, 'discount ' + d + '% > 10%');
        }
        if (floorBreach == true) {
            result.raise(2, 'net price below floor');
        }
        if (String.isNotBlank(paymentTerms) && !STANDARD_PAYMENT_TERMS.contains(paymentTerms)) {
            result.raise(1, 'payment terms ' + paymentTerms);
        }
        if (termMonths != null && termMonths > 36) {
            result.raise(2, 'term ' + termMonths + ' months > 36');
        }
        return result;
    }

    /**
     * Months of service between start and end (end exclusive).
     *   monthly_daily: whole months, then leftover days / days in the month they fall in
     *   daily:         days × 12 / 365
     *   monthly:       whole months, any partial month rounds up
     * Set CPQ's Subscription Prorate Precision to match the method you use.
     */
    public static Decimal prorationMonths(Date startDate, Date endDate, String method) {
        if (startDate >= endDate) {
            return 0;
        }
        if (method == 'daily') {
            return Decimal.valueOf(startDate.daysBetween(endDate) * 12).divide(365, PRECISION, RoundingMode.HALF_UP);
        }
        Integer months = 0;
        while (startDate.addMonths(months + 1) <= endDate) {
            months++;
        }
        Date cursor = startDate.addMonths(months);
        Integer leftover = cursor.daysBetween(endDate);
        if (method == 'monthly') {
            return leftover > 0 ? months + 1 : months;
        }
        Integer daysInMonth = Date.daysInMonth(cursor.year(), cursor.month());
        return months + Decimal.valueOf(leftover).divide(daysInMonth, PRECISION, RoundingMode.HALF_UP);
    }

    public static Decimal prorate(Date startDate, Date endDate, String method, Decimal monthlyPrice, Decimal quantity) {
        return money(monthlyPrice * quantity * prorationMonths(startDate, endDate, method));
    }
}
