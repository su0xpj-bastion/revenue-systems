/**
 * Contract lifecycle guard (before update on Contract).
 *  - Lifecycle_Status__c changes must follow ContractLifecycle.
 *  - Moving to Signed stamps CustomerSignedDate if empty.
 *  - Terminating requires a Termination_Reason__c (audit trail for early terminations).
 */
public with sharing class ContractLifecycleHandler {

    public static void beforeUpdate(List<Contract> newContracts, Map<Id, Contract> oldContracts) {
        for (Contract c : newContracts) {
            String fromStatus = oldContracts.get(c.Id).Lifecycle_Status__c;
            String toStatus = c.Lifecycle_Status__c;
            if (fromStatus == toStatus) {
                continue;
            }
            if (!ContractLifecycle.canTransition(fromStatus, toStatus)) {
                c.Lifecycle_Status__c.addError('Contract cannot move from ' + fromStatus + ' to ' + toStatus + '.');
                continue;
            }
            if (toStatus == 'Signed' && c.CustomerSignedDate == null) {
                c.CustomerSignedDate = Date.today();
            }
            if (toStatus == 'Terminated' && String.isBlank(c.Termination_Reason__c)) {
                c.Termination_Reason__c.addError('Enter a termination reason before terminating the contract.');
            }
        }
    }
}
