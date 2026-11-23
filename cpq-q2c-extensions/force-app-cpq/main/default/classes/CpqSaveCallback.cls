/**
 * Callback for asynchronous CPQ calculation: saves the priced quote. Must be global because CPQ
 * (a managed package) instantiates it by name.
 */
global with sharing class CpqSaveCallback implements SBQQ.CalculateCallback {
    global void callback(String quoteJson) {
        SBQQ.ServiceRouter.save('SBQQ.QuoteAPI.QuoteSaver', quoteJson);
    }
}
