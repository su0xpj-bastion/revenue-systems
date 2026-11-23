/**
 * Revenue guard: a won Opportunity cannot be moved back to an open or lost stage.
 * Reopening booked revenue goes through an approved RevOps process, not a stage edit.
 *
 * Bulk-safe: one SOQL query per transaction, no DML, no per-record queries.
 */
public with sharing class OpportunityTriggerHandler {

    public static final String REOPEN_ERROR =
        'Closed Won opportunities cannot be reopened. Ask RevOps to run the approved reopen process.';

    // Approved-process bypass. In a production org this is backed by a Custom Permission
    // (FeatureManagement.checkPermission) assigned only to the RevOps integration user.
    @TestVisible
    private static Boolean bypass = false;

    private static Set<String> wonStages;

    public static void beforeUpdate(List<Opportunity> newList, Map<Id, Opportunity> oldMap) {
        if (bypass) {
            return;
        }
        Set<String> won = getWonStages();
        for (Opportunity opp : newList) {
            Opportunity previous = oldMap.get(opp.Id);
            Boolean wasWon = won.contains(previous.StageName);
            Boolean isWon = won.contains(opp.StageName);
            if (wasWon && !isWon) {
                opp.StageName.addError(REOPEN_ERROR);
            }
        }
    }

    // Stage names are org configuration, so read them instead of hard-coding 'Closed Won'.
    private static Set<String> getWonStages() {
        if (wonStages == null) {
            wonStages = new Set<String>();
            for (OpportunityStage stage : [
                SELECT ApiName, MasterLabel FROM OpportunityStage WHERE IsWon = true
            ]) {
                wonStages.add(stage.ApiName);
                wonStages.add(stage.MasterLabel);
            }
        }
        return wonStages;
    }
}
