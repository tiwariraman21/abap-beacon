# FSD - Sales Order Creation Interface from Salesforce

## Document Control
| Item | Value |
|---|---|
| Author | Functional Consultant, SD |
| Version | 1.2 |
| Status | Approved |
| Module | SD |

## 1. Business Requirement
Salesforce (SF) captures customer orders for the ADNOC business. Today the sales team re-keys these orders manually in VA01. The requirement is an inbound interface so that SAP creates the sales order automatically from the Salesforce opportunity and returns the SAP order number and any errors to Salesforce.

## 2. Interface Overview
- The interface shall be exposed as an OData service that Salesforce calls in real time.
- The payload will contain header data, item data, partner data, header texts, delivery information and item pricing elements.
- SAP must return the created sales order number (VBELN) and a status with messages to Salesforce.

## 3. Processing Logic
- The system shall check whether a sales order already exists for the Salesforce reference (SF opportunity id) and must not create a duplicate; instead the existing order number is returned.
- The sales order shall be created using BAPI_SALESORDER_CREATEFROMDAT2 with header, items, partners, schedule lines and conditions mapped from the payload.
- Item pricing elements from Salesforce shall be passed as manual conditions.
- After successful creation the system shall commit with BAPI_TRANSACTION_COMMIT and read the document back to return the order details.
- If the customer has a credit block, the order shall be released from the credit block automatically when the Salesforce payload indicates prepayment.
- Mapping between Salesforce values and SAP values (order type, sales organisation, distribution channel, division) shall be maintained in a custom mapping table maintainable via SM30.

## 4. Validations
- Customer number (KUNNR) must exist in the sales area; otherwise return an error.
- Material (MATNR) must exist and be valid for the plant; otherwise return an error.
- Requested delivery date must not be in the past.

## 5. Error Handling
- All BAPI return messages shall be collected and returned to Salesforce.
- Every call and its result must be written to the application log (SLG1) for support.

## 6. Authorization
- The interface user needs authorization for sales order creation in the relevant sales organisation (V_VBAK_VKO).
