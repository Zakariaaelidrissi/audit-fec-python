import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA, RES = BASE / "data", BASE / "resultats"
GRAPH = RES / "graphiques"

POIDS = {"FOURNISSEUR_FICTIF": 5, "DOUBLON": 4, "PAIEMENT_SANS_FACTURE": 4, "POST_CLOTURE": 4, "DESEQUILIBRE": 3,
         "SOUS_SEUIL": 3, "LIBELLE_SUSPECT": 2, "MONTANT_ROND": 2, "WEEKEND_FERIE": 2}
LIBELLES = {"FOURNISSEUR_FICTIF": "Fournisseur atypique", "DOUBLON": "Doublon", "PAIEMENT_SANS_FACTURE": "Paiement sans facture",
            "POST_CLOTURE": "Validation tardive", "DESEQUILIBRE": "Écriture déséquilibrée", "SOUS_SEUIL": "Juste sous le seuil",
            "LIBELLE_SUSPECT": "Libellé suspect", "MONTANT_ROND": "Montant rond", "WEEKEND_FERIE": "Week-end / férié"}
TAUX_SIGNIFICATION, TAUX_PLANIFICATION, TAUX_INSIGNIFIANT = 0.01, 0.75, 0.05
NIVEAUX = [(6, "Élevé"), (4, "Moyen"), (0, "Faible")]
MOIS = ["Janv.", "Févr.", "Mars", "Avr.", "Mai", "Juin", "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc."]
BLEU, ORANGE, ENCRE, GRIS = "#2a78d6", "#eb6834", "#3d3d3a", "#d9d9d6"

fichier = next(DATA.glob("*FEC*.txt"), None)
conf, drap = RES / "01_conformite.xlsx", RES / "drapeaux_tests.csv"
for f, script in ((fichier, "generer_donnees.py"), (conf, "controles_conformite.py"), (drap, "tests_audit.py")):
    if f is None or not Path(f).exists():
        sys.exit(f"Fichier manquant : lance d'abord {script}")

fec = pd.read_csv(fichier, sep="\t", dtype=str, keep_default_na=False, encoding="utf-8")
for c in ("Debit", "Credit"):
    fec[c] = pd.to_numeric(fec[c].str.replace(",", ".", regex=False), errors="coerce").fillna(0)
fec["EcritureDate"] = pd.to_datetime(fec["EcritureDate"], format="%Y%m%d", errors="coerce")
fec = fec[fec["JournalCode"].ne("AN")]

ventes = fec[fec["CompteNum"].str.startswith("70")]
ca = ventes["Credit"].sum() - ventes["Debit"].sum()
seuil = round(ca * TAUX_SIGNIFICATION, -2)
planif, insignifiant = round(seuil * TAUX_PLANIFICATION, -2), round(seuil * TAUX_INSIGNIFIANT, -1)

ecr = (fec.groupby(["JournalCode", "EcritureNum"], sort=False)
       .agg(Date=("EcritureDate", "first"), PieceRef=("PieceRef", "first"), Libelle=("EcritureLib", "first"), Montant=("Debit", "sum"))
       .reset_index())
tiers = fec[fec["CompAuxLib"].ne("")].groupby("EcritureNum")["CompAuxLib"].first()
ecr["Tiers"] = ecr["EcritureNum"].map(tiers).fillna("")
ecr["Montant"] = ecr["Montant"].round(2)

c07 = pd.read_excel(conf, sheet_name="C07 Équilibre des écritures", dtype=str)
c09 = pd.read_excel(conf, sheet_name="C09 Numérotation continue", dtype=str)
deseq = c07["EcritureNum"].dropna() if "EcritureNum" in c07 else pd.Series(dtype=str)
manquants = c09["NumeroManquant"].dropna() if "NumeroManquant" in c09 else pd.Series(dtype=str)

flags = pd.concat([pd.read_csv(drap, sep=";", dtype=str, encoding="utf-8-sig"),
                   pd.DataFrame({"EcritureNum": deseq, "Test": "DESEQUILIBRE"})], ignore_index=True).drop_duplicates()
flags["Points"] = flags["Test"].map(POIDS).fillna(1)

par_ecr = flags.groupby("EcritureNum").agg(PointsTests=("Points", "sum"), NbTests=("Test", "size"),
                                            Tests=("Test", lambda s: ", ".join(LIBELLES.get(t, t) for t in sorted(s, key=lambda t: -POIDS.get(t, 1)))))
