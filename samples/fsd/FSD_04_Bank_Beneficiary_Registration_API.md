# FSD - Beneficiary Registration with Axis Bank API

## Document Control
| Item | Value |
|---|---|
| Author | Functional Consultant, FI |
| Version | 2.0 |
| Module | FI |

## 1. Business Requirement
Before vendor payments can be transferred through Axis Bank host-to-host, each vendor's bank account must be registered as a beneficiary with the bank. The registration shall be triggered from SAP when a new vendor bank detail is created or changed.

## 2. Processing Logic
- The system shall build the beneficiary registration request from the vendor bank details (bank key, account number, IFSC, beneficiary name) and call the Axis Bank payee management REST API.
- The request body must be encrypted with AES-128 and a checksum must be calculated as per the bank specification.
- The response shall be decrypted and the bank's beneficiary status stored against the vendor bank detail in a custom table with timestamp.
- Registration shall run automatically as a scheduled background job every hour for all pending vendor bank details.
- The bank endpoint, client id and client secret must be stored securely in configuration, not in the program.
- If the bank rejects the registration the vendor payment block shall be set and the treasury team notified by e-mail.

## 3. Output
- A monitoring report shall list all beneficiary registrations with status, bank response message and retry count, selectable by vendor, company code and date.

## 4. Error Handling
- All API calls and responses shall be logged in the application log (SLG1).
- Technical failures (timeout, HTTP error) shall be retried up to three times.

## 5. Authorization
- The report shall check authorization for the company code (F_LFA1_BUK).
