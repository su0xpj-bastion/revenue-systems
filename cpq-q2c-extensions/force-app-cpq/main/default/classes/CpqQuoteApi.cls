/**
 * Thin wrapper over the CPQ Quote API (SBQQ.ServiceRouter). Every quote change made by code goes
 * through here, so it is priced by the same calculator, price rules and QCP as the quote line
 * editor. Code never writes quote line prices directly.
 */
public with sharing class CpqQuoteApi {

    public static CpqModels.QuoteModel read(Id quoteId) {
        String quoteJson = SBQQ.ServiceRouter.read('SBQQ.QuoteAPI.QuoteReader', quoteId);
        return (CpqModels.QuoteModel) JSON.deserialize(quoteJson, CpqModels.QuoteModel.class);
    }

    public static CpqModels.QuoteModel save(CpqModels.QuoteModel quote) {
        String saved = SBQQ.ServiceRouter.save('SBQQ.QuoteAPI.QuoteSaver', JSON.serialize(quote));
        return (CpqModels.QuoteModel) JSON.deserialize(saved, CpqModels.QuoteModel.class);
    }

    /** Asynchronous: CPQ calculates, then calls CpqSaveCallback, which saves the priced quote. */
    public static void calculateAndSave(CpqModels.QuoteModel quote) {
        CpqModels.CalculatorContext context = new CpqModels.CalculatorContext();
        context.quote = quote;
        context.callbackClass = 'CpqSaveCallback';
        SBQQ.ServiceRouter.load('SBQQ.QuoteAPI.QuoteCalculator', null, JSON.serialize(context));
    }

    public static CpqModels.QuoteModel amend(Id contractId) {
        String quoteJson = SBQQ.ServiceRouter.load('SBQQ.ContractManipulationAPI.ContractAmender', contractId, null);
        return (CpqModels.QuoteModel) JSON.deserialize(quoteJson, CpqModels.QuoteModel.class);
    }

    public static List<CpqModels.QuoteModel> renew(Id masterContractId, List<Contract> contracts) {
        CpqModels.RenewalContext context = new CpqModels.RenewalContext();
        context.masterContractId = masterContractId;
        context.renewedContracts = contracts;
        String quotesJson = SBQQ.ServiceRouter.load('SBQQ.ContractManipulationAPI.ContractRenewer',
                                                     masterContractId, JSON.serialize(context));
        return (List<CpqModels.QuoteModel>) JSON.deserialize(quotesJson, List<CpqModels.QuoteModel>.class);
    }
}
