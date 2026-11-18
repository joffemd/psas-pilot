# Draft Canadian PSAS XBRL Taxonomy: Ontario Pilot

A working draft of an XBRL taxonomy for Canadian Public Sector Accounting Standards (PSAS). It is tested by tagging the
primary statements of Ontario's *Public Accounts 2025–26* in Inline XBRL.
Source: https://www.ontario.ca/page/public-accounts-2025-26-consolidated-financial-statements (retrieved Nov. 18, 2026).

**Status:** unofficial draft for discussion. It is not endorsed by PSAB, CPA Canada, XBRL International or the Province of Ontario.
The namespaces (`http://xbrl.example.org/...`) are placeholders.

## Contents

| Path | What it is |
|---|---|
| `taxonomy/psas-2026.xsd` | 92 PSAS monetary elements, plus statement headings and the Budget/Actual dimension |
| `taxonomy/psas-2026-lab.xml` | Standard labels, documentation (with PSAS section and GFS/COFOG cross-references), opening/closing balance labels |
| `taxonomy/psas-2026-entry-all.xsd` | Entry point that adds the generic presentation, calculation and dimension linkbases (`psas-2026-pre/cal/def.xml`) |
| `ontario-2026/on-2026.xsd` + linkbases | Ontario extension: 6 province-specific elements plus Ontario's own statement layouts and calculations |
| `ontario-2026/ontario-2026-ixbrl.xhtml` | The tagged statements, viewable in a browser and readable by any Inline XBRL processor |
| `viewer/ontario-2026-viewer.html` + `viewer/ixbrlviewer.js` | Interactive viewer (Arelle ixbrl-viewer 1.5.10): click any number to see its PSAS element, definition, period and calculations. Online at https://joffemd.github.io/psas-pilot/viewer/ontario-2026-viewer.html once GitHub Pages is enabled |
| `build/spec.py`, `build/build.py` | Generator. Element definitions and statement mappings are in `spec.py` |
| `source/ontario-public-accounts-2025-26.html` | Saved copy of Ontario's web page (retrieved Nov. 18, 2026), used as the build input. The Province's page remains the authoritative version |

## What is tagged

There are seven tables: Statement of Operations (with 2025–26 Budget column), Statement of Financial Position, Components
of Accumulated Deficit, Change in Net Debt (with Budget), Change in Accumulated Operating Deficit, Remeasurement
Gains and Losses, and Cash Flow.
- 265 tagged values (228 unique facts), 8 contexts, in millions of CAD.
- Every subtotal and total in the statements is encoded as a calculation relationship: 47 checks against Ontario's figures, all consistent.
- Notes, schedules and the auditor's report are **not** tagged yet.

## Design decisions (for reviewers)

1. **Built for the current model, with the new one in mind.** The statements follow PS 1201 (the format Ontario used for 2025–26).
   The central element, `NetFinancialAssetsLiabilities`, is named for PS 1202's "net financial assets (net financial liabilities)".
   Ontario's "Net Debt" is the same amount with a negative sign, so the taxonomy carries over when PS 1202 takes effect for fiscal years
   beginning on or after April 1, 2026.
2. **Budget comparison as a dimension.** PSAS requires budget-to-actual comparison. Budget amounts are tagged with
   `StatementScenarioAxis = BudgetMember`, and actual amounts use the default member. This keeps one element per line item.
3. **Sign convention.** Revenues, expenses, assets, liabilities, acquisitions and repayments are positive. Change and "effect"
   elements carry the sign shown in the statements (for example, the annual deficit is −13,006; an increase in net debt is negative).
   No `balance` attributes yet, because debit/credit semantics fit awkwardly with net debt and accumulated deficit. This needs expert review.
4. **Generic base, local extension.** Items such as the Ontario Health Premium, Ontario Power Generation adjustments and the
   Ontario Nuclear Funds are in the `on:` extension. Common provincial concepts (payroll tax, education property tax, federal
   transfers, investments in government business enterprises) are in the base taxonomy, so other provinces can reuse them.
5. **GFS/COFOG bridge.** Revenue and expense elements cite GFS and COFOG codes in their documentation, as a first step
   toward a later GFS taxonomy covering sovereign 18-K filers.
6. **Calculations live with the filer.** As with the US GAAP taxonomy, the base schema carries no calculation
   relationships, so a filer's extension defines its own totals. The `entry-all` entry point shows the generic model.

## Rebuild and validate

```bash
python build/build.py source/ontario-public-accounts-2025-26.html .
```
```bash
python -m arelle.CntlrCmdLine -f ontario-2026/ontario-2026-ixbrl.xhtml -v --calc=c10
```
Requires `beautifulsoup4`; validation uses Arelle (`pip install arelle-release`). Both the entry point and the Ontario document
validate with no errors or warnings in Arelle 2.47.5.

## Known gaps / next steps

- Tag the notes and schedules (debt, tangible capital assets, revenue by source, expense by ministry), with text blocks for the accounting policies.
- Add a second province, such as Saskatchewan or Quebec, to test which elements are really generic.
- Review the element names and definitions against the CPA Canada Handbook (subscription), and decide on `balance` attributes.
- Add PS 1202 statement structures once 2026–27 Public Accounts are published.
- Add a reference linkbase (PS section and paragraph, GFS and COFOG codes) in place of the documentation-label cross-references.
