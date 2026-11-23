import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  LINE_FIELDS, QUOTE_FIELDS, approvalLevel, isFieldEditable, onAfterCalculate, onBeforeCalculate,
  prorate, renewalPrice,
} from '../src/quote-calculator-plugin.js';

const vectors = JSON.parse(readFileSync(new URL('../../vectors/pricing-vectors.json', import.meta.url)));
const money = (n) => n.toFixed(2);

for (const v of vectors.proration) {
  test(`proration: ${v.name}`, () => {
    const got = prorate({ start: v.start, end: v.end, method: v.method, monthlyPrice: v.monthly_price, quantity: v.quantity });
    assert.equal(money(got), v.expected);
  });
}

for (const v of vectors.renewal) {
  test(`renewal: ${v.name}`, () => {
    assert.equal(money(renewalPrice({ list: v.list, prior: v.prior, capPct: v.cap_pct, grandfathered: v.grandfathered })), v.expected);
  });
}

for (const v of vectors.approval) {
  test(`approval: ${v.name}`, () => {
    const { level } = approvalLevel({
      maxDiscountPct: v.max_discount_pct, floorBreach: v.floor_breach,
      paymentTerms: v.payment_terms, termMonths: v.term_months,
    });
    assert.equal(level, v.expected_level);
  });
}

// --- hooks against CPQ-shaped models ------------------------------------------

const quote = (fields) => ({ record: { SBQQ__PaymentTerms__c: 'Net 30', SBQQ__SubscriptionTerm__c: 12, ...fields } });
const line = (fields) => ({ record: { ...fields } });

test('renewal quote: special price set from prior net, capped at list', async () => {
  const q = quote({ SBQQ__Type__c: 'Renewal', Renewal_Cap_Pct__c: 7 });
  const lines = [
    line({ SBQQ__ListPrice__c: 30, Prior_Net_Price__c: 25 }),
    line({ SBQQ__ListPrice__c: 30, Prior_Net_Price__c: 20, Grandfathered__c: true }),
    line({ SBQQ__ListPrice__c: 30 }),                            // new product on the renewal: untouched
  ];
  await onBeforeCalculate(q, lines);
  assert.equal(lines[0].record.SBQQ__SpecialPrice__c, 26.75);
  assert.equal(lines[0].record.SBQQ__SpecialPriceType__c, 'Custom');
  assert.equal(lines[1].record.SBQQ__SpecialPrice__c, 20);
  assert.equal(lines[2].record.SBQQ__SpecialPrice__c, undefined);
});

test('new-business quote: renewal pricing does not run', async () => {
  const lines = [line({ SBQQ__ListPrice__c: 30, Prior_Net_Price__c: 25 })];
  await onBeforeCalculate(quote({ SBQQ__Type__c: 'Quote' }), lines);
  assert.equal(lines[0].record.SBQQ__SpecialPrice__c, undefined);
});

test('after calculate: floor breach and approval level on the quote', async () => {
  const q = quote({ SBQQ__Type__c: 'Quote' });
  const lines = [
    line({ SBQQ__ListPrice__c: 100, SBQQ__NetPrice__c: 92, Max_Discount_Pct__c: 25 }),  // 8% off, above floor 75
    line({ SBQQ__ListPrice__c: 50, SBQQ__NetPrice__c: 42, Max_Discount_Pct__c: 10 }),   // 16% off, floor 45 → breach
  ];
  await onAfterCalculate(q, lines);
  assert.equal(lines[0].record.Floor_Price__c, 75);
  assert.equal(lines[0].record.Floor_Breach__c, false);
  assert.equal(lines[1].record.Floor_Breach__c, true);
  assert.equal(q.record.Max_Line_Discount__c, 16);
  assert.equal(q.record.Approval_Level__c, 2);
  assert.match(q.record.Approval_Reasons__c, /below floor/);
});

test('grandfathered lines do not count toward the discount signal', async () => {
  const q = quote({ SBQQ__Type__c: 'Renewal' });
  await onAfterCalculate(q, [line({ SBQQ__ListPrice__c: 30, SBQQ__NetPrice__c: 15, Grandfathered__c: true })]);
  assert.equal(q.record.Approval_Level__c, 0);
});

test('grandfathered lines are locked against re-discounting', () => {
  assert.equal(isFieldEditable('SBQQ__Discount__c', { Grandfathered__c: true }), false);
  assert.equal(isFieldEditable('SBQQ__Quantity__c', { Grandfathered__c: true }), null);
  assert.equal(isFieldEditable('SBQQ__Discount__c', { Grandfathered__c: false }), null);
});

test('every field the plugin touches is declared for CPQ', () => {
  const source = readFileSync(new URL('../src/quote-calculator-plugin.js', import.meta.url), 'utf8');
  const used = new Set([...source.matchAll(/\b(?:r|quote)\.([A-Za-z_]+__c)\b/g)].map((m) => m[1]));
  const declared = new Set([...QUOTE_FIELDS, ...LINE_FIELDS]);
  assert.deepEqual([...used].filter((f) => !declared.has(f)), []);
});
