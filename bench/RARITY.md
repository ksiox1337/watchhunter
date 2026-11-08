# Rarity benchmark

`bench/rarity_bench.py` checks the rarity tier the evaluator assigns against an
expected tier per reference (`bench/rarity_refs.json`): 17 references, up to 6
live eBay listings each (EBAY_DE + EBAY_US, auctions and Buy It Now, spread
over the whole price range, parts/accessories filtered out). 95 listings on
2026-11-08.

Expected tiers are a collector's judgement, not ground truth: Citizen 8110
"Bullhead" (labelled medium) is the most debatable one.

| Classifier | Accuracy | Rare recall | Rare precision |
|---|---|---|---|
| gpt-5-mini verdict, old prompt | 72% | 22/29 | 22/31 |
| Jev `choice`, title only | 78% | 27/29 | 27/46 |
| **gpt-5-mini verdict, new rarity definition** | **84%** | **27/29** | **27/37** |
| min(mini, Jev) | 85% | 24/29 | 24/32 |
| max(mini, Jev) | 76% | 29/29 | 29/50 |

What changed in the prompt: "low" is only current production / modern mass
market (a discontinued vintage reference is at least "medium"), and "high" has
concrete examples. Old prompt put vintage Seiko 6119 / 7T32 and Citizen
Crystron into "low" and Casio CA-90 into "medium".

Kept: gpt-5-mini alone (no extra call, best balance). Jev stays the triage
model, where its high recall is what we want.

Remaining errors: medium → high on Citizen 8110 (5 of 6), two Seiko 6309, one
Bell-Matic, 6119 and Crystron; high → medium on one CA-90 and one Casiotron.

```sh
.venv/bin/python bench/rarity_bench.py fetch          # rebuild the listing set
.venv/bin/python bench/rarity_bench.py run mini jev   # ~$0.06 + Jev
```
