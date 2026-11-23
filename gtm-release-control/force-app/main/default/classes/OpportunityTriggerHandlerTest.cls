@IsTest
private class OpportunityTriggerHandlerTest {

    // 200 = one trigger chunk. Every test runs at bulk volume, never with a single record.
    private static final Integer BULK = 200;

    private static String wonStage() {
        return [SELECT ApiName FROM OpportunityStage WHERE IsWon = true AND IsActive = true LIMIT 1].ApiName;
    }

    private static String openStage() {
        return [SELECT ApiName FROM OpportunityStage WHERE IsClosed = false AND IsActive = true LIMIT 1].ApiName;
    }

    private static List<Opportunity> insertOpportunities(String stage) {
        List<Opportunity> opps = new List<Opportunity>();
        for (Integer i = 0; i < BULK; i++) {
            opps.add(new Opportunity(
                Name = 'Release Control Opp ' + i,
                StageName = stage,
                CloseDate = Date.today(),
                Amount = 1000
            ));
        }
        insert opps;
        return opps;
    }

    @IsTest
    static void blocksReopeningWonOpportunitiesInBulk() {
        List<Opportunity> opps = insertOpportunities(wonStage());
        String reopenTo = openStage();
        for (Opportunity opp : opps) {
            opp.StageName = reopenTo;
        }

        Test.startTest();
        List<Database.SaveResult> results = Database.update(opps, false);
        Test.stopTest();

        for (Database.SaveResult result : results) {
            Assert.isFalse(result.isSuccess(), 'Reopening a won opportunity must be blocked');
            Assert.areEqual(OpportunityTriggerHandler.REOPEN_ERROR, result.getErrors()[0].getMessage());
        }
    }

    @IsTest
    static void allowsEditsThatKeepOpportunityWon() {
        List<Opportunity> opps = insertOpportunities(wonStage());
        for (Opportunity opp : opps) {
            opp.Amount = 2000;
        }

        Test.startTest();
        List<Database.SaveResult> results = Database.update(opps, false);
        Test.stopTest();

        for (Database.SaveResult result : results) {
            Assert.isTrue(result.isSuccess(), 'Non-stage edits on won opportunities must succeed');
        }
    }

    @IsTest
    static void allowsOpenOpportunitiesToMoveFreely() {
        List<Opportunity> opps = insertOpportunities(openStage());
        String won = wonStage();
        for (Opportunity opp : opps) {
            opp.StageName = won;
        }

        Test.startTest();
        update opps;
        Test.stopTest();

        Assert.areEqual(BULK, [SELECT COUNT() FROM Opportunity WHERE IsWon = true]);
    }

    @IsTest
    static void approvedProcessBypassCanReopen() {
        List<Opportunity> opps = insertOpportunities(wonStage());
        String reopenTo = openStage();
        for (Opportunity opp : opps) {
            opp.StageName = reopenTo;
        }

        Test.startTest();
        OpportunityTriggerHandler.bypass = true;
        update opps;
        Test.stopTest();

        Assert.areEqual(0, [SELECT COUNT() FROM Opportunity WHERE IsWon = true]);
    }

    @IsTest
    static void staysWithinOneQueryPerTransaction() {
        List<Opportunity> opps = insertOpportunities(wonStage());
        for (Opportunity opp : opps) {
            opp.Amount = 3000;
        }

        Test.startTest();
        update opps;
        Integer queries = Limits.getQueries();
        Test.stopTest();

        Assert.isTrue(queries <= 1, 'Handler must not query per record; used ' + queries);
    }
}
