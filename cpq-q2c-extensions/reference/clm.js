/**
 * Executable reference for the contract lifecycle rules. The production implementation is Apex
 * (force-app-core: ContractLifecycle, RenewalNotice). This file exists so the shared vectors are
 * checked by node on every push, before any org is involved.
 */

const TRANSITIONS = {
  'Draft': ['In Negotiation'],
  'In Negotiation': ['Signed', 'Draft'],
  'Signed': ['Active'],
  'Active': ['Expiring', 'Terminated'],
  'Expiring': ['Renewed', 'Expired', 'Terminated'],
  'Renewed': [],
  'Expired': [],
  'Terminated': [],
};

export function contractCanTransition(from, to) {
  return from === to || (TRANSITIONS[from] || []).includes(to);
}

const DAY_MS = 86400000;
const PREP_DAYS = 30;
const toUtc = (iso) => Date.parse(`${iso}T00:00:00Z`);

/**
 * end_date is inclusive (Salesforce Contract.EndDate). notice date = end − notice days;
 * the prep window opens 30 days before the notice date.
 */
export function renewalNotice({ endDate, noticeDays, autoRenew, renewalQuoted, asOf }) {
  const end = toUtc(endDate);
  const prep = end - (noticeDays + PREP_DAYS) * DAY_MS;
  const today = toUtc(asOf);
  if (today < prep) return { action: 'none', expiring: false };
  if (today <= end) {
    if (renewalQuoted) return { action: 'none', expiring: true };
    return { action: autoRenew ? 'create_renewal_quote' : 'notify_owner', expiring: true };
  }
  if (!autoRenew) return { action: 'expire', expiring: false };
  return { action: renewalQuoted ? 'none' : 'create_renewal_quote', expiring: false };
}
