import sys
import numpy as np
import pandas as pd
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA, RES = BASE / "data", BASE / "resultats"
DEBUT, FIN = pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")
COLS = ["JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
        "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit", "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise"]
OBLIG = ["JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum", "CompteLib", "PieceRef", "PieceDate", "EcritureLib", "ValidDate"]
REF = ["Ligne", "JournalCode", "EcritureNum"]

fichier = next(DATA.glob("*FEC*.txt"), None)
if fichier is None:
    sys.exit("Aucun FEC dans le dossier data : lance d'abord generer_donnees.py")

fec = pd.read_csv(fichier, sep="\t", dtype=str, keep_default_na=False, encoding="utf-8")
fec.insert(0, "Ligne", fec.index + 2)

controles, feuilles = [], {}


def ajouter(titre, details, ok, ko):
    n = len(details)
    controles.append({"N°": len(controles) + 1, "Contrôle": titre, "Statut": "OK" if n == 0 else "ANOMALIE",
                      "Nb": n, "Commentaire": ok if n == 0 else ko})
    feuilles[f"C{len(controles):02d} {titre}"[:31]] = details.reset_index(drop=True)


manq = [c for c in COLS if c not in fec.columns]
plus = [c for c in fec.columns if c not in COLS + ["Ligne"]]
d = pd.DataFrame({"Colonne": manq + plus, "Problème": ["Absente"] * len(manq) + ["Non prévue"] * len(plus)})
if d.empty and list(fec.columns[1:]) != COLS:
    d = pd.DataFrame({"Colonne": ["(ordre)"], "Problème": ["Ordre des colonnes différent de la norme"]})
ajouter("Structure", d, "18 colonnes conformes, dans l'ordre réglementaire", "Colonnes absentes, en trop ou mal ordonnées")
if manq:
    sys.exit(f"Colonnes absentes : {', '.join(manq)}. Contrôles arrêtés.")

vide = fec[OBLIG].eq("")
champs = vide.dot(pd.Series([c + ", " for c in OBLIG], index=OBLIG)).str.rstrip(", ")
ajouter("Champs obligatoires", fec.loc[champs.ne(""), REF].assign(ChampsVides=champs[champs.ne("")]),
        "Tous les champs obligatoires sont renseignés", "Lignes avec des champs obligatoires vides")

dates = {c: pd.to_datetime(fec[c], format="%Y%m%d", errors="coerce") for c in ("EcritureDate", "PieceDate", "ValidDate", "DateLet")}
d = pd.concat([fec.loc[s.isna() & fec[c].ne(""), REF].assign(Champ=c, Valeur=fec.loc[s.isna() & fec[c].ne(""), c])
               for c, s in dates.items()], ignore_index=True)
ajouter("Format des dates", d, "Toutes les dates sont au format AAAAMMJJ", "Dates illisibles ou au mauvais format")

ed, vd = dates["EcritureDate"], dates["ValidDate"]
m = ed.notna() & ~ed.between(DEBUT, FIN)
ajouter("Dates hors exercice", fec.loc[m, REF + ["EcritureDate"]],
        "Toutes les écritures sont datées dans l'exercice 2025", "Écritures datées hors de l'exercice")

m = vd < ed
ajouter("Validation avant écriture", fec.loc[m, REF + ["EcritureDate", "ValidDate"]],
        "Aucune validation antérieure à la date d'écriture", "Écritures validées avant leur date")

D = pd.to_numeric(fec["Debit"].str.replace(",", ".", regex=False), errors="coerce")
C = pd.to_numeric(fec["Credit"].str.replace(",", ".", regex=False), errors="coerce")
lab = pd.Series(np.select([D.isna() | C.isna(), (D < 0) | (C < 0), (D > 0) & (C > 0), (D == 0) & (C == 0)],
                          ["Montant non numérique", "Montant négatif", "Débit et crédit renseignés", "Ligne à zéro"], ""), index=fec.index)
ajouter("Montants", fec.loc[lab.ne(""), REF + ["Debit", "Credit"]].assign(Problème=lab[lab.ne("")]),
        "Tous les montants sont valides", "Montants invalides, négatifs ou incohérents")
fec["D"], fec["C"] = D.fillna(0), C.fillna(0)

ecr = (fec.groupby(["JournalCode", "EcritureNum"], sort=False)
       .agg(Date=("EcritureDate", "first"), PieceRef=("PieceRef", "first"), Libelle=("EcritureLib", "first"),
            Debit=("D", "sum"), Credit=("C", "sum")).reset_index())
ecr["Ecart"] = (ecr["Debit"] - ecr["Credit"]).round(2)
ajouter("Équilibre des écritures", ecr.loc[ecr["Ecart"].ne(0), ["JournalCode", "EcritureNum", "Date", "PieceRef", "Libelle", "Debit", "Credit", "Ecart"]],
        "Chaque écriture est équilibrée (débit = crédit)", "Écritures dont le débit diffère du crédit")

td, tc = fec["D"].sum(), fec["C"].sum()
d = pd.DataFrame({"TotalDebit": [round(td, 2)], "TotalCredit": [round(tc, 2)], "Ecart": [round(td - tc, 2)]})
ajouter("Équilibre global", d[d["Ecart"].ne(0)], f"Total débit = total crédit = {td:,.2f}".replace(",", " "),
        f"Écart global de {td - tc:,.2f} entre débit et crédit".replace(",", " "))

