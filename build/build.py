"""Generate the draft PSAS taxonomy, the Ontario extension, and an Inline XBRL rendering of
Ontario's 2025-26 consolidated financial statements.

Usage: python build.py <ontario_page.html> <output_root>
  <ontario_page.html>  saved copy of
      https://www.ontario.ca/page/public-accounts-2025-26-consolidated-financial-statements
  <output_root>        folder that will receive taxonomy/ and ontario-2026/
"""
import os, re, sys, html, datetime
from collections import defaultdict
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec import (PSAS_NS, ON_NS, PSAS_ELEMENTS, ON_ELEMENTS, STATEMENTS, BUDGET_ROLES, COLUMNS)

SRC, OUT = sys.argv[1], sys.argv[2]
TAX = os.path.join(OUT, "taxonomy")
ONT = os.path.join(OUT, "ontario-2026")
os.makedirs(TAX, exist_ok=True)
os.makedirs(ONT, exist_ok=True)
SOURCE_URL = "https://www.ontario.ca/page/public-accounts-2025-26-consolidated-financial-statements"

NS = {"psas": PSAS_NS, "on": ON_NS}
ELEMS = {"psas": PSAS_ELEMENTS, "on": ON_ELEMENTS}
DIM_ELEMS = ["StatementScenarioAxis", "ScenarioDomain", "ActualMember", "BudgetMember",
             "BudgetComparisonTable", "BudgetComparisonLineItems"]
ROLE = lambda r: f"{PSAS_NS}/role/{r}"
esc = lambda s: html.escape(s, quote=True)

# ------------------------------------------------------------------ parse source tables
soup = BeautifulSoup(open(SRC, encoding="utf-8").read(), "html.parser")
tables = soup.find_all("table")

def clean_label(s):
    s = re.sub(r"\s*footnote \d+ \[\d+\]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_num(s):
    s = s.strip().replace("−", "-")
    if s in ("–", "—", "-", ""):
        return None
    neg = s.startswith("(") and s.endswith(")")
    v = int(s.strip("()").replace(",", ""))
    return -v if neg else v

def prev_day(d):
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()

facts = []           # dicts: prefix, name, ctx, value, display, stmt, row, col
rendered = []        # per statement: caption, header cells, rows [(label, [cell html])]
problems = []

def ctx_id(kind, date_or_start, end, scen):
    base = ("D" + end[:4]) if kind == "D" else ("I" + end[:4])
    return base + ("_Budget" if scen else "")

contexts = {}        # id -> (kind, start, end, scen)

for st in STATEMENTS:
    t = tables[st["table"]]
    trs = t.find_all("tr")
    head = [c.get_text(" ", strip=True) for c in trs[0].find_all(["th", "td"])]
    data = trs[1:]
    if len(data) != len(st["rows"]):
        problems.append(f"{st['role']}: {len(data)} source rows vs {len(st['rows'])} mapped rows")
        continue
    out_rows = []
    for tr, rowspec in zip(data, st["rows"]):
        prefix, name, mode = rowspec[:3]
        prole = rowspec[3] if len(rowspec) > 3 else None
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        label = clean_label(cells[0])
        vals = cells[1:]
        cell_html = []
        for colkey, disp in zip(st["cols"], vals):
            kind, start, end, scen = COLUMNS[colkey]
            num = parse_num(disp)
            if num is None:
                cell_html.append(esc(disp))
                continue
            ptype = ELEMS[prefix][name][0]
            if ptype == "instant":
                if kind == "D":
                    inst = prev_day(start) if prole == "start" else end
                else:
                    inst = end
                cid = "I" + inst[:4] + ("_Budget" if scen else "")
                contexts[cid] = ("I", None, inst, scen)
            else:
                if kind != "D":
                    problems.append(f"duration element {name} in instant column")
                cid = ctx_id("D", start, end, scen)
                contexts[cid] = ("D", start, end, scen)
            value = num if mode == "disp" else -num
            fid = f"f{len(facts) + 1}"
            facts.append(dict(prefix=prefix, name=name, ctx=cid, value=value, stmt=st["role"], label=label, id=fid))
            digits = f"{abs(num):,}"
            sign = ' sign="-"' if value < 0 else ""
            tag = (f'<ix:nonFraction name="{prefix}:{name}" contextRef="{cid}" unitRef="CAD" decimals="-6" scale="6" '
                   f'format="ixt:num-dot-decimal"{sign} id="{fid}">{digits}</ix:nonFraction>')
            cell_html.append(f"({tag})" if num < 0 else tag)
        out_rows.append((label, cell_html, name))
    rendered.append(dict(role=st["role"], caption=clean_label(t.find("caption").get_text(" ", strip=True)),
                         head=[clean_label(h) for h in head], rows=out_rows))

# ------------------------------------------------------------------ consistency checks
by_key = defaultdict(set)
for f in facts:
    by_key[(f["prefix"], f["name"], f["ctx"])].add(f["value"])
for k, v in by_key.items():
    if len(v) > 1:
        problems.append(f"inconsistent duplicate fact {k}: {v}")
val = {k: next(iter(v)) for k, v in by_key.items()}
calc_checks = 0
for st in STATEMENTS:
    for (pp, pn), kids in st["calc"].items():
        for cid in {f["ctx"] for f in facts if f["stmt"] == st["role"]}:
            if (pp, pn, cid) not in val:
                continue
            got = [(val.get((cp, cn, cid)), w) for cp, cn, w in kids]
            if all(v is None for v, _ in got):
                continue
            total = sum(v * w for v, w in got if v is not None)
            calc_checks += 1
            if abs(total - val[(pp, pn, cid)]) > 1:   # rounding tolerance: 1 (million)
                problems.append(f"calc {st['role']} {pn} [{cid}]: children sum {total} vs reported {val[(pp, pn, cid)]}")

# ------------------------------------------------------------------ taxonomy writers
XSD_HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'
LB_HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'xmlns:xbrldt="http://xbrl.org/2005/xbrldt" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://www.xbrl.org/2003/linkbase http://www.xbrl.org/2003/xbrl-linkbase-2003-12-31.xsd">\n')

