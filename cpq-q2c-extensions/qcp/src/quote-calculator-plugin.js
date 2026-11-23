/**
 * Quote Calculator Plugin (QCP) for Salesforce CPQ.
 *
 * Deployed as the SBQQ__Code__c of an SBQQ__CustomScript__c record and selected in
 * CPQ Settings → Plugins → Quote Calculator Plugin. CPQ runs it in the calculator for the quote
 * line editor, the Quote API and background calculations, so pricing rules here apply everywhere
 * a quote is priced.
 *
 * CPQ does not allow imports, so this file is self-contained. Every field it reads or writes must
 * be listed in the custom script's Quote Fields / Quote Line Fields (see QUOTE_FIELDS and
 * LINE_FIELDS; scripts/build-qcp-record.mjs writes them for you).
 *
 * What it does, and why it is code rather than price rules:
 *  1. Renewal pricing (onBeforeCalculate): renew at min(list, prior net × (1 + cap)), or hold the prior
 *     price for grandfathered lines. Needs per-line min() against a value from the renewed
 *     subscription, which price rules cannot express cleanly across bundles.
 *  2. Floor prices (onAfterCalculate): floor = list × (1 − product max discount). Flags lines whose
 *     final net price, after every discount layer, falls below it.
 *  3. Approval level (onAfterCalculate): one quote-level number that Advanced Approvals rules key
 *     off, computed from the strongest signal across all lines.
 *  4. Field locks (isFieldEditable): grandfathered renewal lines cannot be re-discounted.
 *  5. Contract terms (onAfterCalculate): non-standard liability cap, auto-renew off or termination
 *     for convenience flag the quote for Legal and raise the approval level.
 *
 * The pure functions at the bottom are exported for unit tests and mirrored in Apex
 * (force-app-core); both run the same vectors in vectors/pricing-vectors.json.
 */

export const QUOTE_FIELDS = [
  'SBQQ__Type__c', 'SBQQ__PaymentTerms__c', 'SBQQ__SubscriptionTerm__c',
  'Renewal_Cap_Pct__c', 'Max_Line_Discount__c', 'Approval_Level__c', 'Approval_Reasons__c',
  'Liability_Cap__c', 'Auto_Renew__c', 'Termination_For_Convenience__c', 'Legal_Review_Required__c',
];
export const LINE_FIELDS = [
  'SBQQ__ListPrice__c', 'SBQQ__NetPrice__c', 'SBQQ__SpecialPrice__c', 'SBQQ__SpecialPriceType__c',
  'Max_Discount_Pct__c', 'Floor_Price__c', 'Floor_Breach__c', 'Prior_Net_Price__c', 'Grandfathered__c',
];

const STANDARD_PAYMENT_TERMS = ['Net 30'];

// --- CPQ hooks ---------------------------------------------------------------

export function onBeforeCalculate(quoteModel, quoteLineModels) {
  const quote = quoteModel.record;
  if (quote.SBQQ__Type__c === 'Renewal') {
    quoteLineModels.forEach((line) => {
      const r = line.record;
      if (r.Prior_Net_Price__c == null && !r.Grandfathered__c) return;
      r.SBQQ__SpecialPrice__c = renewalPrice({
        list: r.SBQQ__ListPrice__c,
        prior: r.Prior_Net_Price__c,
        capPct: quote.Renewal_Cap_Pct__c || 0,
        grandfathered: !!r.Grandfathered__c,
      });
      r.SBQQ__SpecialPriceType__c = 'Custom';
    });
  }
  return Promise.resolve();
}

export function onAfterCalculate(quoteModel, quoteLineModels) {
  const quote = quoteModel.record;
  let maxDiscount = 0;
  let floorBreach = false;
  quoteLineModels.forEach((line) => {
    const r = line.record;
    const list = r.SBQQ__ListPrice__c;
    if (!list) return;
    r.Floor_Price__c = round2(list * (1 - (r.Max_Discount_Pct__c || 0) / 100));
    r.Floor_Breach__c = r.Max_Discount_Pct__c != null && r.SBQQ__NetPrice__c < r.Floor_Price__c - 0.005;
    floorBreach = floorBreach || r.Floor_Breach__c;
    if (!r.Grandfathered__c) {
      maxDiscount = Math.max(maxDiscount, effectiveDiscountPct(list, r.SBQQ__NetPrice__c));
    }
  });
  const result = approvalLevel({
    maxDiscountPct: maxDiscount,
    floorBreach,
    paymentTerms: quote.SBQQ__PaymentTerms__c,
    termMonths: quote.SBQQ__SubscriptionTerm__c,
  });
  const terms = termsReview({
    liabilityCap: quote.Liability_Cap__c,
    autoRenew: quote.Auto_Renew__c !== false,
    terminationForConvenience: !!quote.Termination_For_Convenience__c,
  });
  quote.Max_Line_Discount__c = round2(maxDiscount);
  quote.Approval_Level__c = Math.max(result.level, terms.level);
  quote.Approval_Reasons__c = [...result.reasons, ...terms.reasons].join('; ');
  quote.Legal_Review_Required__c = terms.legal;
  return Promise.resolve();
}

