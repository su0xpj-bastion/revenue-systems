// One trigger per object. All logic lives in the handler so it can be unit-tested and bypassed.
trigger OpportunityTrigger on Opportunity (before update) {
    OpportunityTriggerHandler.beforeUpdate(Trigger.new, Trigger.oldMap);
}