risque = ecr.merge(par_ecr, left_on="EcritureNum", right_index=True)
risque["PointsMontant"] = np.select([risque["Montant"] >= planif, risque["Montant"] >= insignifiant], [2, 1], 0)
risque["Score"] = (risque["PointsTests"] + risque["PointsMontant"]).astype(int)
risque["Niveau"] = np.select([risque["Score"] >= s for s, _ in NIVEAUX[:-1]], [n for _, n in NIVEAUX[:-1]], NIVEAUX[-1][1])
risque = risque.sort_values(["Score", "Montant"], ascending=False).reset_index(drop=True)
risque.insert(0, "Rang", risque.index + 1)

gt_path = DATA / "anomalies_injectees.csv"
perf = None
if gt_path.exists():
    gt = pd.read_csv(gt_path, sep=";", dtype=str, encoding="utf-8-sig")
    attendues = set(gt.loc[gt["Anomalie"].ne("RUPTURE_SEQUENCE"), "EcritureNum"])
    trous = set(gt.loc[gt["Anomalie"].eq("RUPTURE_SEQUENCE"), "EcritureNum"])
    signalees = set(risque["EcritureNum"])
    vp = len(attendues & signalees)
    perf = {"precision": vp / len(signalees), "rappel": vp / len(attendues), "vp": vp, "attendues": len(attendues),
            "signalees": len(signalees), "trous": len(trous & set(manquants)), "trous_total": len(trous)}

par_test = (flags.merge(ecr[["EcritureNum", "Montant"]], on="EcritureNum")
            .groupby("Test").agg(Ecritures=("EcritureNum", "nunique"), Montant=("Montant", "sum")).reset_index())
par_test["Poids"] = par_test["Test"].map(POIDS)
par_test["Test"] = par_test["Test"].map(LIBELLES)
par_test = par_test.sort_values("Ecritures", ascending=False)
par_niveau = (risque.groupby("Niveau").agg(Ecritures=("EcritureNum", "size"), Montant=("Montant", "sum"))
              .reindex([n for _, n in NIVEAUX]).fillna(0).reset_index())
par_mois = (risque.groupby(risque["Date"].dt.month).agg(Ecritures=("EcritureNum", "size"), Montant=("Montant", "sum"))
            .reindex(range(1, 13), fill_value=0))

kpi = [("Écritures analysées (hors à-nouveaux)", len(ecr)), ("Montant total des écritures", round(ecr["Montant"].sum(), 2)),
       ("Écritures signalées", len(risque)), ("Part des écritures signalées", len(risque) / len(ecr)),
       ("Montant des écritures signalées", round(risque["Montant"].sum(), 2)),
       ("Écritures à risque élevé", int((risque["Niveau"] == "Élevé").sum())),
       ("Numéros d'écriture manquants", len(manquants)),
       ("Chiffre d'affaires HT", round(ca, 2)), ("Seuil de signification (1 % du CA)", seuil),
       ("Seuil de planification (75 %)", planif), ("Seuil des anomalies insignifiantes (5 %)", insignifiant)]
if perf:
    kpi += [("Précision (alertes justifiées)", perf["precision"]), ("Rappel (anomalies retrouvées)", perf["rappel"])]

methodo = pd.DataFrame([(LIBELLES[t], p) for t, p in POIDS.items()], columns=["Test", "Points"])
methodo = pd.concat([methodo, pd.DataFrame([(f"Montant ≥ seuil des anomalies insignifiantes ({insignifiant:,.0f} €)".replace(",", " "), 1),
                                            (f"Montant ≥ seuil de planification ({planif:,.0f} €)".replace(",", " "), 2)], columns=["Test", "Points"])])

GRAPH.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRIS, "axes.labelcolor": ENCRE,
                     "xtick.color": ENCRE, "ytick.color": ENCRE, "text.color": ENCRE, "axes.spines.top": False, "axes.spines.right": False})


