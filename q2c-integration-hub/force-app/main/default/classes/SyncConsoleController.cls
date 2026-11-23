/**
 * Backs the syncConsole LWC on the contract record page.
 *
 * Reads run in user mode (sharing + field-level security). The one write that needs more than the
 * user's object permissions (re-queueing a message) runs in system mode, and only after an explicit
 * check of the Q2C_Sync_Operator custom permission. Sync messages stay read-only everywhere else, so
 * the console is the only way to change them, and it records who did it in the error log.
 */
public with sharing class SyncConsoleController {
    static final Set<String> REQUEUEABLE = new Set<String>{ 'Dead', 'Parked', 'Retrying' };

    public class Summary {
        @AuraEnabled public Decimal version;
        @AuraEnabled public Decimal lastSyncedVersion;
        @AuraEnabled public String status;
        @AuraEnabled public Boolean inSync;
        @AuraEnabled public Boolean canRetry;
        @AuraEnabled public List<Sync_Message__c> messages;
        @AuraEnabled public List<Recon_Break__c> openBreaks;
    }

    @AuraEnabled(cacheable=true)
    public static Summary load(Id contractId) {
        Q2C_Contract__c c = [
            SELECT Id, Status__c, Version__c, Last_Synced_Version__c
            FROM Q2C_Contract__c
            WHERE Id = :contractId
            WITH USER_MODE
        ];
        String recordId = String.valueOf(contractId);
        Summary s = new Summary();
        s.version = c.Version__c;
        s.lastSyncedVersion = c.Last_Synced_Version__c;
        s.status = c.Status__c;
        s.inSync = ReconciliationService.expectedBillingStatus(c.Status__c) == null || c.Last_Synced_Version__c == c.Version__c;
        s.canRetry = FeatureManagement.checkPermission('Q2C_Sync_Operator');
        s.messages = [
            SELECT Id, Name, Direction__c, Target__c, Operation__c, Status__c, Entity_Version__c, Attempts__c,
                Last_Status_Code__c, Last_Error__c, Next_Attempt_At__c, LastModifiedDate
            FROM Sync_Message__c
            WHERE Record_Id__c = :recordId
            WITH USER_MODE
            ORDER BY CreatedDate DESC
            LIMIT 50
        ];
        s.openBreaks = [
            SELECT Id, Name, Kind__c, Line_Key__c, Salesforce_Value__c, Billing_Value__c, Run_Id__c
            FROM Recon_Break__c
            WHERE Contract__c = :contractId AND Resolved__c = false
            WITH USER_MODE
            ORDER BY CreatedDate DESC
            LIMIT 50
        ];
        return s;
    }

    /** Re-queue a dead, parked or waiting message now. Returns the message's new status. */
    @AuraEnabled
    public static String retry(Id messageId) {
        if (!FeatureManagement.checkPermission('Q2C_Sync_Operator')) {
            throw new AuraHandledException('You need the Q2C Sync Operator permission to retry sync messages.');
        }
        List<Sync_Message__c> rows = [
            SELECT Id, Direction__c, Status__c, Payload__c, Last_Error__c, Attempts__c
            FROM Sync_Message__c
            WHERE Id = :messageId
            FOR UPDATE
        ];
        if (rows.isEmpty()) {
            throw new AuraHandledException('Message not found.');
        }
        Sync_Message__c m = rows[0];
        if (!REQUEUEABLE.contains(m.Status__c)) {
            throw new AuraHandledException('A ' + m.Status__c + ' message cannot be retried.');
        }
        String audit = 'Re-queued by ' + UserInfo.getUserName() + ' at ' + System.now().formatGmt('yyyy-MM-dd HH:mm:ss') + 'Z';
        if (m.Direction__c == 'Inbound') {
            InboundApplier.apply(m);
            m.Last_Error__c = audit + (m.Last_Error__c == null ? '' : '\n' + m.Last_Error__c);
            Database.update(m, AccessLevel.SYSTEM_MODE);
            return m.Status__c;
        }
        m.Status__c = 'Pending';
        m.Attempts__c = 0;
        m.Next_Attempt_At__c = System.now();
        m.Last_Error__c = audit + (m.Last_Error__c == null ? '' : '\nPrevious: ' + m.Last_Error__c);
        Database.update(m, AccessLevel.SYSTEM_MODE);
        OutboxDispatcher.kick();
        return m.Status__c;
    }

    /** Mark a reconciliation break resolved. Runs in user mode: the permission set grants the field. */
    @AuraEnabled
    public static void resolveBreak(Id breakId) {
        Recon_Break__c b = new Recon_Break__c(Id = breakId, Resolved__c = true);
        Database.update(b, AccessLevel.USER_MODE);
    }
}
