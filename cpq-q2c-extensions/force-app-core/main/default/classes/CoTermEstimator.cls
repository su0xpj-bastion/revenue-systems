/**
 * Flow action: estimate a co-termed add-on charge before anyone builds an amendment quote.
 * Lets a rep or Deal Desk answer "what would 10 more seats cost until renewal?" from a screen flow.
 */
public with sharing class CoTermEstimator {

    public class Request {
        @InvocableVariable(required=true label='Add-on start date') public Date startDate;
        @InvocableVariable(required=true label='Contract end date (exclusive)') public Date endDate;
        @InvocableVariable(required=true label='Monthly unit price') public Decimal monthlyPrice;
        @InvocableVariable(required=true label='Quantity') public Decimal quantity;
        @InvocableVariable(label='Proration method (monthly_daily, daily, monthly)') public String method;
    }

    public class Result {
        @InvocableVariable(label='Prorated amount') public Decimal amount;
        @InvocableVariable(label='Months of service') public Decimal months;
    }

    @InvocableMethod(label='Estimate co-term charge' category='CPQ')
    public static List<Result> estimate(List<Request> requests) {
        List<Result> results = new List<Result>();
        for (Request r : requests) {
            String method = String.isBlank(r.method) ? 'monthly_daily' : r.method;
            Result result = new Result();
            result.months = Pricing.prorationMonths(r.startDate, r.endDate, method).setScale(4, RoundingMode.HALF_UP);
            result.amount = Pricing.prorate(r.startDate, r.endDate, method, r.monthlyPrice, r.quantity);
            results.add(result);
        }
        return results;
    }
}
