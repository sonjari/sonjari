# Kyobo "990p": reward points read as page count (2026-09-06)

## What was found

Task given to a browser agent: "From Kyobo Bookstore, give me the page count and publisher of 3 accounting books."

The agent was Browser Use with default settings, run once with a local Gemma 4 26B (QAT) and once with Claude Sonnet 5. Both models gave the same wrong page counts for the three books: **990p, 990p, 2,250p**.

Those numbers are not page counts. On the Kyobo **search results (listing) page** they are the **reward points** shown next to each book. The markup holding them uses the class `point` (followed by a `rate` element). Neither model opened a product page. Both stopped at the listing because a plausible-looking "NNNp" value was already there. Sonnet also said the data came straight from the listing.

Counts on the saved listing page:

| what | count |
|---|---|
| `class="point"` (reward points markup) | 20 |
| the Korean page-count unit "쪽" | 0 |
| `990p` | 2 |
| `2,250` | 1 |

The listing page has **no page-count field at all**. The only "p" numbers on it are points.

Why this matters: the wrong values really are on the page, so a usual grounding check ("is this number in what the agent read?") passes them. The missing check is whether the agent read **the right field**.

Correction to the brief: the 09-06 finding was on the search **listing** page, not on product pages. A page count, if available, has to come from the product page; the listing never had one. (That the product page shows it as its own labelled field was not re-checked for this note.)

Limits: one task, one run per model, default Browser Use settings. No run told the agent to open the detail page. It is a reproducible finding, not a benchmark.

## How to reproduce

1. Fetch the Kyobo search listing for a keyword (the original used the Korean word for "accounting"; any book keyword should behave the same):

   ```bash
   curl -s "https://search.kyobobook.co.kr/search?keyword=<keyword>&target=total" -o listing.html
   ```

2. Look for the two fields:

   ```bash
   grep -c "쪽" listing.html                       # page-count unit: expected 0
   grep -o 'class="point"' listing.html | wc -l    # reward-points markup: expected about 20
   ```

3. Open the product page of any listed book and find the page-count field (number followed by the page unit "쪽") and the reward-points field (labelled as points). Compare both with what the agent reported.

If an agent reports page counts that match the `point` values and not the product page's page-count field, it has the same bug.

Page layouts change over time. The counts above are from 2026-09-06.