def finir(fig, ax, nom, titre):
    ax.set_title(titre, loc="left", fontsize=12, fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(GRAPH / nom, dpi=160, facecolor="white")
    plt.close(fig)


d = par_test.sort_values("Ecritures")
fig, ax = plt.subplots(figsize=(8, 4.2))
ax.barh(d["Test"], d["Ecritures"], color=BLEU, height=0.6)
for y, v in enumerate(d["Ecritures"]):
    ax.text(v + 0.2, y, str(v), va="center", fontsize=9)
ax.xaxis.grid(True, color=GRIS, linewidth=0.6)
ax.set_axisbelow(True)
ax.spines["left"].set_visible(False)
ax.tick_params(axis="y", length=0)
ax.set_xlabel("Nombre d'écritures signalées")
finir(fig, ax, "anomalies_par_test.png", "Écritures signalées par test d'audit")

fig, ax = plt.subplots(figsize=(8, 3.8))
ax.bar(MOIS, par_mois["Montant"] / 1000, color=BLEU, width=0.6)
ax.yaxis.grid(True, color=GRIS, linewidth=0.6)
ax.set_axisbelow(True)
ax.set_ylabel("k€")
finir(fig, ax, "risque_par_mois.png", "Montant des écritures signalées par mois")

montants = fec[["Debit", "Credit"]].max(axis=1)
montants = montants[montants >= 10]
p1 = montants.astype(str).str[0].astype(int).value_counts(normalize=True).reindex(range(1, 10), fill_value=0)
att = np.log10(1 + 1 / np.arange(1, 10))
mad = np.abs(p1.values - att).mean()
fig, ax = plt.subplots(figsize=(8, 3.8))
ax.bar(range(1, 10), p1.values, color=BLEU, width=0.6, label="Observé")
ax.plot(range(1, 10), att, color=ORANGE, linewidth=2, marker="o", markersize=6, label="Attendu (loi de Benford)")
ax.set_xticks(range(1, 10))
ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1, decimals=0))
ax.yaxis.grid(True, color=GRIS, linewidth=0.6)
ax.set_axisbelow(True)
ax.set_xlabel("Premier chiffre du montant")
ax.legend(frameon=False, loc="upper right")
ax.text(0.99, 0.62, f"MAD = {mad:.4f}", transform=ax.transAxes, ha="right", fontsize=9)
finir(fig, ax, "benford.png", f"Loi de Benford sur {len(montants):,} montants".replace(",", " "))

