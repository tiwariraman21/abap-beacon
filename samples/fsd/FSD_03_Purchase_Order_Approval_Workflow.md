# FSD - Purchase Order Approval Workflow with Email Notifications

## Document Control
| Item | Value |
|---|---|
| Author | Functional Consultant, MM |
| Version | 1.0 |
| Status | Draft |
| Module | MM |

## 1. Business Requirement
Purchase orders above a value threshold must be approved by the cost centre manager and, above a second threshold, by the finance controller before they can be sent to the supplier. Today approvals are collected by e-mail outside SAP and the PO is released manually in ME29N.

## 2. Processing Logic
- When a purchase order is created or changed and its net value exceeds the threshold, the system shall start an approval workflow automatically.
- The thresholds and the approver determination (per purchasing organisation and cost centre) shall be maintained in a custom configuration table.
- The first approver shall receive a work item in the SAP inbox and an e-mail notification with the PO details and a link to approve or reject.
- On approval the PO shall be released via the release strategy (release code per level).
- On rejection the PO shall be blocked, the requester shall be notified by e-mail with the rejection reason and the workflow ends.
- If the approver does not act within 2 working days the work item shall escalate to the approver's substitute.
- The system shall record every approval decision with user, timestamp and comment for audit.

## 3. Output
- An approval history report shall display all POs with their approval steps, decision, approver and time taken, with a selection by purchasing organisation, date range and PO number.
- The report must allow download to Excel.

## 4. Error Handling
- Workflow errors shall be written to the application log and the MM support team must be notified by e-mail.

## 5. Authorization
- Only users with the approver role for the purchasing organisation may approve; authorization must be checked in the workflow task and in the report.