def element_xml(prefix, name, ptype, abstract=False, kind="monetary"):
    if kind == "monetary":
        return (f'  <xsd:element id="{prefix}_{name}" name="{name}" type="xbrli:monetaryItemType" '
                f'substitutionGroup="xbrli:item" xbrli:periodType="{ptype}" nillable="true"/>\n')
    if kind == "abstract":
        return (f'  <xsd:element id="{prefix}_{name}" name="{name}" type="xbrli:stringItemType" abstract="true" '
                f'substitutionGroup="xbrli:item" xbrli:periodType="duration" nillable="true"/>\n')
    if kind == "hypercube":
        return (f'  <xsd:element id="{prefix}_{name}" name="{name}" type="xbrli:stringItemType" abstract="true" '
                f'substitutionGroup="xbrldt:hypercubeItem" xbrli:periodType="duration" nillable="true"/>\n')
    if kind == "dimension":
        return (f'  <xsd:element id="{prefix}_{name}" name="{name}" type="xbrli:stringItemType" abstract="true" '
                f'substitutionGroup="xbrldt:dimensionItem" xbrli:periodType="duration" nillable="true"/>\n')

def abstract_name(role):
    return role + "Abstract"

def write_schema(path, prefix, ns, elements, extra, linkbases, imports, roles):
    x = [XSD_HEAD,
         f'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xbrli="http://www.xbrl.org/2003/instance" '
         f'xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink" '
         f'xmlns:xbrldt="http://xbrl.org/2005/xbrldt" xmlns:{prefix}="{ns}" '
         + "".join(f'xmlns:{p}="{n}" ' for p, n, _ in imports) +
         f'targetNamespace="{ns}" elementFormDefault="qualified" attributeFormDefault="unqualified">\n',
         '  <xsd:annotation><xsd:appinfo>\n']
    for lb, role in linkbases:
        x.append(f'    <link:linkbaseRef xlink:type="simple" xlink:href="{lb}" xlink:role="{role}" '
                 f'xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>\n')
    for r, title in roles:
        x.append(f'    <link:roleType roleURI="{ROLE(r)}" id="{r}">\n      <link:definition>{esc(title)}</link:definition>\n'
                 '      <link:usedOn>link:presentationLink</link:usedOn>\n      <link:usedOn>link:calculationLink</link:usedOn>\n'
                 '      <link:usedOn>link:definitionLink</link:usedOn>\n    </link:roleType>\n')
    x.append('  </xsd:appinfo></xsd:annotation>\n')
    x.append('  <xsd:import namespace="http://www.xbrl.org/2003/instance" schemaLocation="http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd"/>\n')
    x.append('  <xsd:import namespace="http://xbrl.org/2005/xbrldt" schemaLocation="http://www.xbrl.org/2005/xbrldt-2005.xsd"/>\n')
    for p, n, loc in imports:
        x.append(f'  <xsd:import namespace="{n}" schemaLocation="{loc}"/>\n')
    for name, (ptype, _, _) in elements.items():
        x.append(element_xml(prefix, name, ptype))
    x.extend(extra)
    x.append('</xsd:schema>\n')
    open(path, "w", encoding="utf-8").write("".join(x))

