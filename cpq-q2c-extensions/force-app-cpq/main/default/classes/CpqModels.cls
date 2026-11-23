/**
 * Apex shapes for the Salesforce CPQ API's JSON (SBQQ.ServiceRouter). CPQ returns and accepts
 * these as JSON strings; the field names must match the package's models exactly.
 * Only the fields this project uses are declared. JSON.deserialize ignores the rest.
 */
public with sharing class CpqModels {

    public class QuoteModel {
        public SBQQ__Quote__c record;
        public List<QuoteLineModel> lineItems;
        public List<QuoteLineGroupModel> lineItemGroups;
        public Integer nextKey;
        public Boolean applyAdditionalDiscountLast;
        public Boolean applyPartnerDiscountFirst;
        public Boolean channelDiscountsOffList;
        public Decimal customerTotal;
        public Decimal netTotal;
        public Decimal netNonSegmentTotal;
    }

    public class QuoteLineModel {
        public SBQQ__QuoteLine__c record;
        public Boolean amountDiscountProrated;
        public Integer parentGroupKey;
        public Integer parentItemKey;
        public Integer key;
        public Boolean upliftable;
        public String configurationType;
        public String configurationEvent;
        public Boolean reconfigurationDisabled;
        public Boolean descriptionLocked;
        public Boolean productQuantityEditable;
        public Decimal productQuantityScale;
        public String dimensionType;
        public Boolean productHasDimensions;
        public Decimal targetCustomerAmount;
        public Decimal targetCustomerTotal;
    }

    public class QuoteLineGroupModel {
        public SBQQ__QuoteLineGroup__c record;
        public Decimal netNonSegmentTotal;
        public Integer key;
    }

    public class CalculatorContext {
        public QuoteModel quote;
        public String callbackClass;
    }

    public class RenewalContext {
        public Id masterContractId;
        public List<Contract> renewedContracts;
    }
}
