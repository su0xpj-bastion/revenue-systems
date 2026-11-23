/**
 * Q2C_Contract__c trigger logic.
 *
 * before insert  Status defaults to Draft, Version starts at 1.
 * before update  Enforces ContractStateMachine; bumps Version__c when a billing-relevant field changes;
 *                refuses to move Version__c backwards.
 * after insert / after update
 *                Publishes one Q2C_Change__e per new version. The event is PublishAfterCommit, so it
 *                exists only if this transaction commits: no event for a rolled-back save, and no
 *                committed save without its event (a failed publish fails the save). That is the
 *                transactional-outbox guarantee, without a callout in the trigger.
 */
public inherited sharing class Q2CContractTriggerHandler {
    static final List<SObjectField> BILLING_FIELDS = new List<SObjectField>{
        Q2C_Contract__c.Status__c,
        Q2C_Contract__c.Start_Date__c,
        Q2C_Contract__c.End_Date__c,
        Q2C_Contract__c.Billing_Account_Id__c,
        Q2C_Contract__c.Account__c
    };

    public static void beforeInsert(List<Q2C_Contract__c> rows) {
        for (Q2C_Contract__c c : rows) {
            if (c.Status__c == null) {
                c.Status__c = ContractStateMachine.DRAFT;
            }
            if (c.Version__c == null || c.Version__c < 1) {
                c.Version__c = 1;
            }
            if (c.CLM_Version__c == null) {
                c.CLM_Version__c = 0;
            }
        }
    }

    public static void beforeUpdate(List<Q2C_Contract__c> rows, Map<Id, Q2C_Contract__c> oldMap) {
        for (Q2C_Contract__c c : rows) {
            Q2C_Contract__c old = oldMap.get(c.Id);
            if (!ContractStateMachine.canTransition(old.Status__c, c.Status__c)) {
                c.Status__c.addError('A contract cannot move from ' + old.Status__c + ' to ' + c.Status__c + '.');
                continue;
            }
            if (c.Version__c < old.Version__c) {
                c.Version__c.addError('Version can only move forward.');
                continue;
            }
            Boolean callerBumped = c.Version__c > old.Version__c;
            if (!callerBumped && billingFieldsChanged(c, old)) {
                c.Version__c = old.Version__c + 1;
            }
        }
    }

    public static void afterInsert(List<Q2C_Contract__c> rows) {
        publish(rows, 'created');
    }

    public static void afterUpdate(List<Q2C_Contract__c> rows, Map<Id, Q2C_Contract__c> oldMap) {
        List<Q2C_Contract__c> changed = new List<Q2C_Contract__c>();
        for (Q2C_Contract__c c : rows) {
            if (c.Version__c != oldMap.get(c.Id).Version__c) {
                changed.add(c);
            }
        }
        publish(changed, 'updated');
    }

    static Boolean billingFieldsChanged(Q2C_Contract__c c, Q2C_Contract__c old) {
        for (SObjectField f : BILLING_FIELDS) {
            if (c.get(f) != old.get(f)) {
                return true;
            }
        }
        return false;
    }

    static void publish(List<Q2C_Contract__c> rows, String change) {
        if (rows.isEmpty()) {
            return;
        }
        List<Q2C_Change__e> events = new List<Q2C_Change__e>();
        for (Q2C_Contract__c c : rows) {
            events.add(new Q2C_Change__e(
                Record_Id__c = c.Id,
                Entity__c = 'Q2C_Contract__c',
                Version__c = c.Version__c,
                Change__c = change
            ));
        }
        List<Database.SaveResult> results = EventBus.publish(events);
        for (Integer i = 0; i < results.size(); i++) {
            if (!results[i].isSuccess()) {
                // Losing the event would leave Billing silently stale. Fail the save instead.
                rows[i].addError('Could not queue the downstream sync: ' + results[i].getErrors()[0].getMessage());
            }
        }
    }
}