LAB_ROLES = {"label": "http://www.xbrl.org/2003/role/label",
             "doc": "http://www.xbrl.org/2003/role/documentation",
             "start": "http://www.xbrl.org/2003/role/periodStartLabel",
             "end": "http://www.xbrl.org/2003/role/periodEndLabel"}

def write_labels(path, xsdname, prefix, entries):
    """entries: name -> dict(label=..., doc=..., start=..., end=...)"""
    x = [LB_HEAD, '  <link:labelLink xlink:type="extended" xlink:role="http://www.xbrl.org/2003/role/link">\n']
    for name, labs in entries.items():
        x.append(f'    <link:loc xlink:type="locator" xlink:href="{xsdname}#{prefix}_{name}" xlink:label="loc_{name}"/>\n')
        for k, text in labs.items():
            if not text:
                continue
            x.append(f'    <link:label xlink:type="resource" xlink:label="lab_{name}_{k}" xlink:role="{LAB_ROLES[k]}" '
                     f'xml:lang="en">{esc(text)}</link:label>\n')
            x.append(f'    <link:labelArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/concept-label" '
                     f'xlink:from="loc_{name}" xlink:to="lab_{name}_{k}"/>\n')
    x.append('  </link:labelLink>\n</link:linkbase>\n')
    open(path, "w", encoding="utf-8").write("".join(x))

def href(prefix, name, here):
    """here: 'taxonomy' or 'ontario'"""
    if prefix == "psas":
        return ("psas-2026.xsd" if here == "taxonomy" else "../taxonomy/psas-2026.xsd") + f"#psas_{name}"
    return f"on-2026.xsd#on_{name}"

def role_refs(here, roles):
    loc = "psas-2026.xsd" if here == "taxonomy" else "../taxonomy/psas-2026.xsd"
    return "".join(f'  <link:roleRef roleURI="{ROLE(r)}" xlink:type="simple" xlink:href="{loc}#{r}"/>\n' for r in roles)

def keep(prefix, base):
    return not (base and prefix == "on")

def write_pre(path, here, base):
    x = [LB_HEAD, role_refs(here, [s["role"] for s in STATEMENTS])]
    for st in STATEMENTS:
        x.append(f'  <link:presentationLink xlink:type="extended" xlink:role="{ROLE(st["role"])}">\n')
        locs = set()
        def loc(p, n, suffix=""):
            # opening and closing balances of the same concept get separate locators, so no two arcs
            # share the same from/to pair (XLink duplicate-arc rule)
            lab = f"{p}_{n}{suffix}"
            if lab not in locs:
                locs.add(lab)
                x.append(f'    <link:loc xlink:type="locator" xlink:href="{href(p, n, here)}" xlink:label="{lab}"/>\n')
            return lab
        root = loc("psas", abstract_name(st["role"]))
        order = 0
        for rowspec in st["rows"]:
            p, n = rowspec[0], rowspec[1]
            prole = rowspec[3] if len(rowspec) > 3 else None
            if not keep(p, base):
                continue
            order += 1
            pl = f' preferredLabel="{LAB_ROLES[prole]}"' if prole else ""
            x.append(f'    <link:presentationArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/parent-child" '
                     f'xlink:from="{root}" xlink:to="{loc(p, n, "_" + prole if prole else "")}" order="{order}"{pl}/>\n')
        x.append('  </link:presentationLink>\n')
    x.append('</link:linkbase>\n')
    open(path, "w", encoding="utf-8").write("".join(x))

def write_cal(path, here, base):
    x = [LB_HEAD, role_refs(here, [s["role"] for s in STATEMENTS if s["calc"]])]
    for st in STATEMENTS:
        if not st["calc"]:
            continue
        x.append(f'  <link:calculationLink xlink:type="extended" xlink:role="{ROLE(st["role"])}">\n')
        locs = set()
        def loc(p, n):
            lab = f"{p}_{n}"
            if lab not in locs:
                locs.add(lab)
                x.append(f'    <link:loc xlink:type="locator" xlink:href="{href(p, n, here)}" xlink:label="{lab}"/>\n')
            return lab
        for (pp, pn), kids in st["calc"].items():
            for i, (cp, cn, w) in enumerate(kids, 1):
                if not keep(cp, base):
                    continue
                x.append(f'    <link:calculationArc xlink:type="arc" xlink:arcrole="http://www.xbrl.org/2003/arcrole/summation-item" '
                         f'xlink:from="{loc(pp, pn)}" xlink:to="{loc(cp, cn)}" order="{i}" weight="{w}.0"/>\n')
        x.append('  </link:calculationLink>\n')
    x.append('</link:linkbase>\n')
    open(path, "w", encoding="utf-8").write("".join(x))

