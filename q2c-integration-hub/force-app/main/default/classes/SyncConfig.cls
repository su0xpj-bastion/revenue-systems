/**
 * Runtime switches from the protected Q2C_Integration_Settings__c (org defaults), with safe defaults
 * when the setting has never been saved. Tests inject values through `testOverride`.
 */
public inherited sharing class SyncConfig {
    /** Callouts per transaction are capped at 100; leave headroom for the contract update. */
    public static final Integer MAX_BATCH = 90;

    @TestVisible
    static Q2C_Integration_Settings__c testOverride;

    static Q2C_Integration_Settings__c settings() {
        if (testOverride != null) {
            return testOverride;
        }
        Q2C_Integration_Settings__c s = Q2C_Integration_Settings__c.getOrgDefaults();
        return (s == null || s.Id == null) ? null : s;
    }

    /** Kill switch. Off = messages keep queueing, nothing is sent. Turning it on drains the queue. */
    public static Boolean outboundEnabled() {
        Q2C_Integration_Settings__c s = settings();
        return s == null || s.Outbound_Enabled__c == true;
    }

    public static Integer maxAttempts() {
        Q2C_Integration_Settings__c s = settings();
        return (s == null || s.Max_Attempts__c == null) ? 8 : s.Max_Attempts__c.intValue();
    }

    public static Integer batchSize() {
        Q2C_Integration_Settings__c s = settings();
        Integer size = (s == null || s.Dispatch_Batch_Size__c == null) ? 50 : s.Dispatch_Batch_Size__c.intValue();
        return Math.max(1, Math.min(size, MAX_BATCH));
    }

    /** Blank means every webhook is rejected: fail closed, never accept unsigned traffic. */
    public static String webhookSecret() {
        Q2C_Integration_Settings__c s = settings();
        return s == null ? null : s.Webhook_Secret__c;
    }
}
