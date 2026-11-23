/**
 * Runs the shared vectors (static resource PricingVectors = vectors/pricing-vectors.json)
 * against the Apex implementation. The QCP's node tests run the same file.
 */
@IsTest
private class PricingVectorsTest {

    private static Map<String, Object> vectors;

    private static List<Object> section(String name) {
        if (vectors == null) {
            StaticResource resource = [SELECT Body FROM StaticResource WHERE Name = 'PricingVectors' LIMIT 1];
            vectors = (Map<String, Object>) JSON.deserializeUntyped(resource.Body.toString());
        }
        return (List<Object>) vectors.get(name);
    }

    private static Decimal dec(Object value) {
        return value == null ? null : Decimal.valueOf(String.valueOf(value));
    }

    @IsTest
    static void proration() {
        for (Object item : section('proration')) {
            Map<String, Object> v = (Map<String, Object>) item;
            Decimal got = Pricing.prorate(
                Date.valueOf((String) v.get('start')), Date.valueOf((String) v.get('end')),
                (String) v.get('method'), dec(v.get('monthly_price')), dec(v.get('quantity')));
            Assert.areEqual((String) v.get('expected'), String.valueOf(got), (String) v.get('name'));
        }
    }

    @IsTest
    static void renewal() {
        for (Object item : section('renewal')) {
            Map<String, Object> v = (Map<String, Object>) item;
            Decimal got = Pricing.renewalPrice(dec(v.get('list')), dec(v.get('prior')),
                                               dec(v.get('cap_pct')), (Boolean) v.get('grandfathered'));
            Assert.areEqual((String) v.get('expected'), String.valueOf(got), (String) v.get('name'));
        }
    }

    @IsTest
    static void approval() {
        for (Object item : section('approval')) {
            Map<String, Object> v = (Map<String, Object>) item;
            Pricing.ApprovalResult got = Pricing.approvalLevel(
                dec(v.get('max_discount_pct')), (Boolean) v.get('floor_breach'),
                (String) v.get('payment_terms'), (Integer) v.get('term_months'));
            Assert.areEqual((Integer) v.get('expected_level'), got.level, (String) v.get('name'));
        }
    }

    @IsTest
    static void statusTransitions() {
        for (Object item : section('status')) {
            Map<String, Object> v = (Map<String, Object>) item;
            Assert.areEqual((Boolean) v.get('allowed'),
                QuoteStatusMachine.canTransition((String) v.get('from'), (String) v.get('to')),
                String.valueOf(v.get('from')) + ' → ' + String.valueOf(v.get('to')));
        }
    }

    @IsTest
    static void autoApprovalOnlyAtLevelZero() {
        Assert.isTrue(QuoteStatusMachine.canTransition('Draft', 'Approved', 0));
        Assert.isFalse(QuoteStatusMachine.canTransition('Draft', 'Approved', 1));
        Assert.isFalse(QuoteStatusMachine.canTransition('Draft', 'Approved', null));
    }

    @IsTest
    static void illegalTransitionThrows() {
        try {
            QuoteStatusMachine.assertTransition('Draft', 'Accepted', 0);
            Assert.fail('expected TransitionException');
        } catch (QuoteStatusMachine.TransitionException e) {
            Assert.isTrue(e.getMessage().contains('Draft to Accepted'));
        }
    }

    @IsTest
    static void effectiveDiscount() {
        Assert.areEqual('16.00', String.valueOf(Pricing.effectiveDiscountPct(50, 42)));
        Assert.isTrue(Pricing.effectiveDiscountPct(50, 55) == 0, 'price above list is not a discount');
        Assert.isTrue(Pricing.effectiveDiscountPct(null, 10) == 0, 'no list price');
    }

    @IsTest
    static void amendmentPolicy() {
        Id seats = '01t000000000001';
        Id other = '01t000000000002';
        Map<Id, Decimal> current = new Map<Id, Decimal>{ seats => 20 };
        Date startDate = Date.newInstance(2027, 3, 1);
        Date endDate = Date.newInstance(2028, 3, 1);

        Assert.isTrue(AmendmentPolicy.violations(current, new Map<Id, Decimal>{ seats => 30 },
            Date.newInstance(2027, 6, 1), startDate, endDate, false).isEmpty(), 'increase mid-term');
        Assert.areEqual(1, AmendmentPolicy.violations(current, new Map<Id, Decimal>{ seats => 10 },
            Date.newInstance(2027, 6, 1), startDate, endDate, false).size(), 'decrease blocked');
        Assert.isTrue(AmendmentPolicy.violations(current, new Map<Id, Decimal>{ seats => 10 },
            Date.newInstance(2027, 6, 1), startDate, endDate, true).isEmpty(), 'decrease permitted');
        Assert.areEqual(1, AmendmentPolicy.violations(current, new Map<Id, Decimal>{ other => 5 },
            Date.newInstance(2027, 6, 1), startDate, endDate, false).size(), 'product not on contract');
        Assert.areEqual(1, AmendmentPolicy.violations(current, new Map<Id, Decimal>{ seats => 30 },
            endDate, startDate, endDate, false).size(), 'effective date outside term');
    }

    @IsTest
    static void coTermEstimatorFlowAction() {
        CoTermEstimator.Request r = new CoTermEstimator.Request();
        r.startDate = Date.newInstance(2027, 4, 15);
        r.endDate = Date.newInstance(2027, 7, 1);
        r.monthlyPrice = 30;
        r.quantity = 10;
        List<CoTermEstimator.Result> results = CoTermEstimator.estimate(new List<CoTermEstimator.Request>{ r });
        Assert.areEqual('760.00', String.valueOf(results[0].amount));
        Assert.areEqual('2.5333', String.valueOf(results[0].months));
    }

    @IsTest
    static void contractTerms() {
        for (Object item : section('terms')) {
            Map<String, Object> v = (Map<String, Object>) item;
            ContractTerms.Review got = ContractTerms.review((String) v.get('liability_cap'),
                (Boolean) v.get('auto_renew'), (Boolean) v.get('termination_for_convenience'));
            Assert.areEqual((Integer) v.get('expected_level'), got.level, (String) v.get('name'));
            Assert.areEqual((Boolean) v.get('expected_legal'), got.legal, (String) v.get('name'));
        }
    }

    @IsTest
    static void contractTransitions() {
        for (Object item : section('contract_status')) {
            Map<String, Object> v = (Map<String, Object>) item;
            Assert.areEqual((Boolean) v.get('allowed'),
                ContractLifecycle.canTransition((String) v.get('from'), (String) v.get('to')),
                String.valueOf(v.get('from')) + ' → ' + String.valueOf(v.get('to')));
        }
    }

    @IsTest
    static void renewalNotices() {
        for (Object item : section('renewal_notice')) {
            Map<String, Object> v = (Map<String, Object>) item;
            RenewalNotice.Decision got = RenewalNotice.evaluate(
                Date.valueOf((String) v.get('end_date')), (Integer) v.get('notice_days'),
                (Boolean) v.get('auto_renew'), (Boolean) v.get('renewal_quoted'),
                Date.valueOf((String) v.get('as_of')));
            Assert.areEqual((String) v.get('expected_action'), got.action, (String) v.get('name'));
            Assert.areEqual((Boolean) v.get('expected_expiring'), got.expiring, (String) v.get('name'));
        }
    }
}
