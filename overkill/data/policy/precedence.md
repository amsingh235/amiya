---
category: precedence
---
<!-- Cross-category precedence rules. These resolve the "two categories plausibly apply" tier.
     One rule per section = one retrievable document. DRAFT: rewrite in your own words. -->

## R1 Recognition beats wording
If the cardholder recognises the merchant or admits making the purchase, the dispute is not unauthorised, even when they write "fraud", "unauthorised" or "I didn't authorise this". Words like these often mean "I didn't agree to what happened", not "it wasn't me". Classify by what went wrong with the recognised purchase: the amount, the delivery, the condition, the renewal, or the processing.

## R2 An acknowledged refund that never arrived is credit not processed
If the merchant agreed to refund, issued a refund confirmation or reference, accepted a return, or cancelled an order or booking while promising the money back, and the credit did not arrive, label credit_not_processed. This holds even when the original problem was quality, non-delivery or a cancelled service: once the merchant has acknowledged the debt, the dispute is about the missing credit. Exception: recurring billing after cancellation (R3).

## R3 Billing after cancelling a recurring plan is cancelled recurring
A subscription, membership, plan or auto-renewal charge taken after the cardholder cancelled, or after the merchant confirmed the cancellation, is cancelled_recurring. It stays cancelled_recurring even if the merchant later promised to refund that charge, and even if the renewal came through at a different price. The root cause is the cancellation not being honoured.

## R4 Paid by other means counts as duplicate processing
If the cardholder paid for the same purchase by another method (cash, cash on delivery, another card, bank transfer, UPI, voucher) and the card was charged as well, label duplicate_processing. This includes a terminal that showed a decline, after which the cardholder paid with a different card and both were charged. Without a second payment, a charge after a decline is processing_error (R5).

## R5 Price wrong versus mechanics wrong
Compare what was charged with what was agreed. If the agreed price itself was exceeded (overcharge, undisclosed fee, altered tip, extra nights, wrong quantity, a quote that was exceeded) label incorrect_amount. If the agreed price was right but the processing was wrong (wrong currency, a conversion the cardholder declined, the wrong card or account, a charge after a decline, posting months late, a refund processed as a charge) label processing_error. A merchant blaming "currency conversion" when no foreign currency was involved is still incorrect_amount.

## R6 Goods versus services
Physical goods and digital goods (downloads, licence keys, gift cards and e-gift cards, in-game items) that never arrived are product_not_received. Experiences, bookings, appointments, travel, events, classes, online courses, memberships to a venue, installations, repairs and labour that did not happen are service_not_rendered. When a purchase bundles both, classify by the part the cardholder actually paid for and did not get.

## R7 Wrong or broken is quality, missing is not received
A delivered item that is damaged, defective, counterfeit, used when sold as new, the wrong item, the wrong size or model, or materially different from its description is product_quality. Items missing from a delivery, or a parcel marked delivered that never reached the cardholder, are product_not_received.

## R8 A short refund is still credit not processed
If the merchant refunded less than the amount it agreed to refund, label credit_not_processed (a partial credit), not incorrect_amount. Incorrect_amount is about the original charge exceeding the agreed price, not about the size of a refund.

## R9 A failed service with no refund promise is service not rendered
If the merchant cancelled or failed to provide a service and has not agreed to refund, label service_not_rendered. Silence, a closed website or a shut-down company is not a refund agreement. Contrast R2: the same cancelled event becomes credit_not_processed once the organiser promises a refund that never comes.

## R10 Classify by the facts, not the stated reason
Cardholders often pick the wrong reason. When the reason they name ("duplicate", "item not received", "wrong amount", "fraud") contradicts the facts they describe, the facts decide. Example: a cardholder files "item not received" for a parcel they received and sent back with the seller's approval; the facts describe a refund that never arrived, so the label is credit_not_processed.
