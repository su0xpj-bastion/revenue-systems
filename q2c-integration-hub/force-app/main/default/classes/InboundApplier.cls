/**
 * Applies one stored inbound CLM event to its contract. Used by the webhook on first delivery and by
 * the Sync Console when an operator replays a Parked or Dead message.
 *
 * Outcomes (Sync_Message__c.Status__c):
 *  Applied        Contract moved to the status the event implies (or was already there).
 *  Ignored_Stale  Event's agreementVersion <= the contract's CLM_Version__c: an older event arrived
 *                 late. Applying it would roll the contract back.
 *  Parked         Contract not found yet (CLM can be faster than our commit). Replayable.
 *  Dead           Illegal transition or a save error. A person has to decide.
 */
public inherited sharing class InboundApplier {
    public static void apply(Sync_Message__c msg) {
        Map<String, Object> evt = (Map<String, Object>) JSON.deserializeUntyped(msg.Payload__c);
        String type = (String) evt.get('type');
        String newStatus = ContractStateMachine.statusForClmEvent(type);
        Integer agreementVersion = toInt(evt.get('agreementVersion'));
        String agreementId = (String) evt.get('agreementId');

        Id contractId;
        try {
            contractId = Id.valueOf((String) evt.get('externalReference'));
        } catch (Exception e) {
            finish(msg, 'Dead', 'externalReference is not a Salesforce Id');
            return;
        }
        if (contractId.getSobjectType() != Q2C_Contract__c.SObjectType) {
            finish(msg, 'Dead', 'externalReference is not a Q2C contract');
            return;
        }

        List<Q2C_Contract__c> found = [
            SELECT Id, Status__c, CLM_Version__c, CLM_Agreement_Id__c FROM Q2C_Contract__c WHERE Id = :contractId FOR UPDATE
        ];
        if (found.isEmpty()) {
            finish(msg, 'Parked', 'Contract not found; replay once it exists.');
            return;
        }
        Q2C_Contract__c c = found[0];
        if (agreementVersion <= (c.CLM_Version__c == null ? 0 : c.CLM_Version__c.intValue())) {
            finish(msg, 'Ignored_Stale', 'agreementVersion ' + agreementVersion + ' <= stored ' + c.CLM_Version__c);
            return;
        }
        if (!ContractStateMachine.canTransition(c.Status__c, newStatus)) {
            finish(msg, 'Dead', 'Illegal transition ' + c.Status__c + ' -> ' + newStatus + ' from ' + type);
            return;
        }

        Q2C_Contract__c upd = new Q2C_Contract__c(
            Id = c.Id,
            Status__c = newStatus,
            CLM_Version__c = agreementVersion,
            CLM_Agreement_Id__c = String.isBlank(agreementId) ? c.CLM_Agreement_Id__c : agreementId
        );
        if (newStatus == ContractStateMachine.SIGNED) {
            upd.Signed_At__c = System.now();
        }
        Savepoint sp = Database.setSavepoint();
        try {
            update upd; // contract trigger bumps the version and publishes the Billing sync
            finish(msg, 'Applied', null);
        } catch (DmlException e) {
            Database.rollback(sp);
            finish(msg, 'Dead', e.getDmlMessage(0));
        }
    }

    static void finish(Sync_Message__c msg, String status, String error) {
        msg.Status__c = status;
        msg.Last_Error__c = error;
        msg.Next_Attempt_At__c = null;
        if (msg.Id != null) {
            update msg;
        }
    }

    static Integer toInt(Object o) {
        if (o == null) {
            return 0;
        }
        if (o instanceof Integer) {
            return (Integer) o;
        }
        return Integer.valueOf(String.valueOf(o));
    }
}
