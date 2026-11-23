trigger Q2CContractTrigger on Q2C_Contract__c (before insert, before update, after insert, after update) {
    if (Trigger.isBefore && Trigger.isInsert) {
        Q2CContractTriggerHandler.beforeInsert(Trigger.new);
    } else if (Trigger.isBefore && Trigger.isUpdate) {
        Q2CContractTriggerHandler.beforeUpdate(Trigger.new, Trigger.oldMap);
    } else if (Trigger.isAfter && Trigger.isInsert) {
        Q2CContractTriggerHandler.afterInsert(Trigger.new);
    } else if (Trigger.isAfter && Trigger.isUpdate) {
        Q2CContractTriggerHandler.afterUpdate(Trigger.new, Trigger.oldMap);
    }
}
