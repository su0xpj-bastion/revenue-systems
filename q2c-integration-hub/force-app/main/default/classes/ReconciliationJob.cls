/**
 * Nightly Salesforce <-> Billing reconciliation (Batch Apex with callouts, scope 50).
 *
 * Scope: only contracts that are settled (Last_Synced_Version__c = Version__c) and that Billing
 * should know about. In-flight contracts are skipped, so a message still in the outbox isn't
 * reported as a break.
 *
 * Per scope: GET each contract from Billing (callouts first), compare, then insert Recon_Break__c
 * rows and, when `repair` is on, queue a fresh full-snapshot sync under a repair key. Breaks are
 * recorded either way: repair fixes the data, the break row is the audit trail that it drifted.
 */
public inherited sharing class ReconciliationJob implements Database.Batchable<SObject>, Database.AllowsCallouts, Database.Stateful, Schedulable {
    public final String runId;
    public final Boolean repair;
    public Integer contractsChecked = 0;
    public Integer breaksFound = 0;
    public Integer fetchErrors = 0;

    public ReconciliationJob(Boolean repair) {
        this.repair = repair;
        this.runId = 'recon-' + System.now().format('yyyyMMddHHmmss', 'UTC');
    }

    public void execute(SchedulableContext ctx) {
        Database.executeBatch(new ReconciliationJob(true), 50);
    }

    public Database.QueryLocator start(Database.BatchableContext ctx) {
        return Database.getQueryLocator([
            SELECT Id, Status__c, Version__c, Last_Synced_Version__c,
                (SELECT Line_Key__c, Product_Code__c, Quantity__c, Unit_Price__c FROM Subscriptions__r)
            FROM Q2C_Contract__c
            WHERE Status__c IN ('Signed', 'Active', 'Cancelled')
        ]);
    }

    public void execute(Database.BatchableContext ctx, List<Q2C_Contract__c> scope) {
        List<Recon_Break__c> breaks = new List<Recon_Break__c>();
        Set<Id> toRepair = new Set<Id>();
        for (Q2C_Contract__c c : scope) {
            if (c.Last_Synced_Version__c != c.Version__c) {
                continue; // still syncing; the outbox owns it
            }
            BillingSnapshot snap = fetch(c.Id);
            if (snap.error != null) {
                fetchErrors++;
                continue;
            }
            contractsChecked++;
            List<ReconciliationService.Line> sfLines = new List<ReconciliationService.Line>();
            for (Q2C_Subscription__c s : c.Subscriptions__r) {
                sfLines.add(new ReconciliationService.Line(s.Line_Key__c, s.Product_Code__c, s.Quantity__c, s.Unit_Price__c));
            }
            for (ReconciliationService.Drift b : ReconciliationService.compare(c.Status__c, sfLines, snap.status, snap.lines)) {
                breaks.add(new Recon_Break__c(
                    Contract__c = c.Id,
                    Run_Id__c = runId,
                    Kind__c = b.kind,
                    Line_Key__c = b.lineKey,
                    Salesforce_Value__c = b.salesforceValue == null ? null : b.salesforceValue.left(255),
                    Billing_Value__c = b.billingValue == null ? null : b.billingValue.left(255)
                ));
                toRepair.add(c.Id);
            }
        }
        // ---- DML only after every callout ----
        breaksFound += breaks.size();
        insert breaks;
        if (repair && !toRepair.isEmpty()) {
            OutboxService.enqueueContracts(toRepair, null, runId);
        }
    }

    public void finish(Database.BatchableContext ctx) {
        System.debug(LoggingLevel.INFO, JSON.serialize(new Map<String, Object>{
            'runId' => runId, 'checked' => contractsChecked, 'breaks' => breaksFound, 'fetchErrors' => fetchErrors
        }));
    }

    public class BillingSnapshot {
        public String status; // null = 404
        public List<ReconciliationService.Line> lines = new List<ReconciliationService.Line>();
        public String error;
    }

    @TestVisible
    static BillingSnapshot fetch(Id contractId) {
        BillingSnapshot snap = new BillingSnapshot();
        HttpRequest req = new HttpRequest();
        req.setMethod('GET');
        req.setTimeout(HttpSyncTransport.TIMEOUT_MS);
        req.setEndpoint('callout:Billing_Core/v1/contracts/' + contractId);
        try {
            HttpResponse res = new Http().send(req);
            if (res.getStatusCode() == 404) {
                return snap;
            }
            if (res.getStatusCode() != 200) {
                snap.error = 'HTTP ' + res.getStatusCode();
                return snap;
            }
            Map<String, Object> body = (Map<String, Object>) JSON.deserializeUntyped(res.getBody());
            snap.status = (String) body.get('status');
            for (Object o : (List<Object>) body.get('lines')) {
                Map<String, Object> l = (Map<String, Object>) o;
                snap.lines.add(new ReconciliationService.Line(
                    (String) l.get('lineKey'),
                    (String) l.get('productCode'),
                    toDecimal(l.get('quantity')),
                    toDecimal(l.get('unitPrice'))
                ));
            }
        } catch (Exception e) {
            snap.error = e.getMessage();
        }
        return snap;
    }

    static Decimal toDecimal(Object o) {
        return o == null ? null : Decimal.valueOf(String.valueOf(o));
    }
}
