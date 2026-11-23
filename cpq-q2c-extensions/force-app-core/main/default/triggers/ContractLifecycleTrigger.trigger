trigger ContractLifecycleTrigger on Contract (before update) {
    ContractLifecycleHandler.beforeUpdate(Trigger.new, Trigger.oldMap);
}
