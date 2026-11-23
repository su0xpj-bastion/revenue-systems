/**
 * Builds the wire payloads described in contracts/*.schema.json.
 *
 * Every payload is a full snapshot of the contract at one version, never a diff. A full snapshot can be
 * re-sent, replayed out of order (the target keeps the highest version), or used to repair drift.
 * Lines are sorted by lineKey so the same version always serializes to the same bytes.
 */
public inherited sharing class OutboxPayloads {
    public static final String CONTRACT_SCHEMA = 'q2c.contract.v1';
    public static final String AGREEMENT_SCHEMA = 'q2c.agreement.v1';

    public static List<Q2C_Contract__c> loadContracts(Set<Id> ids) {
        return [
            SELECT Id, Name, Status__c, Version__c, Account__c, Billing_Account_Id__c, Start_Date__c, End_Date__c,
                CLM_Agreement_Id__c,
                (SELECT Line_Key__c, Product_Code__c, Quantity__c, Unit_Price__c FROM Subscriptions__r ORDER BY Line_Key__c)
            FROM Q2C_Contract__c
            WHERE Id IN :ids
        ];
    }

    public static String build(Q2C_Contract__c c, String target, String operation) {
        Map<String, Object> body = new Map<String, Object>{
            'operation' => operation,
            'contractId' => c.Id,
            'version' => c.Version__c.intValue(),
            'status' => c.Status__c
        };
        if (target == 'Billing') {
            body.put('schema', CONTRACT_SCHEMA);
            body.put('billingAccountId', c.Billing_Account_Id__c);
            body.put('startDate', c.Start_Date__c);
            body.put('endDate', c.End_Date__c);
            body.put('lines', lines(c));
        } else {
            body.put('schema', AGREEMENT_SCHEMA);
            body.put('externalReference', c.Id);
            body.put('agreementId', c.CLM_Agreement_Id__c);
            body.put('title', c.Name);
            body.put('lines', lines(c));
        }
        return JSON.serialize(body, true);
    }

    static List<Map<String, Object>> lines(Q2C_Contract__c c) {
        List<Map<String, Object>> out = new List<Map<String, Object>>();
        for (Q2C_Subscription__c s : c.Subscriptions__r) {
            out.add(new Map<String, Object>{
                'lineKey' => s.Line_Key__c,
                'productCode' => s.Product_Code__c,
                'quantity' => s.Quantity__c,
                'unitPrice' => s.Unit_Price__c
            });
        }
        return out;
    }
}
