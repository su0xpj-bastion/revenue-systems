/**
 * Nightly renewal notices for Active and Expiring contracts.
 *
 *   create_renewal_quote → ContractRenewalService (CPQ Contract Renewer + capped uplift via QCP)
 *   notify_owner         → one open Task for the contract owner (not repeated on later runs)
 *   expire               → Lifecycle Expiring → Expired
 * and Active → Expiring once the prep window opens.
 *
 * Batch size 1: each renewal makes CPQ API saves plus an async calculation.
 * Schedule: System.schedule('Renewal notices', '0 0 2 * * ?', new RenewalNoticeJob());
 */
public with sharing class RenewalNoticeJob implements Database.Batchable<SObject>, Schedulable {

    public static final String TASK_SUBJECT = 'Renewal decision needed: contract does not auto-renew';
    private final Date asOf;

    public RenewalNoticeJob() {
        this(Date.today());
    }

    public RenewalNoticeJob(Date asOf) {
        this.asOf = asOf;
    }

    public void execute(SchedulableContext context) {
        Database.executeBatch(new RenewalNoticeJob(), 1);
    }

    public Database.QueryLocator start(Database.BatchableContext context) {
        return Database.getQueryLocator([
            SELECT Id, OwnerId, EndDate, Notice_Days__c, Auto_Renew__c, Renewal_Quote_Created__c, Lifecycle_Status__c
            FROM Contract
            WHERE Lifecycle_Status__c IN ('Active', 'Expiring') AND EndDate != null
        ]);
    }

    public void execute(Database.BatchableContext context, List<Contract> contracts) {
        Set<Id> alreadyNotified = new Set<Id>();
        for (Task t : [SELECT WhatId FROM Task WHERE WhatId IN :contracts AND Subject = :TASK_SUBJECT AND IsClosed = false]) {
            alreadyNotified.add(t.WhatId);
        }
        List<Contract> updates = new List<Contract>();
        List<Task> tasks = new List<Task>();
        for (Contract c : contracts) {
            RenewalNotice.Decision decision = RenewalNotice.evaluate(
                c.EndDate, c.Notice_Days__c == null ? 60 : c.Notice_Days__c.intValue(),
                c.Auto_Renew__c, c.Renewal_Quote_Created__c, asOf);
            Contract change = new Contract(Id = c.Id);
            Boolean changed = false;

            if (c.Lifecycle_Status__c == 'Active' && (decision.expiring || decision.action == 'expire')) {
                change.Lifecycle_Status__c = 'Expiring';   // Expired follows on the next run
                changed = true;
            } else if (decision.action == 'expire' && c.Lifecycle_Status__c == 'Expiring') {
                change.Lifecycle_Status__c = 'Expired';
                changed = true;
            }
            if (decision.action == 'create_renewal_quote') {
                ContractRenewalService.renew(c.Id);
                change.Renewal_Quote_Created__c = true;
                changed = true;
            }
            if (decision.action == 'notify_owner' && !alreadyNotified.contains(c.Id)) {
                tasks.add(new Task(
                    WhatId = c.Id, OwnerId = c.OwnerId, Subject = TASK_SUBJECT, Priority = 'High',
                    ActivityDate = c.EndDate.addDays(-(c.Notice_Days__c == null ? 60 : c.Notice_Days__c.intValue())),
                    Description = 'This contract ends ' + c.EndDate + ' and does not auto-renew. '
                        + 'Decide by the notice date: renew (create a renewal quote) or let it expire.'));
            }
            if (changed) {
                updates.add(change);
            }
        }
        update as user updates;
        insert as user tasks;
    }

    public void finish(Database.BatchableContext context) {}
}