export function isFieldEditable(fieldName, line) {
  const discountFields = ['SBQQ__Discount__c', 'SBQQ__AdditionalDiscountAmount__c', 'SBQQ__SpecialPrice__c'];
  if (line && line.Grandfathered__c && discountFields.includes(fieldName)) {
    return false;
  }
  return null; // defer to CPQ's own rules
}

// --- pure pricing logic (mirrored in Apex) -----------------------------------

export function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

export function effectiveDiscountPct(list, net) {
  if (!list || net == null) return 0;
  return Math.max(0, round2((1 - net / list) * 100));
}

export function renewalPrice({ list, prior, capPct, grandfathered }) {
  if (grandfathered && prior != null) return round2(prior);
  if (prior == null) return round2(list);
  return round2(Math.min(list, prior * (1 + capPct / 100)));
}

export function approvalLevel({ maxDiscountPct, floorBreach, paymentTerms, termMonths }) {
  const reasons = [];
  let level = 0;
  const raise = (to, why) => {
    if (to > 0) reasons.push(why);
    level = Math.max(level, to);
  };
  const d = maxDiscountPct || 0;
  if (d > 35) raise(3, `discount ${d}% > 35%`);
  else if (d > 20) raise(2, `discount ${d}% > 20%`);
  else if (d > 10) raise(1, `discount ${d}% > 10%`);
  if (floorBreach) raise(2, 'net price below floor');
  if (paymentTerms && !STANDARD_PAYMENT_TERMS.includes(paymentTerms)) raise(1, `payment terms ${paymentTerms}`);
  if ((termMonths || 0) > 36) raise(2, `term ${termMonths} months > 36`);
  return { level, reasons };
}

const STANDARD_LIABILITY_CAP = '1x fees';

/** Non-standard contract terms: Legal always reviews; the level reflects the business risk. */
export function termsReview({ liabilityCap, autoRenew, terminationForConvenience }) {
  const reasons = [];
  let level = 0;
  const flag = (to, why) => { reasons.push(why); level = Math.max(level, to); };
  if (liabilityCap && liabilityCap !== STANDARD_LIABILITY_CAP) {
    flag(liabilityCap === 'Uncapped' ? 3 : 1, `liability cap ${liabilityCap}`);
  }
  if (autoRenew === false) flag(1, 'auto-renew off');
  if (terminationForConvenience) flag(2, 'termination for convenience');
  return { level, legal: reasons.length > 0, reasons };
}

const DAY_MS = 86400000;

function parseDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return { y, m, d };
}

function daysInMonth(y, m) {
  return new Date(Date.UTC(y, m, 0)).getUTCDate();
}

function addMonths({ y, m, d }, n) {
  const index = m - 1 + n;
  const year = y + Math.floor(index / 12);
  const month = (index % 12) + 1;
  return { y: year, m: month, d: Math.min(d, daysInMonth(year, month)) };
}

function toUtc({ y, m, d }) {
  return Date.UTC(y, m - 1, d);
}

export function prorationMonths(startIso, endIso, method) {
  const start = parseDate(startIso);
  const end = toUtc(parseDate(endIso));
  if (toUtc(start) >= end) return 0;
  const days = (end - toUtc(start)) / DAY_MS;
  if (method === 'daily') return (days * 12) / 365;
  let months = 0;
  while (toUtc(addMonths(start, months + 1)) <= end) months += 1;
  const cursor = addMonths(start, months);
  const leftover = (end - toUtc(cursor)) / DAY_MS;
  if (method === 'monthly') return leftover > 0 ? months + 1 : months;
  return months + leftover / daysInMonth(cursor.y, cursor.m);
}

export function prorate({ start, end, method, monthlyPrice, quantity }) {
  return round2(monthlyPrice * quantity * prorationMonths(start, end, method));
}
