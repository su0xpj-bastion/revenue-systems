/**
 * Renewals through the CPQ Contract Renewer, with prior pricing carried onto the renewal quote.
 *
 * Division of labour: this class gathers the facts (prior net price per renewed subscription,
 * grandfathering, the account's uplift cap) and writes them onto the renewal quote. The QCP
 * turns those facts into prices during calculation. A rep who recalculates the renewal quote
 * later gets the same answer, because the rule lives in the calculator, not in a one-time script.
 */
public with sharing class ContractRenewalService {

    public class Request {
        @InvocableVariable(required=true label='Contract Id') public Id contractId;
    }

    public class Result {
        @InvocableVariable(label='Renewal quote Id') public Id quoteId;
    }

    @InvocableMethod(label='Create renewal quote with capped uplift' category='CPQ')
    public static List<Result> renewFromFlow(List<Request> requests) {
        List<Result> results = new List<Result>();
        for (Request r : requests) {
            Result result = new Result();
            result.quoteId = renew(r.contractId);
            results.add(result);
        }
        return results;
    }

    public static Id renew(Id contractId) {
        Contract contract = [
            SELECT Id, AccountId, Account.Renewal_Cap_Pct__c
            FROM Contract WHERE Id = :contractId WITH USER_MODE
        ];
        List<CpqModels.QuoteModel> quotes = CpqQuoteApi.renew(contractId, new List<Contract>{ contract });
        if (quotes.isEmpty()) {
            throw new IllegalArgumentException('CPQ returned no renewal quote for contract ' + contractId);
        }
        CpqModels.QuoteModel quote = quotes[0];

        Set<Id> subscriptionIds = new Set<Id>();
        for (CpqModels.QuoteLineModel line : quote.lineItems) {
            if (line.record.SBQQ__RenewedSubscription__c != null) {
                subscriptionIds.add(line.record.SBQQ__RenewedSubscription__c);
            }
        }
        Map<Id, SBQQ__Subscription__c> subscriptions = new Map<Id, SBQQ__Subscription__c>([
            SELECT Id, SBQQ__NetPrice__c, Grandfathered__c
            FROM SBQQ__Subscription__c WHERE Id IN :subscriptionIds WITH USER_MODE
        ]);

        quote.record.Renewal_Cap_Pct__c = contract.Account.Renewal_Cap_Pct__c;
        for (CpqModels.QuoteLineModel line : quote.lineItems) {
            SBQQ__Subscription__c prior = subscriptions.get(line.record.SBQQ__RenewedSubscription__c);
            if (prior != null) {
                line.record.Prior_Net_Price__c = prior.SBQQ__NetPrice__c;
                line.record.Grandfathered__c = prior.Grandfathered__c;
            }
        }
        CpqModels.QuoteModel saved = CpqQuoteApi.save(quote);
        CpqQuoteApi.calculateAndSave(saved);
        return saved.record.Id;
    }
}