sortie = RES / "03_rapport_audit.xlsx"
try:
    with pd.ExcelWriter(sortie, engine="xlsxwriter", datetime_format="dd/mm/yyyy") as w:
        wb = w.book
        entete = wb.add_format({"bold": True, "font_color": "white", "bg_color": "#1F3864", "border": 1})
        grand = wb.add_format({"bold": True, "font_size": 16, "font_color": "#1F3864"})
        gras = wb.add_format({"bold": True})
        euro = wb.add_format({"num_format": "#,##0.00 €"})
        euro_g = wb.add_format({"num_format": "#,##0 €", "bold": True})
        pct_g = wb.add_format({"num_format": "0.0%", "bold": True})
        ent_g = wb.add_format({"num_format": "#,##0", "bold": True})
        couleurs = {"Élevé": ("#FFC7CE", "#9C0006"), "Moyen": ("#FFEB9C", "#9C5700"), "Faible": ("#C6EFCE", "#006100")}

        ws = wb.add_worksheet("Tableau de bord")
        w.sheets["Tableau de bord"] = ws
        ws.write(0, 0, "Audit du FEC 2025 - analyse des écritures (données fictives)", grand)
        ws.set_column(0, 0, 44)
        ws.set_column(1, 1, 18)
        ws.set_column(3, 3, 26)
        ws.set_column(4, 6, 14)
        for i, (lib, val) in enumerate(kpi, start=2):
            ws.write(i, 0, lib)
            fmt = pct_g if isinstance(val, float) and val <= 1 else euro_g if isinstance(val, float) or "Seuil" in lib else ent_g
            ws.write(i, 1, val, fmt)
        r0 = 2
        for j, c in enumerate(["Test", "Écritures", "Montant", "Points"]):
            ws.write(r0, 3 + j, c, entete)
        for i, row in enumerate(par_test.itertuples(index=False), start=r0 + 1):
            ws.write(i, 3, row.Test)
            ws.write(i, 4, row.Ecritures)
            ws.write(i, 5, row.Montant, euro)
            ws.write(i, 6, row.Poids)
        r1 = r0 + len(par_test) + 2
        for j, c in enumerate(["Niveau de risque", "Écritures", "Montant"]):
            ws.write(r1, 3 + j, c, entete)
        for i, row in enumerate(par_niveau.itertuples(index=False), start=r1 + 1):
            fond, texte = couleurs[row.Niveau]
            ws.write(i, 3, row.Niveau, wb.add_format({"bg_color": fond, "font_color": texte, "bold": True}))
            ws.write(i, 4, int(row.Ecritures))
            ws.write(i, 5, row.Montant, euro)

        g1 = wb.add_chart({"type": "bar"})
        g1.add_series({"name": "Écritures signalées", "categories": ["Tableau de bord", r0 + 1, 3, r0 + len(par_test), 3],
                       "values": ["Tableau de bord", r0 + 1, 4, r0 + len(par_test), 4], "fill": {"color": BLEU}, "gap": 60,
                       "data_labels": {"value": True}})
        g1.set_title({"name": "Écritures signalées par test"})
        g1.set_legend({"none": True})
        g1.set_y_axis({"reverse": True, "interval_unit": 1, "num_font": {"size": 9}})
        g1.set_x_axis({"major_gridlines": {"visible": True, "line": {"color": GRIS}}})
        g1.set_size({"width": 500, "height": 380})
        ws.insert_chart(r1 + 6, 0, g1)

        rm = r1 + 6
        ws.write(rm, 11, "Mois", entete)
        ws.write(rm, 12, "Montant signalé", entete)
        for i, (m, v) in enumerate(zip(MOIS, par_mois["Montant"]), start=rm + 1):
            ws.write(i, 11, m)
            ws.write(i, 12, v, euro)
        ws.set_column(11, 11, 8)
        ws.set_column(12, 12, 16)
        g2 = wb.add_chart({"type": "column"})
        g2.add_series({"name": "Montant signalé", "categories": ["Tableau de bord", rm + 1, 11, rm + 12, 11],
                       "values": ["Tableau de bord", rm + 1, 12, rm + 12, 12], "fill": {"color": BLEU}, "gap": 60})
        g2.set_title({"name": "Montant des écritures signalées par mois"})
        g2.set_legend({"none": True})
        g2.set_y_axis({"num_format": "#,##0 €", "major_gridlines": {"visible": True, "line": {"color": GRIS}}})
        g2.set_size({"width": 560, "height": 340})
        ws.insert_chart(rm, 4, g2)

        cols = ["Rang", "Score", "Niveau", "Tests", "JournalCode", "EcritureNum", "Date", "PieceRef", "Libelle", "Tiers", "Montant"]
        risque[cols].to_excel(w, sheet_name="Écritures à risque", index=False)
        ws = w.sheets["Écritures à risque"]
        for i, c in enumerate(cols):
            ws.write(0, i, c, entete)
            larg = max([len(str(c))] + [len(str(x)) for x in risque[c].head(300)])
            ws.set_column(i, i, min(max(larg + 2, 8), 60), euro if c == "Montant" else None)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, len(risque), len(cols) - 1)
        for niv, (fond, texte) in couleurs.items():
            ws.conditional_format(1, 2, len(risque), 2, {"type": "cell", "criteria": "==", "value": f'"{niv}"',
                                                         "format": wb.add_format({"bg_color": fond, "font_color": texte, "bold": True})})
        ws.conditional_format(1, 1, len(risque), 1, {"type": "data_bar", "bar_color": BLEU, "bar_solid": True})

        methodo.to_excel(w, sheet_name="Méthodologie", index=False, startrow=2)
        ws = w.sheets["Méthodologie"]
        ws.write(0, 0, "Score de risque = points des tests déclenchés + points liés au montant", gras)
        for i, c in enumerate(methodo.columns):
            ws.write(2, i, c, entete)
        ws.set_column(0, 0, 62)
        ws.set_column(1, 1, 10)
        r = len(methodo) + 4
        ws.write(r, 0, "Niveaux : Élevé ≥ 6 points | Moyen 4 à 5 points | Faible < 4 points", gras)
        ws.write(r + 1, 0, "Seuil de signification : 1 % du chiffre d'affaires HT ; planification : 75 % ; anomalies insignifiantes : 5 %.")
except PermissionError:
    sys.exit(f"Impossible d'écrire {sortie.name} : ferme le fichier dans Excel puis relance.")

print(f"\nScore de risque : {len(risque)} écritures signalées sur {len(ecr):,}".replace(",", " "))
print(f"Seuil de signification : {seuil:,.0f} € (1 % du CA de {ca:,.0f} €)".replace(",", " "))
print("\nRépartition par niveau de risque :")
for row in par_niveau.itertuples(index=False):
    print(f"  {row.Niveau:<8}{int(row.Ecritures):>5} écritures {row.Montant:>14,.2f} €".replace(",", " "))
print("\nTop 5 des écritures les plus risquées :")
for row in risque.head(5).itertuples(index=False):
    print(f"  {row.Rang}. {row.EcritureNum}  score {row.Score:>2}  {row.Montant:>10,.2f} €  {row.Tests}".replace(",", " "))
if perf:
    print(f"\nPerformance par rapport au corrigé :")
    print(f"  Rappel    : {perf['rappel']:.1%} ({perf['vp']}/{perf['attendues']} écritures anormales retrouvées)")
    print(f"  Précision : {perf['precision']:.1%} ({perf['vp']}/{perf['signalees']} alertes justifiées)")
    print(f"  Trous de numérotation : {perf['trous']}/{perf['trous_total']}")
print(f"\nRapport Excel : {sortie}")
print(f"Graphiques    : {GRAPH}")