def write_def(path, here, base):
    roles = [s["role"] for s in STATEMENTS if s["role"] in BUDGET_ROLES]
    x = [LB_HEAD, role_refs(here, roles),
         '  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/all" xlink:type="simple" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#all"/>\n'
         '  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/hypercube-dimension" xlink:type="simple" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#hypercube-dimension"/>\n'
         '  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/dimension-domain" xlink:type="simple" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#dimension-domain"/>\n'
         '  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/domain-member" xlink:type="simple" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#domain-member"/>\n'
         '  <link:arcroleRef arcroleURI="http://xbrl.org/int/dim/arcrole/dimension-default" xlink:type="simple" xlink:href="http://www.xbrl.org/2005/xbrldt-2005.xsd#dimension-default"/>\n']
    A = "http://xbrl.org/int/dim/arcrole/"
    for st in STATEMENTS:
        if st["role"] not in BUDGET_ROLES:
            continue
        x.append(f'  <link:definitionLink xlink:type="extended" xlink:role="{ROLE(st["role"])}">\n')
        locs = set()
        def loc(p, n):
            lab = f"{p}_{n}"
            if lab not in locs:
                locs.add(lab)
                x.append(f'    <link:loc xlink:type="locator" xlink:href="{href(p, n, here)}" xlink:label="{lab}"/>\n')
            return lab
        li, hc, ax = loc("psas", "BudgetComparisonLineItems"), loc("psas", "BudgetComparisonTable"), loc("psas", "StatementScenarioAxis")
        dom, act, bud = loc("psas", "ScenarioDomain"), loc("psas", "ActualMember"), loc("psas", "BudgetMember")
        x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}all" xlink:from="{li}" xlink:to="{hc}" xbrldt:contextElement="segment" xbrldt:closed="true" order="1"/>\n')
        x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}hypercube-dimension" xlink:from="{hc}" xlink:to="{ax}" order="1"/>\n')
        x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}dimension-domain" xlink:from="{ax}" xlink:to="{dom}" order="1"/>\n')
        x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}domain-member" xlink:from="{dom}" xlink:to="{act}" order="1"/>\n')
        x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}domain-member" xlink:from="{dom}" xlink:to="{bud}" order="2"/>\n')
        x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}dimension-default" xlink:from="{ax}" xlink:to="{act}" order="1"/>\n')
        seen = set()
        order = 0
        for rowspec in st["rows"]:
            p, n = rowspec[0], rowspec[1]
            if not keep(p, base) or (p, n) in seen:
                continue
            seen.add((p, n))
            order += 1
            x.append(f'    <link:definitionArc xlink:type="arc" xlink:arcrole="{A}domain-member" xlink:from="{li}" xlink:to="{loc(p, n)}" order="{order}"/>\n')
        x.append('  </link:definitionLink>\n')
    x.append('</link:linkbase>\n')
    open(path, "w", encoding="utf-8").write("".join(x))

LB_ROLE = {"lab": "http://www.xbrl.org/2003/role/labelLinkbaseRef", "pre": "http://www.xbrl.org/2003/role/presentationLinkbaseRef",
           "cal": "http://www.xbrl.org/2003/role/calculationLinkbaseRef", "def": "http://www.xbrl.org/2003/role/definitionLinkbaseRef"}

# --- base taxonomy schema (elements + labels only; relationships live in entry point / extensions)
extra = [element_xml("psas", abstract_name(s["role"]), None, kind="abstract") for s in STATEMENTS]
extra += [element_xml("psas", "BudgetComparisonTable", None, kind="hypercube"),
          element_xml("psas", "StatementScenarioAxis", None, kind="dimension"),
          element_xml("psas", "BudgetComparisonLineItems", None, kind="abstract"),
          element_xml("psas", "ScenarioDomain", None, kind="abstract"),
          element_xml("psas", "ActualMember", None, kind="abstract"),
          element_xml("psas", "BudgetMember", None, kind="abstract")]
