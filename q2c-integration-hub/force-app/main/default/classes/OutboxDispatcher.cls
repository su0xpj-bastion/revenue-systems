/**
 * Drains the outbound outbox. Queueable (with callouts) for the fast path, Schedulable as a sweeper
 * that catches anything a lost kick() left behind.
 *
 * Per run:
 *  1. Lock due messages (Pending or Retrying with Next_Attempt_At <= now).
 *  2. Supersede: for each (target, record), only the highest due version is sent, whatever the
 *     operation (a v5 cancel replaces a v4 upsert). Payloads are full snapshots, so older versions
 *     carry nothing the newest doesn't.
 *  3. Callouts first, DML after. Salesforce forbids a callout after uncommitted DML, so results are
 *     held in memory and written in one update at the end.
 *  4. Stop early before hitting the 100-callout or ~120s cumulative-callout limits; the rest stay
 *     Pending for the next link in the chain.
 *  5. Chain again: right away if more is due, otherwise delayed until the next retry is due (up to 10 min).
 */
public inherited sharing class OutboxDispatcher implements Queueable, Database.AllowsCallouts, Schedulable {
    @TestVisible
    static final Integer CALLOUT_BUDGET_MS = 100000;

    public void execute(SchedulableContext ctx) {
        kick();
    }

    /** Enqueue a dispatcher unless one is already queued. Safe to call from triggers and jobs. */
    public static void kick() {
        if (!SyncConfig.outboundEnabled() || Limits.getQueueableJobs() >= Limits.getLimitQueueableJobs()) {
            return;
        }
        AsyncOptions options = new AsyncOptions();
        options.DuplicateSignature = QueueableDuplicateSignature.Builder().addString('OutboxDispatcher').build();
        try {
            System.enqueueJob(new OutboxDispatcher(), options);
        } catch (DuplicateMessageException alreadyQueued) {
            // One dispatcher is enough; it will pick these messages up.
            return;
        }
    }

    public void execute(QueueableContext ctx) {
        DispatchSummary summary = dispatchDue();
        chain(summary);
    }

    public class DispatchSummary {
        public Integer sent = 0;
        public Integer acked = 0;
        public Integer retrying = 0;
        public Integer dead = 0;
        public Integer superseded = 0;
        public Boolean moreDue = false;
    }

    public static DispatchSummary dispatchDue() {
        DispatchSummary summary = new DispatchSummary();
        if (!SyncConfig.outboundEnabled()) {
            return summary;
        }
        Integer batch = SyncConfig.batchSize();
        Integer maxAttempts = SyncConfig.maxAttempts();
        Datetime now = System.now();
        Integer fetch = batch + 1;

        // FOR UPDATE can't be combined with ORDER BY; ordering happens in memory below.
        List<Sync_Message__c> due = [
            SELECT Id, Idempotency_Key__c, Target__c, Operation__c, Record_Id__c, Entity_Version__c,
                Payload__c, Attempts__c, Correlation_Id__c, Status__c
            FROM Sync_Message__c
            WHERE Direction__c = 'Outbound' AND Status__c IN ('Pending', 'Retrying') AND Next_Attempt_At__c <= :now
            LIMIT :fetch
            FOR UPDATE
        ];
        summary.moreDue = due.size() > batch;

        Map<String, Sync_Message__c> newest = new Map<String, Sync_Message__c>();
        List<Sync_Message__c> updates = new List<Sync_Message__c>();
        for (Sync_Message__c m : due) {
            String stream = m.Target__c + ':' + m.Record_Id__c;
            Sync_Message__c current = newest.get(stream);
            if (current == null || m.Entity_Version__c > current.Entity_Version__c) {
                if (current != null) {
                    supersede(current, m, updates, summary);
                }
                newest.put(stream, m);
            } else {
                supersede(m, current, updates, summary);
            }
        }

        Map<Id, Decimal> billingAcked = new Map<Id, Decimal>();
        Long started = System.currentTimeMillis();
        for (Sync_Message__c m : newest.values()) {
            Boolean outOfCallouts = Limits.getCallouts() >= Limits.getLimitCallouts() - 1;
            Boolean outOfTime = System.currentTimeMillis() - started > CALLOUT_BUDGET_MS - HttpSyncTransport.TIMEOUT_MS;
            if (outOfCallouts || outOfTime || summary.sent >= batch) {
                summary.moreDue = true;
                break;
            }
            HttpSyncTransport.Result r = HttpSyncTransport.send(m);
            summary.sent++;
            Integer attempts = (m.Attempts__c == null ? 0 : m.Attempts__c.intValue()) + 1;
            RetryPolicy.Decision d = RetryPolicy.classify(r.status, r.timedOut, attempts, maxAttempts);
            m.Attempts__c = attempts;
            m.Last_Status_Code__c = r.status;
            m.Last_Error__c = r.error;
            switch on d {
                when ACK {
                    m.Status__c = 'Acked';
                    m.Next_Attempt_At__c = null;
                    summary.acked++;
                    if (m.Target__c == 'Billing') {
                        Id contractId = Id.valueOf(m.Record_Id__c);
                        Decimal prev = billingAcked.get(contractId);
                        billingAcked.put(contractId, prev == null ? m.Entity_Version__c : Math.max(prev, m.Entity_Version__c));
                    }
                }
                when SUPERSEDED {
                    m.Status__c = 'Superseded';
                    m.Next_Attempt_At__c = null;
                    summary.superseded++;
                }
                when RETRY {
                    m.Status__c = 'Retrying';
                    m.Next_Attempt_At__c = System.now().addSeconds(RetryPolicy.jitteredBackoffSeconds(attempts));
                    summary.retrying++;
                }
                when else {
                    m.Status__c = 'Dead';
                    m.Next_Attempt_At__c = null;
                    summary.dead++;
                }
            }
            updates.add(m);
        }

        // ---- DML only after every callout ----
        update updates;
        if (!billingAcked.isEmpty()) {
            markSynced(billingAcked);
        }
        return summary;
    }

    static void supersede(Sync_Message__c older, Sync_Message__c newer, List<Sync_Message__c> updates, DispatchSummary summary) {
        older.Status__c = 'Superseded';
        older.Next_Attempt_At__c = null;
        older.Last_Error__c = 'Superseded by v' + newer.Entity_Version__c.intValue() + ' before sending.';
        updates.add(older);
        summary.superseded++;
    }

    /** Last_Synced_Version__c only moves forward; an ack for an old version never lowers it. */
    static void markSynced(Map<Id, Decimal> ackedVersions) {
        List<Q2C_Contract__c> contracts = [
            SELECT Id, Last_Synced_Version__c FROM Q2C_Contract__c WHERE Id IN :ackedVersions.keySet() FOR UPDATE
        ];
        List<Q2C_Contract__c> changed = new List<Q2C_Contract__c>();
        for (Q2C_Contract__c c : contracts) {
            Decimal acked = ackedVersions.get(c.Id);
            if (c.Last_Synced_Version__c == null || acked > c.Last_Synced_Version__c) {
                changed.add(new Q2C_Contract__c(Id = c.Id, Last_Synced_Version__c = acked));
            }
        }
        // Last_Synced_Version__c isn't a billing field, so this update doesn't bump the version or publish.
        update changed;
    }

    static void chain(DispatchSummary summary) {
        if (Test.isRunningTest() || !SyncConfig.outboundEnabled()) {
            return; // Tests can't chain queueables; the scheduled sweeper covers production gaps.
        }
        if (summary.moreDue) {
            System.enqueueJob(new OutboxDispatcher());
            return;
        }
        List<Sync_Message__c> next = [
            SELECT Next_Attempt_At__c FROM Sync_Message__c
            WHERE Direction__c = 'Outbound' AND Status__c = 'Retrying'
            ORDER BY Next_Attempt_At__c ASC
            LIMIT 1
        ];
        if (!next.isEmpty()) {
            Long waitMs = next[0].Next_Attempt_At__c.getTime() - System.now().getTime();
            Integer delayMinutes = Math.max(0, Math.min(10, Math.ceil(waitMs / 60000.0).intValue()));
            System.enqueueJob(new OutboxDispatcher(), delayMinutes);
        }
    }
}