parts = ecr["EcritureNum"].str.extract(r"^(.*?)(\d+)$")
ecr["N"] = pd.to_numeric(parts[1], errors="coerce")
manquants = []
for j, g in ecr.dropna(subset=["N"]).groupby("JournalCode"):
    n = g["N"].astype(int).to_numpy()
    pref, larg = parts.loc[g.index[0], 0], len(parts.loc[g.index[0], 1])
    manquants += [(j, f"{pref}{t:0{larg}d}") for t in np.setdiff1d(np.arange(n.min(), n.max() + 1), n)]
ajouter("Numérotation continue", pd.DataFrame(manquants, columns=["JournalCode", "NumeroManquant"]),
        "Numérotation continue dans chaque journal", "Numéros d'écriture absents de la séquence")

s = ecr.assign(DateTs=pd.to_datetime(ecr["Date"], format="%Y%m%d", errors="coerce")).sort_values(["JournalCode", "N"])
recul = s.groupby("JournalCode")["DateTs"].diff().dt.days < 0
ajouter("Chronologie", s.loc[recul, ["JournalCode", "EcritureNum", "Date", "PieceRef", "Libelle"]],
        "Numérotation chronologique dans chaque journal", "Écritures numérotées avant une écriture plus ancienne")

g = (fec[fec["EcritureLet"].ne("")].groupby(["CompteNum", "CompAuxNum", "EcritureLet"])
     .agg(Debit=("D", "sum"), Credit=("C", "sum"), Lignes=("Ligne", "count")).reset_index())
g["Ecart"] = (g["Debit"] - g["Credit"]).round(2)
ajouter("Lettrage", g[g["Ecart"].ne(0)], "Tous les lettrages sont soldés", "Lettrages non soldés")

m = fec["CompteNum"].str.match(r"^(401|411)") & fec["CompAuxNum"].eq("")
ajouter("Tiers sans auxiliaire", fec.loc[m, REF + ["CompteNum", "EcritureLib"]],
        "Toutes les lignes clients/fournisseurs ont un compte auxiliaire", "Lignes clients/fournisseurs sans compte auxiliaire")

att = (fec[fec["CompteNum"].str.startswith("471")].groupby(["CompteNum", "CompteLib"])
       .agg(Debit=("D", "sum"), Credit=("C", "sum"), Lignes=("Ligne", "count")).reset_index())
att["Solde"] = (att["Debit"] - att["Credit"]).round(2)
ajouter("Compte d'attente", att[att["Solde"].ne(0)], "Comptes d'attente soldés à la clôture",
        "Compte d'attente non soldé à la clôture : opérations non justifiées")

synthese = pd.DataFrame(controles)

gt_path = DATA / "anomalies_injectees.csv"
scores = []
if gt_path.exists():
    gt = pd.read_csv(gt_path, sep=";", dtype=str, encoding="utf-8-sig")
    for typ, trouves in (("DESEQUILIBRE", feuilles["C07 Équilibre des écritures"]["EcritureNum"]),
                         ("RUPTURE_SEQUENCE", feuilles["C09 Numérotation continue"]["NumeroManquant"])):
        attendus = set(gt.loc[gt["Anomalie"].eq(typ), "EcritureNum"])
        scores.append((typ, len(attendus & set(trouves)), len(attendus)))

RES.mkdir(exist_ok=True)
sortie = RES / "01_conformite.xlsx"
try:
    with pd.ExcelWriter(sortie, engine="xlsxwriter") as w:
        wb = w.book
        entete = wb.add_format({"bold": True, "font_color": "white", "bg_color": "#1F3864", "border": 1})
        vert = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100", "bold": True})
        rouge = wb.add_format({"bg_color": "#FFC7CE", "font_color": "#9C0006", "bold": True})
        lien = wb.add_format({"font_color": "blue", "underline": 1})
        for nom, df in {"Synthèse": synthese, **feuilles}.items():
            df.to_excel(w, sheet_name=nom, index=False)
            ws = w.sheets[nom]
            for i, c in enumerate(df.columns):
                ws.write(0, i, c, entete)
                larg = max([len(str(c))] + [len(str(x)) for x in df[c].head(300)])
                ws.set_column(i, i, min(larg + 2, 70))
            ws.freeze_panes(1, 0)
            if df.empty:
                ws.write(1, 0, "Aucune anomalie")
        ws = w.sheets["Synthèse"]
        k = synthese.columns.get_loc("Statut")
        ws.conditional_format(1, k, len(synthese), k, {"type": "cell", "criteria": "==", "value": '"OK"', "format": vert})
        ws.conditional_format(1, k, len(synthese), k, {"type": "cell", "criteria": "==", "value": '"ANOMALIE"', "format": rouge})
        x = len(synthese.columns)
        ws.write(0, x, "Détail", entete)
        for i, nom in enumerate(feuilles, start=1):
            ws.write_url(i, x, f"internal:'{nom}'!A1", lien, string="Voir")
except PermissionError:
    sys.exit(f"Impossible d'écrire {sortie.name} : ferme le fichier dans Excel puis relance.")

print(f"\nContrôles de conformité : {fichier.name}")
print(f"{len(fec):,} lignes | {len(ecr):,} écritures\n".replace(",", " "))
for r in controles:
    print(f"{r['N°']:>3}. {r['Contrôle']:<28}{r['Statut']:<10}{r['Nb']:>5}")
if scores:
    print("\nComparaison avec le corrigé :")
    for typ, ok, tot in scores:
        print(f"  {typ:<18} {ok}/{tot} retrouvées")
print(f"\nRapport Excel : {sortie}")
