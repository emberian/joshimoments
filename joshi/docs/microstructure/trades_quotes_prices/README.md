# Trades, Quotes and Prices: JOSHI formalization corpus

## Purpose

This corpus is an original, highly distilled first-pass formalization of Jean-Philippe Bouchaud,
Julius Bonart, Jonathan Donier, and Martin Gould's *Trades, Quotes and Prices: Financial Markets
Under the Microscope* (Cambridge University Press, 2018). It is a conceptual and empirical beacon
for JOSHI, not a substitute for the book and not a claim that limit-order-book results apply
unchanged to Solana memecoins.

The corpus has four jobs:

1. make the book's models, assumptions, variables, and dependencies inspectable;
2. keep empirical findings separate from model consequences and author heuristics;
3. identify concrete JOSHI evidence, schema, glass, and research implications; and
4. make transfer failures explicit before an elegant LOB result becomes an AMM trading rule.

## Source boundary

| field | value |
| --- | --- |
| Title | *Trades, Quotes and Prices: Financial Markets Under the Microscope* |
| Authors | Jean-Philippe Bouchaud; Julius Bonart; Jonathan Donier; Martin Gould |
| Publisher/year | Cambridge University Press, 2018 |
| Edition | First edition |
| ISBN-13 | `9781107156050` |
| PDF pages | 463 |
| SHA-256 | `289c40fdb0ba973cf60c00c33fbaa06bf01a6e645d53cbbaac1e46fd5c81cd8c` |
| Repository treatment | Source PDF excluded; private extraction and renders live under ignored `state/books/trades_quotes_prices/` |

The rendered title page was checked because the source filename omits Martin Gould; the title page
names all four authors. The repository does not contain the PDF, a full transcription, or a
near-verbatim reconstruction. Equations are included only when needed to state a model or
dependency. Quotations are avoided except for short necessary labels.

## Page-reference convention

References such as `p. 253, Eq. 13.9` use the **printed book page**, not the PDF viewer page. For
numbered body matter and the index:

```text
PDF page = printed page + 19
printed page = PDF page - 19
```

Thus printed p. 253 is PDF page 272. Front matter is cited by printed Roman numeral or explicit PDF
page. Figure, table, equation, chapter, and section identifiers retain the book's identifiers.

## Corpus map

- [`BOOK_MAP.md`](BOOK_MAP.md): parts, chapters, sections, pages, and conceptual route.
- [`GLOSSARY.md`](GLOSSARY.md): source concepts plus JOSHI-safe distinctions.
- [`FORMAL_MODEL.md`](FORMAL_MODEL.md): definitions, assumptions, equations, propositions, and
  dependency graph in new words.
- [`EMPIRICAL_CLAIMS.md`](EMPIRICAL_CLAIMS.md): evidence separated from models, identities,
  interpretations, and heuristics.
- [`CHAPTER_NOTES.md`](CHAPTER_NOTES.md): chapter-by-chapter distilled notes.
- [`JOSHI_BEACON.md`](JOSHI_BEACON.md): concrete evidence, schema, glass, analysis, and research
  consequences.
- [`TRANSFER_LIMITS.md`](TRANSFER_LIMITS.md): where LOB results do and do not survive contact with
  Pump, PumpSwap, Meteora, Solana, social attention, and Ember's episode process.
- [`OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md): unresolved formal, empirical, transfer, and engineering
  lanes.

## Extraction and visual-verification report

The PDF has a high-quality text layer for prose, headings, captions, page numbers, and most
symbols. Search and page routing are reliable. It is **not equation-safe** without a render:

- hats, tildes, primes, calligraphic letters, and some Greek characters can become control glyphs;
- square-root bars and large delimiters can disappear;
- summation/integration bounds can be reordered;
- multi-column and rotated tables lose their visual associations; and
- a caption can extract correctly while the plotted evidence remains invisible.

The following were personally checked against PNG renders:

- title page (PDF 4) and the complete TOC (PDF 8–13);
- equation-heavy pages in the queue, Hawkes, impact, propagator, adverse-selection,
  market-making, latent-liquidity, self-referential, and execution chapters, including printed
  pp. 85, 170, 253, 282, 293, 307, 325, 346, 358, 373, 388, and 400;
- tables including Table 4.1 and Table 11.1;
- figures including Figures 4.11, 12.2, 13.1, 16.6, 18.5, and 18.6; and
- the alternative market-making appendix, symbol list, index opening, and final PDF page.

Equations reproduced in [`FORMAL_MODEL.md`](FORMAL_MODEL.md) were checked against the rendered
source when the text layer showed a suspicious glyph. Equations not required for the dependency
map remain references rather than attempted transcriptions.

## Quality and uncertainty labels

- **Verified equation**: visually checked against the page render.
- **Model result**: follows inside the model's assumptions; not a theorem about actual markets.
- **Empirical claim**: supported by the sample described in the book; not presumed current or
  universal.
- **Author interpretation**: the book's explanation of evidence, which may have alternatives.
- **JOSHI hypothesis**: a proposed transfer to be tested prospectively.
- **Transfer warning**: a source-market assumption is absent or materially changed in JOSHI.

When a formula depends on several pages of derivation, this corpus records the boundary equation,
assumptions, and conclusion rather than reconstructing the derivation. Any future implementation
must return to the cited source pages and current venue/program specifications.

## Follow-up study order

The most valuable next passes are:

1. **AMM impact analogue:** define mark, local slope, exact-size quote, landing-state fill, and
   post-trade response separately for Pump curves, PumpSwap, and Meteora.
2. **Signed-flow memory:** estimate event-time and wall-time persistence by mint, lifecycle, venue,
   wallet cohort, and market regime without assuming LOB trade signs.
3. **Liquidity-provider economics:** decompose Meteora fees, inventory conversion, adverse
   selection, rebalancing friction, and full withdrawal/liquidation value.
4. **Attention excitation:** test whether trade, callout, creator, and social events alter event
   intensity while refusing the Hawkes-causality shortcut.
5. **Execution and management paths:** model partial exits, runners, flat watching, and re-entry as
   stateful episode decisions with executable quotes and counterfactual uncertainty.
6. **Impact-adjusted exposure:** replace mark-times-balance with size-specific liquidation and
   stress paths throughout the cockpit.

These are research lanes, not strategy recommendations or permission to automate trades.

