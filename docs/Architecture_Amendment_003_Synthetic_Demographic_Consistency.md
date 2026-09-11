# Architecture Amendment 003: Synthetic demographic consistency

## Purpose

TrustID's synthetic national identity and driving licence records now use structured names, an authority-held gender value and a matching identity photograph. This makes the demonstration data coherent without expanding the information returned by a verification.

## Name structure

Both trusted sources store surname, first name and an optional middle name separately. The displayed full name is assembled from the available parts. Some records intentionally have no middle name because a middle name is not universal.

The synthetic profiles include varied Nigerian naming conventions. These include patronymic middle names, compound female names, two-part names and three-part names across several cultural groups. A name component is never used to infer gender.

## Gender and photographs

Gender is stored independently by each trusted source and is used only to keep synthetic portrait assignments credible. Matching synthetic records across the two sources retain the same name, date of birth, gender and photograph. Independent driving licence records remain self-contained.

Gender is not a verification category and is not returned in verification results, receipts, history or public authenticity pages.

## Production principle

Production data must use the value supplied by the responsible identity authority. TrustID must not infer a person's gender from their name or photograph. The deterministic assignment in the synthetic dataset exists only to keep demonstration records internally consistent.
