trigger CpqQuoteTrigger on SBQQ__Quote__c (before update) {
    QuoteTriggerHandler.beforeUpdate(Trigger.new, Trigger.oldMap);
}
