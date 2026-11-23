# Example: two billing periods, four contracts

| Contract | Shows |
|---|---|
| K-ACME | Annual seats billed in advance and recognized by day; graduated API usage; a late March event billed in April |
| K-GLOBEX | $5,000 prepaid commit drawn down by usage, used up in April, then overage |
| K-INITECH | $1,000 prepaid commit, $300 used, $700 breakage recognized at contract end |
| K-UMBRELLA | Monthly seats for a tax-exempt customer (certificate on file) |

Planted issues, caught by controls:
- `batch-2027-03` resends `evt-0002` → rejected as a duplicate (C-02 evidence), never billed twice
- `batch-2027-04` manifest says 4 events / 1,100 units, but 3 / 1,050 arrived → **C-01 fails** for April
- `changes.yaml`: carol approved her own seat change → **C-08 fails** for April

March: all 8 controls pass. April: C-01 and C-08 fail, with the exceptions listed in the evidence pack.
