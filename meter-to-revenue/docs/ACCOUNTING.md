# Recognition policy and journal patterns

Simplified, ASC 606-style. Confirm with Accounting before using any of this as policy.

## Policy

| Billed item | Billing | Recognition |
|---|---|---|
| Seats / flat fee, monthly | In advance, per month | Ratably by day over the month |
| Seats, annual | In advance, on each anniversary | Ratably by day over the 12-month service period; rounding remainder in the last period |
| Usage (pay as you go) | In arrears, monthly | In the period consumed |
| Prepaid commit | In full, in the first period | Deferred. Released as usage draws it down; any unused balance is recognized as **breakage** in the contract's last period |
| Usage covered by a commit | Shown at list price with an equal negative "credit applied" line | Revenue at list in the period consumed; the credit applied releases deferred revenue |

**Simplifications:** no standalone-selling-price allocation across bundled obligations; breakage at expiry
(not estimated and recognized as the commit is consumed); no variable-consideration constraint; single currency.

## Journal patterns

**Invoice**
```
Dr Accounts Receivable        invoice total
Dr Deferred Revenue           credit applied
    Cr Deferred Revenue       subscriptions + prepaid commits
    Cr Revenue                usage at list
    Cr Tax Payable            tax
```

**Period recognition**
```
Dr Deferred Revenue           ratable subscription share + breakage
    Cr Revenue
```

## Worked example (the example book, March–April 2027)

**Acme annual seats.** 20 × $30 × 12 = $7,200 billed Mar 1 for Mar 1 2027 to Mar 1 2028 (366 days, spanning Feb 29 2028).
- March: 7,200 × 31/366 = **$609.84**; April: 7,200 × 30/366 = **$590.16**; the remaining **$6,000.00** is deferred.

**Globex prepaid commit.** $5,000 billed in March (deferred).
- March usage 1,200 M tokens = 100 × 3.00 + 900 × 2.50 + 200 × 2.00 = **$2,950**. Fully covered by credit, so the invoice nets to $0 for usage. Revenue +2,950; deferred −2,950.
- April usage 1,000 = 100 × 3.00 + 900 × 2.50 = **$2,550**. Only $2,050 credit is left, so **$500 is overage** billed to AR.
- Commit fully used, so no breakage.

**Initech prepaid commit.** $1,000 billed; $300 used in March; **$700 breakage** recognized in April (last period).

**Deferred revenue roll-forward**
```
2027-03:    0.00 + 14,000.00 − 4,659.84 = 9,340.16
2027-04: 9,340.16 +    800.00 − 4,140.16 = 6,000.00
```
Billed into deferred in March: 7,200 + 300 + 500 + 5,000 + 1,000. Released in March: subscriptions
609.84 + 300 + 500, plus credit applied 2,950 + 300.

**Trial balance through April** (debit +): AR 16,971.28 · Deferred −6,000.00 · Revenue −9,875.00 · Tax −1,096.28. It sums to 0.
