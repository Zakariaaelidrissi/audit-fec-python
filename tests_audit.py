import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, timedelta
from scipy.stats import chisquare

BASE = Path(__file__).resolve().parent
DATA, RES = BASE / "data", BASE / "resultats"
SEUIL = 10_000
MARGE_SEUIL = 0.05
DELAI_VALIDATION = 30
MAX_FACTURES_FOURNISSEUR = 3
DELAI_PAIEMENT_IMMEDIAT = 2
MOTS_SUSPECTS = r"divers|ajustement|à voir|a voir|correction|écart|ecart|annule et remplace|à justifier|a justifier|inexpliqu|erreur|provisoire"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def paques(a):
    b, c = divmod(a, 100)
    d = (19 * (a % 19) + b - b // 4 - (b - (b + 8) // 25 + 1) // 3 + 15) % 30
    e = (32 + 2 * (b % 4) + 2 * (c // 4) - d - c % 4) % 7
    f = (a % 19 + 11 * d + 22 * e) // 451
    m, j = divmod(d + e - 7 * f + 114, 31)
    return date(a, m, j + 1)


def feries(a):
    p = paques(a)
    return {date(a, 1, 1), p + timedelta(1), date(a, 5, 1), date(a, 5, 8), p + timedelta(39), p + timedelta(50),
            date(a, 7, 14), date(a, 8, 15), date(a, 11, 1), date(a, 11, 11), date(a, 12, 25)}


fichier = next(DATA.glob("*FEC*.txt"), None)
if fichier is None:
    sys.exit("Aucun FEC dans le dossier data : lance d'abord generer_donnees.py")

fec = pd.read_csv(fichier, sep="\t", dtype=str, keep_default_na=False, encoding="utf-8")
for c in ("Debit", "Credit"):
    fec[c] = pd.to_numeric(fec[c].str.replace(",", ".", regex=False), errors="coerce").fillna(0)
for c in ("EcritureDate", "ValidDate", "DateLet"):
    fec[c] = pd.to_datetime(fec[c], format="%Y%m%d", errors="coerce")
fec = fec[fec["JournalCode"].ne("AN")]

ecr = (fec.groupby(["JournalCode", "EcritureNum"], sort=False)
       .agg(Date=("EcritureDate", "first"), Validation=("ValidDate", "first"), PieceRef=("PieceRef", "first"),
            Libelle=("EcritureLib", "first"), Montant=("Debit", "sum")).reset_index())
tiers = fec[fec["CompAuxLib"].ne("")].groupby("EcritureNum")["CompAuxLib"].first()
ecr["Tiers"] = ecr["EcritureNum"].map(tiers).fillna("")
ecr["Montant"] = ecr["Montant"].round(2)
VUE = ["JournalCode", "EcritureNum", "Date", "PieceRef", "Libelle", "Tiers", "Montant"]

fournisseurs = fec[fec["CompteNum"].str.startswith("401")]
factures = (fournisseurs[fournisseurs["Credit"] > 0].groupby("EcritureNum")
            .agg(Fournisseur=("CompAuxNum", "first"), Nom=("CompAuxLib", "first"), Date=("EcritureDate", "first"),
                 TTC=("Credit", "sum"), Paiement=("DateLet", "first")).reset_index())
factures["DelaiPaiement"] = (factures["Paiement"] - factures["Date"]).dt.days

tests, feuilles = [], {}


def signaler(code, titre, description, nums, details):
    tests.append({"code": code, "titre": titre, "description": description, "nums": set(nums)})
    feuilles[titre] = details.reset_index(drop=True)


fer = set().union(*(feries(int(a)) for a in ecr["Date"].dt.year.dropna().unique()))
ferie = ecr["Date"].dt.date.isin(fer)
m = (ecr["Date"].dt.weekday >= 5) | ferie
d = ecr.loc[m, VUE].assign(Jour=np.where(ferie[m], "jour férié", ecr.loc[m, "Date"].dt.weekday.map(dict(enumerate(JOURS)))))
signaler("WEEKEND_FERIE", "T1 Week-end et fériés", "Écritures datées un samedi, un dimanche ou un jour férié", d["EcritureNum"], d)

centimes = (ecr["Montant"] * 100).round().astype("int64")
m = ecr["Montant"].ge(1000) & centimes.mod(100_000).eq(0)
d = ecr.loc[m, VUE]
signaler("MONTANT_ROND", "T2 Montants ronds", "Écritures dont le montant est un multiple exact de 1 000 €", d["EcritureNum"], d)

lettre = fournisseurs["EcritureLet"].ne("")
origine = fournisseurs[lettre & fournisseurs["Credit"].gt(0)].groupby(["CompAuxNum", "EcritureLet"])["EcritureDate"].first()
regl = fournisseurs[lettre & fournisseurs["Debit"].gt(0)]
date_facture = pd.Series(origine.reindex(pd.MultiIndex.from_frame(regl[["CompAuxNum", "EcritureLet"]])).values, index=regl["EcritureNum"].values)
ecr["DateOrigine"] = ecr["EcritureNum"].map(date_facture[~date_facture.index.duplicated()]).fillna(ecr["Date"])

cle = ["JournalCode", "PieceRef", "Tiers", "Montant"]
base = ecr[ecr["Tiers"].ne("")].sort_values(["DateOrigine", "Date", "EcritureNum"])
dbl = base.duplicated(cle, keep="first")
d = base[base.duplicated(cle, keep=False)].assign(Statut=np.where(dbl[base.duplicated(cle, keep=False)], "DOUBLON", "Original"))
d = d.sort_values(cle + ["Date"])[VUE + ["Statut"]]
signaler("DOUBLON", "T3 Doublons", "Même journal, même pièce, même tiers et même montant (l'original n'est pas compté)",
         base.loc[dbl, "EcritureNum"], d)

m = factures["TTC"].ge(SEUIL * (1 - MARGE_SEUIL)) & factures["TTC"].lt(SEUIL)
d = factures[m].copy()
d["ProchesSeuilFournisseur"] = d.groupby("Fournisseur")["EcritureNum"].transform("size")
d = d.sort_values(["Fournisseur", "Date"])
signaler("SOUS_SEUIL", "T4 Juste sous le seuil", f"Factures entre {SEUIL * (1 - MARGE_SEUIL):,.0f} et {SEUIL:,.0f} € TTC (seuil d'autorisation)".replace(",", " "),
         d["EcritureNum"], d)

ecart = (ecr["Validation"] - ecr["Date"]).dt.days
m = ecart > DELAI_VALIDATION
d = ecr.loc[m, VUE + ["Validation"]].assign(JoursAvantValidation=ecart[m])
signaler("POST_CLOTURE", "T5 Validation tardive", f"Écritures validées plus de {DELAI_VALIDATION} jours après leur date (risque de cut-off)",
         d["EcritureNum"], d)

m = ecr["Libelle"].str.contains(MOTS_SUSPECTS, case=False, regex=True)
d = ecr.loc[m, VUE]
signaler("LIBELLE_SUSPECT", "T6 Libellés suspects", "Libellés vagues ou non justifiés (divers, ajustement, à justifier…)", d["EcritureNum"], d)

pf = factures.groupby(["Fournisseur", "Nom"]).agg(NbFactures=("EcritureNum", "size"), TotalTTC=("TTC", "sum"),
                                                  PaiementsImmediats=("DelaiPaiement", lambda s: int((s <= DELAI_PAIEMENT_IMMEDIAT).sum()))).reset_index()
susp = pf[pf["NbFactures"].le(MAX_FACTURES_FOURNISSEUR) & pf["PaiementsImmediats"].ge(1)]
nums = fournisseurs.loc[fournisseurs["CompAuxNum"].isin(susp["Fournisseur"]), "EcritureNum"].unique()
d = ecr[ecr["EcritureNum"].isin(nums)][VUE].sort_values(["Tiers", "Date"])
signaler("FOURNISSEUR_FICTIF", "T7 Fournisseurs atypiques",
         f"Fournisseurs avec {MAX_FACTURES_FOURNISSEUR} factures ou moins, payées en {DELAI_PAIEMENT_IMMEDIAT} jours ou moins", nums, d)

m = fournisseurs["Debit"].gt(0) & fournisseurs["EcritureLet"].eq("")
nums = fournisseurs.loc[m, "EcritureNum"].unique()
d = ecr[ecr["EcritureNum"].isin(nums)][VUE]
signaler("PAIEMENT_SANS_FACTURE", "T8 Paiements sans facture", "Paiements fournisseurs non rapprochés (non lettrés) d'une facture", nums, d)

montants = fec[["Debit", "Credit"]].max(axis=1)
montants = montants[montants >= 10]
p1 = montants.astype(str).str[0].astype(int)
p2 = (montants.astype("int64").astype(str).str[:2]).astype(int)
obs1 = p1.value_counts(normalize=True).reindex(range(1, 10), fill_value=0)
att1 = pd.Series(np.log10(1 + 1 / np.arange(1, 10)), index=range(1, 10))
obs2 = p2.value_counts(normalize=True).reindex(range(10, 100), fill_value=0)
att2 = pd.Series(np.log10(1 + 1 / np.arange(10, 100)), index=range(10, 100))
mad1, mad2 = (obs1 - att1).abs().mean(), (obs2 - att2).abs().mean()
chi = chisquare(p1.value_counts().reindex(range(1, 10), fill_value=0), att1 * len(p1))


def verdict(mad, seuils):
    return next(v for s, v in zip(seuils + [np.inf], ["Conformité étroite", "Conformité acceptable", "Conformité marginale", "Non conforme"]) if mad <= s)


v1, v2 = verdict(mad1, [0.006, 0.012, 0.015]), verdict(mad2, [0.0012, 0.0018, 0.0022])
benford = pd.DataFrame({"Chiffre": range(1, 10), "Observé": obs1.values.round(4), "Attendu": att1.values.round(4),
                        "Écart": (obs1 - att1).values.round(4), "Nb": p1.value_counts().reindex(range(1, 10), fill_value=0).values})
pics = pd.DataFrame({"DeuxChiffres": range(10, 100), "Observé": obs2.values.round(4), "Attendu": att2.values.round(4),
                     "Écart": (obs2 - att2).values.round(4)}).sort_values("Écart", ascending=False).head(10)

gt_path = DATA / "anomalies_injectees.csv"
gt = pd.read_csv(gt_path, sep=";", dtype=str, encoding="utf-8-sig") if gt_path.exists() else None
toutes = set(gt["EcritureNum"]) if gt is not None else set()

synthese = []
for t in tests:
    sig = ecr[ecr["EcritureNum"].isin(t["nums"])]
    ligne = {"Test": t["titre"], "Description": t["description"], "Signalées": len(t["nums"]), "Montant": round(sig["Montant"].sum(), 2)}
    if gt is not None:
        att = set(gt.loc[gt["Anomalie"].eq(t["code"]), "EcritureNum"])
        ligne["Retrouvées"] = f"{len(att & t['nums'])}/{len(att)}"
        ligne["Taux"] = round(len(att & t["nums"]) / len(att), 3) if att else None
        ligne["FaussesAlertes"] = len(t["nums"] - toutes)
    synthese.append(ligne)
synthese = pd.DataFrame(synthese)

drapeaux = pd.DataFrame([(n, t["code"]) for t in tests for n in sorted(t["nums"])], columns=["EcritureNum", "Test"])

RES.mkdir(exist_ok=True)
sortie = RES / "02_tests_audit.xlsx"
try:
    drapeaux.to_csv(RES / "drapeaux_tests.csv", sep=";", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(sortie, engine="xlsxwriter", datetime_format="dd/mm/yyyy") as w:
        wb = w.book
        entete = wb.add_format({"bold": True, "font_color": "white", "bg_color": "#1F3864", "border": 1})
        euro = wb.add_format({"num_format": "#,##0.00 €"})
        pct = wb.add_format({"num_format": "0.0%"})
        lien = wb.add_format({"font_color": "blue", "underline": 1})
        titre = wb.add_format({"bold": True, "font_size": 12})

        def ecrire(nom, df, ligne0=0):
            df.to_excel(w, sheet_name=nom, index=False, startrow=ligne0)
            ws = w.sheets[nom]
            for i, c in enumerate(df.columns):
                ws.write(ligne0, i, c, entete)
                larg = max([len(str(c))] + [len(str(x)) for x in df[c].head(300)])
                fmt = euro if c in ("Montant", "TTC", "TotalTTC") else pct if c == "Taux" else None
                ws.set_column(i, i, min(max(larg + 2, 12), 70), fmt)
            ws.freeze_panes(ligne0 + 1, 0)
            if df.empty:
                ws.write(ligne0 + 1, 0, "Aucune écriture signalée")
            return ws

        ws = ecrire("Synthèse", synthese)
        x = len(synthese.columns)
        ws.write(0, x, "Détail", entete)
        for i, t in enumerate(tests, start=1):
            ws.write_url(i, x, f"internal:'{t['titre']}'!A1", lien, string="Voir")
        if "Taux" in synthese:
            k = synthese.columns.get_loc("Taux")
            ws.conditional_format(1, k, len(synthese), k, {"type": "data_bar", "bar_color": "#63BE7B", "bar_solid": True, "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 1})
        for nom, df in feuilles.items():
            ecrire(nom, df)

        ws = ecrire("T9 Benford", benford, 3)
        ws.write(0, 0, f"Loi de Benford - premier chiffre ({len(p1):,} montants)".replace(",", " "), titre)
        ws.write(1, 0, f"MAD = {mad1:.4f} : {v1} | Khi² = {chi.statistic:.1f} (p = {chi.pvalue:.3f}) | Deux premiers chiffres : MAD = {mad2:.5f} : {v2}")
        graph = wb.add_chart({"type": "column"})
        graph.add_series({"name": "Observé", "categories": ["T9 Benford", 4, 0, 12, 0], "values": ["T9 Benford", 4, 1, 12, 1], "fill": {"color": "#1F3864"}})
        courbe = wb.add_chart({"type": "line"})
        courbe.add_series({"name": "Attendu (Benford)", "categories": ["T9 Benford", 4, 0, 12, 0], "values": ["T9 Benford", 4, 2, 12, 2],
                           "line": {"color": "#C00000", "width": 2.25}, "marker": {"type": "circle", "size": 6, "fill": {"color": "#C00000"}, "border": {"color": "#C00000"}}})
        graph.combine(courbe)
        graph.set_title({"name": "Répartition du premier chiffre des montants"})
        graph.set_y_axis({"num_format": "0%", "major_gridlines": {"visible": True, "line": {"color": "#D9D9D9"}}})
        graph.set_x_axis({"name": "Premier chiffre"})
        graph.set_legend({"position": "bottom"})
        graph.set_size({"width": 620, "height": 360})
        ws.insert_chart("G4", graph)
        ws.write(15, 0, "Les 10 couples de deux premiers chiffres les plus surreprésentés", titre)
        pics.to_excel(w, sheet_name="T9 Benford", index=False, startrow=16)
        for i, c in enumerate(pics.columns):
            ws.write(16, i, c, entete)
except PermissionError:
    sys.exit(f"Impossible d'écrire {sortie.name} : ferme le fichier dans Excel puis relance.")

print(f"\nTests d'audit : {fichier.name} ({len(ecr):,} écritures hors à-nouveaux)\n".replace(",", " "))
print(f"{'Test':<28}{'Signalées':>10}{'Retrouvées':>12}{'Fausses alertes':>17}")
for r in synthese.to_dict("records"):
    print(f"{r['Test']:<28}{r['Signalées']:>10}{r.get('Retrouvées', '-'):>12}{r.get('FaussesAlertes', '-'):>17}")
print(f"\nBenford (1er chiffre) : MAD = {mad1:.4f} -> {v1}")
print(f"Benford (2 chiffres)  : MAD = {mad2:.5f} -> {v2}")
print(f"\nRapport Excel : {sortie}")
