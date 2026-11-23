import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { termsReview, onAfterCalculate } from '../src/quote-calculator-plugin.js';
import { contractCanTransition, renewalNotice } from '../../reference/clm.js';

const vectors = JSON.parse(readFileSync(new URL('../../vectors/pricing-vectors.json', import.meta.url)));

for (const v of vectors.terms) {
  test(`terms: ${v.name}`, () => {
    const r = termsReview({ liabilityCap: v.liability_cap, autoRenew: v.auto_renew, terminationForConvenience: v.termination_for_convenience });
    assert.equal(r.level, v.expected_level);
    assert.equal(r.legal, v.expected_legal);
  });
}

for (const v of vectors.contract_status) {
  test(`contract: ${v.from} → ${v.to}`, () => assert.equal(contractCanTransition(v.from, v.to), v.allowed));
}

for (const v of vectors.renewal_notice) {
  test(`notice: ${v.name}`, () => {
    const r = renewalNotice({ endDate: v.end_date, noticeDays: v.notice_days, autoRenew: v.auto_renew, renewalQuoted: v.renewal_quoted, asOf: v.as_of });
    assert.deepEqual(r, { action: v.expected_action, expiring: v.expected_expiring });
  });
}

test('quote: pricing and terms combine into one approval level and a Legal flag', async () => {
  const quote = { record: { SBQQ__PaymentTerms__c: 'Net 30', SBQQ__SubscriptionTerm__c: 12, Liability_Cap__c: 'Uncapped' } };
  await onAfterCalculate(quote, [{ record: { SBQQ__ListPrice__c: 100, SBQQ__NetPrice__c: 85, Max_Discount_Pct__c: 30 } }]);
  assert.equal(quote.record.Approval_Level__c, 3);           // terms (uncapped) beat pricing (15% → 1)
  assert.equal(quote.record.Legal_Review_Required__c, true);
  assert.match(quote.record.Approval_Reasons__c, /discount 15% > 10%; liability cap Uncapped/);
});

test('quote: auto-renew left blank counts as on (standard)', async () => {
  const quote = { record: { SBQQ__PaymentTerms__c: 'Net 30', SBQQ__SubscriptionTerm__c: 12 } };
  await onAfterCalculate(quote, []);
  assert.equal(quote.record.Legal_Review_Required__c, false);
});
