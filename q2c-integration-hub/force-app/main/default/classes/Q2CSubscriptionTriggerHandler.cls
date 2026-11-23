/**
 * Q2C_Subscription__c trigger logic.
 *
 * before insert / update  Line_Key__c = <contractId>:<productCode>. The unique index on it rejects a
 *                         second line for the same product, and reconciliation joins on it.
 * after insert / update / delete / undelete
 *                         A priced-line change is a new contract version: bump the parent once per
 *                         transaction (bulk-safe), which publishes one Q2C_Change__e through the
 *                         contract trigger. Billing always receives the whole contract snapshot.
 */
public inherited sharing class Q2CSubscriptionTriggerHandler {
    public static void stampLineKeys(List<Q2C_Subscription__c> rows) {
        for (Q2C_Subscription__c s : rows) {
            s.Line_Key__c = String.valueOf(s.Contract__c) + ':' + s.Product_Code__c;
        }
    }

    public static void bumpParents(List<Q2C_Subscription__c> rows, Map<Id, Q2C_Subscription__c> oldMap) {
        Set<Id> contractIds = new Set<Id>();
        for (Q2C_Subscription__c s : rows) {
            Q2C_Subscription__c old = oldMap == null ? null : oldMap.get(s.Id);
            if (old == null
                    || s.Quantity__c != old.Quantity__c
                    || s.Unit_Price__c != old.Unit_Price__c
                    || s.Product_Code__c != old.Product_Code__c) {
                contractIds.add(s.Contract__c);
            }
        }
        if (contractIds.isEmpty()) {
            return;
        }
        List<Q2C_Contract__c> parents = [
            SELECT Id, Version__c FROM Q2C_Contract__c WHERE Id IN :contractIds FOR UPDATE
        ];
        for (Q2C_Contract__c c : parents) {
            c.Version__c = c.Version__c + 1;
        }
        update parents;
    }
}