write_schema(os.path.join(TAX, "psas-2026.xsd"), "psas", PSAS_NS, PSAS_ELEMENTS, extra,
             [("psas-2026-lab.xml", LB_ROLE["lab"])], [], [(s["role"], s["title"]) for s in STATEMENTS])

used_start_end = defaultdict(set)
for st in STATEMENTS:
    for r in st["rows"]:
        if len(r) > 3:
            used_start_end[(r[0], r[1])].add(r[3])

def label_entries(prefix, elements):
    out = {}
    for n, (pt, lab, doc) in elements.items():
        e = dict(label=lab, doc=doc)
        if "start" in used_start_end.get((prefix, n), ()):
            e["start"] = lab + ", beginning of period"
        if "end" in used_start_end.get((prefix, n), ()):
            e["end"] = lab + ", end of period"
        out[n] = e
    return out

psas_labels = label_entries("psas", PSAS_ELEMENTS)
for s in STATEMENTS:
    psas_labels[abstract_name(s["role"])] = dict(label=s["title"] + " [Abstract]")
psas_labels.update({
    "BudgetComparisonTable": dict(label="Budget comparison [Table]"),
    "StatementScenarioAxis": dict(label="Statement scenario [Axis]", doc="Distinguishes budget amounts (PS 1201 requires budget comparison) from actual results."),
    "BudgetComparisonLineItems": dict(label="Budget comparison [Line Items]"),
    "ScenarioDomain": dict(label="Scenario [Domain]"),
    "ActualMember": dict(label="Actual [Member]", doc="Default member: actual results."),
    "BudgetMember": dict(label="Budget [Member]", doc="Amounts from the original budget presented for comparison."),
})
write_labels(os.path.join(TAX, "psas-2026-lab.xml"), "psas-2026.xsd", "psas", psas_labels)

# --- base entry point with generic (non-Ontario) relationships
write_pre(os.path.join(TAX, "psas-2026-pre.xml"), "taxonomy", True)
write_cal(os.path.join(TAX, "psas-2026-cal.xml"), "taxonomy", True)
write_def(os.path.join(TAX, "psas-2026-def.xml"), "taxonomy", True)
open(os.path.join(TAX, "psas-2026-entry-all.xsd"), "w", encoding="utf-8").write(
    XSD_HEAD +
    f'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:link="http://www.xbrl.org/2003/linkbase" '
    f'xmlns:xlink="http://www.w3.org/1999/xlink" targetNamespace="{PSAS_NS}/entry-all" elementFormDefault="qualified">\n'
    '  <xsd:annotation><xsd:appinfo>\n' +
    "".join(f'    <link:linkbaseRef xlink:type="simple" xlink:href="psas-2026-{k}.xml" xlink:role="{LB_ROLE[k]}" '
            f'xlink:arcrole="http://www.w3.org/1999/xlink/properties/linkbase"/>\n' for k in ("pre", "cal", "def")) +
    '  </xsd:appinfo></xsd:annotation>\n'
    f'  <xsd:import namespace="{PSAS_NS}" schemaLocation="psas-2026.xsd"/>\n</xsd:schema>\n')

# --- Ontario extension
write_schema(os.path.join(ONT, "on-2026.xsd"), "on", ON_NS, ON_ELEMENTS, [],
             [(f"on-2026-{k}.xml", LB_ROLE[k]) for k in ("lab", "pre", "cal", "def")],
             [("psas", PSAS_NS, "../taxonomy/psas-2026.xsd")], [])
write_labels(os.path.join(ONT, "on-2026-lab.xml"), "on-2026.xsd", "on", label_entries("on", ON_ELEMENTS))
write_pre(os.path.join(ONT, "on-2026-pre.xml"), "ontario", False)
write_cal(os.path.join(ONT, "on-2026-cal.xml"), "ontario", False)
write_def(os.path.join(ONT, "on-2026-def.xml"), "ontario", False)

# ------------------------------------------------------------------ Inline XBRL document
ctx_xml = []
for cid, (kind, start, end, scen) in sorted(contexts.items()):
    seg = ('<xbrli:segment><xbrldi:explicitMember dimension="psas:StatementScenarioAxis">psas:BudgetMember'
           '</xbrldi:explicitMember></xbrli:segment>') if scen else ""
    period = (f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>" if kind == "D"
              else f"<xbrli:instant>{end}</xbrli:instant>")
    ctx_xml.append(f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000074615'
                   f'</xbrli:identifier>{seg}</xbrli:entity><xbrli:period>{period}</xbrli:period></xbrli:context>')

