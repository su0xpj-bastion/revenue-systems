trigger Q2CSubscriptionTrigger on Q2C_Subscription__c (
    before insert, before update, after insert, after update, after delete, after undelete
) {
    if (Trigger.isBefore) {
        Q2CSubscriptionTriggerHandler.stampLineKeys(Trigger.new);
    } else if (Trigger.isDelete) {
        Q2CSubscriptionTriggerHandler.bumpParents(Trigger.old, null);
    } else {
        Q2CSubscriptionTriggerHandler.bumpParents(Trigger.new, Trigger.isUpdate ? Trigger.oldMap : null);
    }
}
