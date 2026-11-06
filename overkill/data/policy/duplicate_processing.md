---
category: duplicate_processing
---
## duplicate_processing-definition
Duplicate processing: definition and qualifying conditions. A single purchase was charged more than once, or the cardholder paid by another method and the card was charged as well (R4). Qualifying conditions: (1) one purchase: one order, booking, bill or invoice; (2) two or more settled charges for it, usually the same amount close together in time, or proof of a second payment by other means; (3) the cardholder recognises the merchant. Network references: Visa 12.6.1 and 12.6.2, Mastercard 4834.

## duplicate_processing-evidence
Duplicate processing: evidence and exclusions. Evidence: both statement lines, a single receipt or order number, proof of the other payment (cash receipt, transfer reference). Exclusions: a pending authorisation hold that drops off; two genuine separate purchases; a recurring charge after cancellation that the cardholder calls a "double charge" (cancelled_recurring, R10); one charge for more than the agreed price, or an extra fee posted as a separate line (incorrect_amount); two charges from a merchant the cardholder does not recognise (unauthorised).

## duplicate_processing-precedent-1
Precedent: fuel terminal timeout. At a fuel station the card terminal timed out and the attendant re-ran the card. Both ₹3,450 charges settled two minutes apart for a single fill-up. Decision: duplicate_processing.

## duplicate_processing-precedent-2
Precedent: plumber paid by transfer and by card. A cardholder paid a plumber's invoice by bank transfer, and the plumber also charged the card kept on file for the same invoice. Decision: duplicate_processing (paid by other means, R4), not incorrect_amount and not unauthorised.
