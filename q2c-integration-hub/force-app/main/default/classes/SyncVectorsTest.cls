/**
 * Runs vectors/sync-vectors.json (shipped as the SyncVectors static resource) against the Apex rules.
 * The Python simulator runs the same file, so both implementations stay in step.
 */
@IsTest
private class SyncVectorsTest {
    static Map<String, Object> vectors() {
        StaticResource sr = [SELECT Body FROM StaticResource WHERE Name = 'SyncVectors' LIMIT 1];
        return (Map<String, Object>) JSON.deserializeUntyped(sr.Body.toString());
    }

    @IsTest
    static void retryDecisions() {
        for (Object o : (List<Object>) vectors().get('retry')) {
            Map<String, Object> v = (Map<String, Object>) o;
            RetryPolicy.Decision d = RetryPolicy.classify(
                (Integer) v.get('status'), (Boolean) v.get('timedOut'), (Integer) v.get('attempts'), (Integer) v.get('max'));
            Assert.areEqual((String) v.get('expect'), d.name(), (String) v.get('name'));
        }
    }

    @IsTest
    static void backoffSchedule() {
        for (Object o : (List<Object>) vectors().get('backoff')) {
            Map<String, Object> v = (Map<String, Object>) o;
            Integer attempts = (Integer) v.get('attempts');
            Integer base = (Integer) v.get('baseSeconds');
            Assert.areEqual(base, RetryPolicy.baseBackoffSeconds(attempts), 'attempts=' + attempts);
            Integer jittered = RetryPolicy.jitteredBackoffSeconds(attempts);
            Assert.isTrue(jittered >= base / 2 && jittered <= base, 'jitter stays within [base/2, base]');
        }
    }

    @IsTest
    static void transitions() {
        for (Object o : (List<Object>) vectors().get('transitions')) {
            Map<String, Object> v = (Map<String, Object>) o;
            Assert.areEqual((Boolean) v.get('ok'),
                ContractStateMachine.canTransition((String) v.get('from'), (String) v.get('to')),
                v.get('from') + ' -> ' + v.get('to'));
        }
    }

    @IsTest
    static void outboundRoutes() {
        for (Object o : (List<Object>) vectors().get('outbound')) {
            Map<String, Object> v = (Map<String, Object>) o;
            List<Object> expected = (List<Object>) v.get('targets');
            List<ContractStateMachine.Route> routes = ContractStateMachine.outboundFor((String) v.get('status'));
            Assert.areEqual(expected.size(), routes.size(), (String) v.get('status'));
            for (Integer i = 0; i < routes.size(); i++) {
                List<Object> pair = (List<Object>) expected[i];
                Assert.areEqual((String) pair[0], routes[i].target);
                Assert.areEqual((String) pair[1], routes[i].operation);
            }
        }
    }

    @IsTest
    static void keysAndInbound() {
        for (Object o : (List<Object>) vectors().get('keys')) {
            Map<String, Object> v = (Map<String, Object>) o;
            Assert.areEqual((String) v.get('expect'), IdempotencyKeys.outbound(
                (String) v.get('target'), (String) v.get('operation'), (String) v.get('recordId'), (Integer) v.get('version')));
        }
        for (Object o : (List<Object>) vectors().get('inbound')) {
            Map<String, Object> v = (Map<String, Object>) o;
            Assert.areEqual((String) v.get('to'), ContractStateMachine.statusForClmEvent((String) v.get('type')));
        }
        Assert.isNull(ContractStateMachine.statusForClmEvent('agreement.commented'));
    }
}
