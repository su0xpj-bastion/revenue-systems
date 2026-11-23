/**
 * Mid-term amendments through the CPQ Contract Amender, with policy enforced first.
 *
 * Flow: check policy against current subscriptions → ContractAmender builds the amendment quote
 * (one line per subscription, current quantities) → set new quantities and start date → save →
 * CPQ calculates (price rules + QCP) → callback saves. CPQ computes the co-termed delta itself.
 * This class never prices anything.
 */
public with sharing class ContractAmendmentService {

    public class Request {
        @InvocableVariable(required=true label='Contract Id') public Id contractId;
        @InvocableVariable(required=true label='Product Id') public Id productId;
        @InvocableVariable(required=true label='New total quantity') public Decimal newQuantity;
        @InvocableVariable(required=true label='Effective date') public Date effectiveDate;
        @InvocableVariable(label='Allow mid-term decrease') public Boolean allowDecrease;
    }

    public class Result {
        @InvocableVariable(label='Amendment quote Id') public Id quoteId;
    }

    @InvocableMethod(label='Amend contract quantity' category='CPQ')
    public static List<Result> amendFromFlow(List<Request> requests) {
        List<Result> results = new List<Result>();
        for (Request r : requests) {
            Result result = new Result();
            result.quoteId = amend(r.contractId, new Map<Id, Decimal>{ r.productId => r.newQuantity },
                                   r.effectiveDate, r.allowDecrease == true);
            results.add(result);
        }
        return results;
    }

    public static Id amend(Id contractId, Map<Id, Decimal> newQuantityByProduct, Date effectiveDate,
                           Boolean allowDecrease) {
        Contract contract = [SELECT Id, StartDate, EndDate FROM Contract WHERE Id = :contractId WITH USER_MODE];
        Map<Id, Decimal> current = new Map<Id, Decimal>();
        for (AggregateResult row : [
            SELECT SBQQ__Product__c product, SUM(SBQQ__Quantity__c) qty
            FROM SBQQ__Subscription__c
            WHERE SBQQ__Contract__c = :contractId
            WITH USER_MODE
            GROUP BY SBQQ__Product__c
        ]) {
            current.put((Id) row.get('product'), (Decimal) row.get('qty'));
        }
        AmendmentPolicy.enforce(current, newQuantityByProduct, effectiveDate,
                                contract.StartDate, contract.EndDate.addDays(1), allowDecrease);

        CpqModels.QuoteModel quote = CpqQuoteApi.amend(contractId);
        quote.record.SBQQ__StartDate__c = effectiveDate;
        for (CpqModels.QuoteLineModel line : quote.lineItems) {
            Id productId = line.record.SBQQ__Product__c;
            if (newQuantityByProduct.containsKey(productId)) {
                line.record.SBQQ__Quantity__c = newQuantityByProduct.get(productId);
            }
        }
        CpqModels.QuoteModel saved = CpqQuoteApi.save(quote);
        CpqQuoteApi.calculateAndSave(saved);
        return saved.record.Id;
    }
}