CSS = """
:root { --fg:#1b1b1b; --muted:#5c5c5c; --rule:#d0d0d0; --bg:#ffffff; --band:#f4f6f8; --tag:#e8f0fe; }
body { font-family: Georgia, 'Times New Roman', serif; color: var(--fg); background: var(--bg); max-width: 980px; margin: 0 auto; padding: 24px 16px 64px; line-height: 1.45; }
h1 { font-size: 1.6rem; margin-bottom: 0.2rem; } h2 { font-size: 1.15rem; margin-top: 2.4rem; }
.note { color: var(--muted); font-size: 0.92rem; border-left: 3px solid var(--rule); padding-left: 12px; }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; font-variant-numeric: tabular-nums; }
th, td { padding: 4px 8px; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { text-align: right; background: var(--band); font-weight: 600; } th:first-child, td:first-child { text-align: left; }
td.n { text-align: right; white-space: nowrap; }
tr.total td { font-weight: 700; border-top: 2px solid var(--fg); }
ix\\:nonFraction, .ix { background: var(--tag); }
"""
TOTAL_HINTS = ("Total", "Annual Deficit", "Net Debt", "Accumulated Deficit", "Cash (Applied", "Cash Applied", "Cash Provided",
               "Increase in Net Debt", "Net Remeasurement", "at End of Year", "Net Decrease")
body = []
for r in rendered:
    body.append(f'<h2>{esc(r["caption"])}</h2>\n<div class="wrap"><table>\n<tr>' +
                "".join(f"<th>{esc(h)}</th>" for h in r["head"]) + "</tr>\n")
    shown_groups = set()
    for label, cells, name in r["rows"]:
        parts = label.split(" – ")
        # print group headings (e.g. "Revenue", "Operating Transactions", "Non-Cash Items") once, then indent
        for depth, grp in enumerate(parts[:-1]):
            key = tuple(parts[:depth + 1])
            if key not in shown_groups:
                shown_groups.add(key)
                body.append(f'<tr><td style="padding-left:{8 + 18 * depth}px;font-style:italic">{esc(grp)}</td>' +
                            '<td></td>' * len(cells) + "</tr>\n")
        last = parts[-1]
        cls = ' class="total"' if last.startswith(TOTAL_HINTS) else ""
        pad = 8 + 18 * (len(parts) - 1)
        body.append(f'<tr{cls}><td style="padding-left:{pad}px">{esc(last)}</td>' +
                    "".join(f'<td class="n">{c}</td>' for c in cells) + "</tr>\n")
    body.append("</table></div>\n")

doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12" xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:link="http://www.xbrl.org/2003/linkbase" xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217" xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:psas="{PSAS_NS}" xmlns:on="{ON_NS}">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>Ontario Public Accounts 2025-26: Tagged Statements (Pilot)</title>
<style type="text/css">{CSS}</style>
</head>
<body>
<div style="display:none">
<ix:header>
<ix:references><link:schemaRef xlink:type="simple" xlink:href="on-2026.xsd"/></ix:references>
<ix:resources>
{chr(10).join(ctx_xml)}
<xbrli:unit id="CAD"><xbrli:measure>iso4217:CAD</xbrli:measure></xbrli:unit>
</ix:resources>
</ix:header>
</div>
<h1>Province of Ontario: Consolidated Financial Statements, 2025&#8211;26</h1>
<p class="note">Unofficial pilot. The primary statements are reproduced from the Province's published
<a href="{SOURCE_URL}">Public Accounts 2025&#8211;26 consolidated financial statements</a> and tagged in Inline XBRL with a
draft Canadian PSAS taxonomy. This is not a filing by the Province of Ontario. Amounts are in millions of Canadian dollars.
Notes, schedules and the auditor's report are not reproduced.</p>
{"".join(body)}
</body>
</html>
"""
open(os.path.join(ONT, "ontario-2026-ixbrl.xhtml"), "w", encoding="utf-8").write(doc)

# ------------------------------------------------------------------ report
print(f"facts: {len(facts)}  unique: {len(val)}  contexts: {len(contexts)}  calc checks: {calc_checks}")
print(f"elements: psas {len(PSAS_ELEMENTS)} + on {len(ON_ELEMENTS)}")
for r in rendered:
    for label, cells, name in r["rows"]:
        print(f"  {r['role'][:22]:22} | {label[:60]:60} -> {name}")
print("PROBLEMS:" if problems else "No problems found.")
for p in problems:
    print("  ", p)
