import numpy as np
import pandas as pd
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

SEED = 2025
rng = np.random.default_rng(SEED)

SIREN = "999999999"
DEBUT, FIN = date(2025, 1, 1), date(2025, 12, 31)
ARRETE = date(2026, 1, 31)
TVA = 0.20
OUT = Path(__file__).resolve().parent / "data"

FERIES = {date(2025, m, j) for m, j in [(1, 1), (4, 21), (5, 1), (5, 8), (5, 29), (6, 9), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]}

JOURNAUX = {"AN": "À nouveaux", "VE": "Ventes", "AC": "Achats", "BQ": "Banque", "PA": "Paie", "OD": "Opérations diverses"}

COMPTES = {
    "101000": "Capital social", "106800": "Autres réserves", "164000": "Emprunts auprès des établissements de crédit",
    "215400": "Matériel industriel", "218200": "Matériel de transport",
    "281540": "Amortissements du matériel industriel", "281820": "Amortissements du matériel de transport",
    "401000": "Fournisseurs", "408100": "Fournisseurs - factures non parvenues",
    "411000": "Clients", "418100": "Clients - factures à établir",
    "421000": "Personnel - rémunérations dues", "431000": "Sécurité sociale",
    "445510": "TVA à décaisser", "445660": "TVA déductible sur ABS", "445670": "Crédit de TVA à reporter", "445710": "TVA collectée",
    "471000": "Compte d'attente", "512000": "Banque",
    "601000": "Achats de matières premières", "606100": "Fournitures non stockables", "613200": "Locations immobilières",
    "615600": "Maintenance", "622600": "Honoraires", "624100": "Transports sur achats", "625700": "Réceptions",
    "626000": "Frais postaux et de télécommunications", "627000": "Services bancaires",
    "641000": "Rémunérations du personnel", "645000": "Charges de sécurité sociale", "661100": "Intérêts des emprunts",
    "681120": "Dotations aux amortissements des immobilisations corporelles", "706000": "Prestations de services",
}

CATS = [("601000", 0.40, 7.6, 0.9), ("606100", 0.12, 5.5, 0.8), ("615600", 0.10, 6.8, 0.8), ("622600", 0.08, 7.3, 0.7),
        ("624100", 0.15, 6.2, 0.8), ("625700", 0.07, 5.0, 0.7), ("626000", 0.08, 5.3, 0.6)]
CHARGES = ["606100", "615600", "622600", "624100", "625700", "626000"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

PREF = ["Alpha", "Atlantique", "Horizon", "Delta", "Nova", "Mayenne", "Loire", "Cristal", "Armor", "Boréal", "Vega", "Sirius"]
SUFF = ["Distribution", "Services", "Industrie", "Logistique", "Conseil", "Négoce", "Agro", "Technologies"]
noms = [f"{p} {s}" for p in PREF for s in SUFF]
rng.shuffle(noms)
CLIENTS = [(f"C{i + 1:04d}", noms[i]) for i in range(60)]
FOURN = [(f"F{i + 1:04d}", noms[60 + i], CATS[i % len(CATS)][0]) for i in range(28)]
FOURN_PAR_CAT = [[f for f in FOURN if f[2] == c[0]] for c in CATS]
BAILLEUR = ("F0099", "SCI Horizon Immobilier", "613200")

JOURS = pd.date_range(DEBUT, FIN).date
OUVRES = np.array([d for d in JOURS if d.weekday() < 5 and d not in FERIES])
ORD = np.array([d.toordinal() for d in OUVRES])
MOIS = np.array([d.month for d in OUVRES])
NON_OUVRES = [d for d in JOURS if (d.weekday() >= 5 or d in FERIES) and d != DEBUT]


def r2(x):
    return round(float(x), 2)


def prochain_ouvre(d):
    i = np.searchsorted(ORD, d.toordinal())
    return OUVRES[i] if i < len(OUVRES) else None


def premier_ouvre(m):
    return OUVRES[MOIS == m][0]


def dernier_ouvre(m):
    return OUVRES[MOIS == m][-1]


_n_let = iter(range(26 ** 3))


def code_let():
    n, s = next(_n_let), ""
    for _ in range(3):
        s, n = chr(65 + n % 26) + s, n // 26
    return s


def L(compte, de=0.0, cr=0.0, aux=None, let="", dlet=None):
    return (compte, aux, r2(de), r2(cr), let, dlet)


ecritures = []


def ecrire(j, d, piece, lib, mvts, valid=None, anomalies=()):
    e = {"id": len(ecritures), "j": j, "d": d, "piece": piece, "lib": lib, "mvts": mvts,
         "valid": valid or d + timedelta(days=int(rng.integers(0, 8))), "anom": set(anomalies)}
    ecritures.append(e)
    return e


tva_col, tva_ded = defaultdict(float), defaultdict(float)
n_piece_f = defaultdict(lambda: int(rng.integers(100, 900)))


def facture_achat(d, f, compte, ht, payer=True, delai=40, piece=None, lib=None, anomalies=(), anom_bq=()):
    ht = r2(ht)
    tva = r2(ht * TVA)
    ttc = r2(ht + tva)
    aux = (f[0], f[1])
    if piece is None:
        n_piece_f[f[0]] += 1
        piece = f"{f[0]}-{n_piece_f[f[0]]:04d}"
    dp = prochain_ouvre(d + timedelta(days=delai)) if payer else None
    let = code_let() if dp else ""
    ecrire("AC", d, piece, lib or f"Facture {f[1]}",
           [L(compte, de=ht), L("445660", de=tva), L("401000", cr=ttc, aux=aux, let=let, dlet=dp)], anomalies=anomalies)
    tva_ded[d.month] += tva
    if dp:
        ecrire("BQ", dp, f"VIR-{piece}", f"Paiement {f[1]}",
               [L("401000", de=ttc, aux=aux, let=let, dlet=dp), L("512000", cr=ttc)], anomalies=anom_bq)
    return piece


ecrire("AN", DEBUT, "AN-2025", "Reprise des soldes au 01/01/2025", [
    L("215400", de=420000), L("218200", de=95000), L("512000", de=186342.17),
    L("101000", cr=150000), L("106800", cr=211342.17), L("164000", cr=120000),
    L("281540", cr=180000), L("281820", cr=40000)], valid=DEBUT)

N_VE = 1500
w_cli = 1 / np.arange(1, len(CLIENTS) + 1) ** 0.8
dates_ve = np.sort(rng.choice(OUVRES, N_VE))
idx_cli = rng.choice(len(CLIENTS), N_VE, p=w_cli / w_cli.sum())
ht_ve = rng.lognormal(7.6, 0.9, N_VE)
delai_ve = rng.normal(45, 12, N_VE).clip(5, 120).astype(int)
impaye_ve = rng.random(N_VE) < 0.05

for k in range(N_VE):
    d, cli = dates_ve[k], CLIENTS[idx_cli[k]]
    ht = r2(ht_ve[k])
    tva = r2(ht * TVA)
    ttc = r2(ht + tva)
    piece = f"FV2025-{k + 1:05d}"
    dp = None if impaye_ve[k] else prochain_ouvre(d + timedelta(days=int(delai_ve[k])))
    let = code_let() if dp else ""
    ecrire("VE", d, piece, f"Facture {cli[1]}",
           [L("411000", de=ttc, aux=cli, let=let, dlet=dp), L("706000", cr=ht), L("445710", cr=tva)])
    tva_col[d.month] += tva
    if dp:
        ecrire("BQ", dp, f"REG-{piece}", f"Règlement {cli[1]}",
               [L("512000", de=ttc), L("411000", cr=ttc, aux=cli, let=let, dlet=dp)])

N_AC = 1000
dates_ac = np.sort(rng.choice(OUVRES, N_AC))
cat_ac = rng.choice(len(CATS), N_AC, p=np.array([c[1] for c in CATS]))
delai_ac = rng.normal(40, 10, N_AC).clip(0, 90).astype(int)
paye_ac = rng.random(N_AC) > 0.03
achats = []

for k in range(N_AC):
    compte, _, mu, sg = CATS[cat_ac[k]]
    pool = FOURN_PAR_CAT[cat_ac[k]]
    f = pool[rng.integers(len(pool))]
    ht = r2(rng.lognormal(mu, sg))
    piece = facture_achat(dates_ac[k], f, compte, ht, bool(paye_ac[k]), int(delai_ac[k]))
    achats.append((dates_ac[k], f, compte, ht, piece))

restant = 120000.0
for m in range(1, 13):
    d1, dn = premier_ouvre(m), dernier_ouvre(m)
    facture_achat(d1, BAILLEUR, "613200", 4500, delai=5, piece=f"LOYER-2025-{m:02d}", lib=f"Loyer {MOIS_FR[m - 1]} 2025")

    brut = r2(rng.normal(85000, 2500))
    sal, patr = r2(brut * 0.22), r2(brut * 0.42)
    net = r2(brut - sal)
    ecrire("PA", dn, f"PAIE-2025-{m:02d}", f"Paie {MOIS_FR[m - 1]} 2025",
           [L("641000", de=brut), L("645000", de=patr), L("421000", cr=net), L("431000", cr=sal + patr)])
    ecrire("BQ", dn, f"VIR-SAL-2025-{m:02d}", f"Virement salaires {MOIS_FR[m - 1]}", [L("421000", de=net), L("512000", cr=net)])
    if m < 12:
        du = prochain_ouvre(date(2025, m + 1, 15))
        ecrire("BQ", du, f"URSSAF-2025-{m:02d}", f"Cotisations sociales {MOIS_FR[m - 1]}",
               [L("431000", de=sal + patr), L("512000", cr=sal + patr)])

    interets = r2(restant * 0.035 / 12)
    de = prochain_ouvre(date(2025, m, 10))
    ecrire("BQ", de, f"ECH-PRET-{m:02d}", f"Échéance emprunt {MOIS_FR[m - 1]}",
           [L("164000", de=2000), L("661100", de=interets), L("512000", cr=2000 + interets)])
    restant -= 2000

    frais = r2(rng.uniform(35, 120))
    ecrire("BQ", dn, f"FRAIS-{m:02d}", f"Frais bancaires {MOIS_FR[m - 1]}", [L("627000", de=frais), L("512000", cr=frais)])

ecrire("OD", FIN, "AMORT-2025", "Dotations aux amortissements 2025",
       [L("681120", de=63427.50), L("281540", cr=48216.67), L("281820", cr=15210.83)], valid=date(2026, 1, 20))

for i, k in enumerate(rng.choice(len(achats), 8, replace=False)):
    d0, f, compte, ht, piece = achats[k]
    d1 = prochain_ouvre(d0 + timedelta(days=int(rng.integers(1, 15)))) or d0
    facture_achat(d1, f, compte, ht, payer=i < 5, piece=piece, anomalies=["DOUBLON"], anom_bq=["DOUBLON"])

for i, d in enumerate(rng.choice(np.array(NON_OUVRES), 10, replace=False)):
    x = r2(rng.lognormal(7.0, 0.6))
    ecrire("OD", d, f"OD-WE-{i + 1:03d}", "Régularisation charges",
           [L(rng.choice(CHARGES), de=x), L("408100", cr=x)], valid=d, anomalies=["WEEKEND_FERIE"])

for i, x in enumerate(rng.choice([5000, 8000, 10000, 12000, 15000, 20000, 25000, 30000], 10)):
    d = rng.choice(OUVRES)
    ecrire("OD", d, f"OD-PROV-{i + 1:03d}", "Charges à payer",
           [L(rng.choice(CHARGES), de=x), L("408100", cr=x)], anomalies=["MONTANT_ROND"])

conseil = FOURN_PAR_CAT[[c[0] for c in CATS].index("622600")][0]
for base in (date(2025, 5, 12), date(2025, 9, 15)):
    for _ in range(4):
        d = prochain_ouvre(base + timedelta(days=int(rng.integers(0, 10))))
        facture_achat(d, conseil, "622600", rng.uniform(9500, 9990) / (1 + TVA), delai=30, anomalies=["SOUS_SEUIL"])

for i, ecart in enumerate([0.01, 9.99, 150.00]):
    d = rng.choice(OUVRES)
    x = r2(rng.lognormal(7.5, 0.6))
    ecrire("OD", d, f"OD-REG-{i + 1:03d}", "Écriture de régularisation",
           [L(rng.choice(CHARGES), de=x), L("408100", cr=x - ecart)], anomalies=["DESEQUILIBRE"])

for i in range(6):
    d = date(2025, 12, int(rng.choice([29, 30, 31])))
    x = r2(rng.lognormal(9.3, 0.4))
    v = ARRETE + timedelta(days=int(rng.integers(10, 50)))
    if i < 3:
        mv, lib = [L("408100", de=x), L(rng.choice(CHARGES), cr=x)], "Annulation charges à payer"
    else:
        mv, lib = [L("418100", de=x), L("706000", cr=x)], "Factures à établir"
    ecrire("OD", d, f"OD-CLOT-{i + 1:03d}", lib, mv, valid=v, anomalies=["POST_CLOTURE"])

fictif = ("F9001", "Optima Conseil Express", "622600")
for d in (date(2025, 2, 14), date(2025, 6, 20), date(2025, 11, 21)):
    facture_achat(prochain_ouvre(d), fictif, "622600", rng.uniform(7200, 9400) / (1 + TVA), delai=0,
                  lib="Prestation de conseil", anomalies=["FOURNISSEUR_FICTIF"], anom_bq=["FOURNISSEUR_FICTIF"])

LIBS = ["Divers", "Ajustement", "Régul à voir", "Correction écart", "Écart inexpliqué", "Annule et remplace", "Virement interne divers", "À justifier"]
for i, lib in enumerate(LIBS):
    d = rng.choice(OUVRES)
    x = r2(rng.lognormal(7.5, 0.8))
    mv = [L("471000", de=x), L("512000", cr=x)] if i % 2 == 0 else [L(rng.choice(CHARGES), de=x), L("471000", cr=x)]
    ecrire("OD", d, f"OD-DIV-{i + 1:03d}", lib, mv, anomalies=["LIBELLE_SUSPECT"])

for i in range(5):
    f = FOURN[rng.integers(len(FOURN))]
    d = rng.choice(OUVRES)
    x = r2(rng.lognormal(8.0, 0.5))
    ecrire("BQ", d, f"VIR-MAN-{i + 1:03d}", f"Paiement {f[1]}",
           [L("401000", de=x, aux=(f[0], f[1])), L("512000", cr=x)], anomalies=["PAIEMENT_SANS_FACTURE"])

for m in range(1, 12):
    d = prochain_ouvre(date(2025, m + 1, 19))
    col, ded = r2(tva_col[m]), r2(tva_ded[m])
    net = r2(col - ded)
    mv = [L("445710", de=col), L("445660", cr=ded)]
    mv.append(L("445510", cr=net) if net >= 0 else L("445670", de=-net))
    ecrire("OD", d, f"CA3-2025-{m:02d}", f"Déclaration TVA {MOIS_FR[m - 1]} 2025", mv)
    if net > 0:
        ecrire("BQ", d, f"TVA-2025-{m:02d}", f"Paiement TVA {MOIS_FR[m - 1]}", [L("445510", de=net), L("512000", cr=net)])

ordre = sorted(ecritures, key=lambda e: (e["j"], e["d"], e["id"]))
cibles = set(rng.choice([e["id"] for e in ecritures if e["j"] in ("VE", "AC", "BQ", "OD")], 4, replace=False).tolist())
num, manquants = defaultdict(int), []
for e in ordre:
    j = e["j"]
    if e["id"] in cibles and num[j] > 0:
        for _ in range(int(rng.integers(1, 4))):
            num[j] += 1
            manquants.append((f"{j}{num[j]:06d}", j, e["d"].strftime("%d/%m/%Y"), "", "Numéro absent de la séquence", 0.0, "RUPTURE_SEQUENCE"))
    num[j] += 1
    e["num"] = f"{j}{num[j]:06d}"

COLS = ["JournalCode", "JournalLib", "EcritureNum", "EcritureDate", "CompteNum", "CompteLib", "CompAuxNum", "CompAuxLib",
        "PieceRef", "PieceDate", "EcritureLib", "Debit", "Credit", "EcritureLet", "DateLet", "ValidDate", "Montantdevise", "Idevise"]
rows = [(e["j"], JOURNAUX[e["j"]], e["num"], e["d"], c, COMPTES[c], a[0] if a else "", a[1] if a else "",
         e["piece"], e["d"], e["lib"], de, cr, lt, dl, e["valid"], "", "")
        for e in ordre for c, a, de, cr, lt, dl in e["mvts"]]
fec = pd.DataFrame(rows, columns=COLS).sort_values(["EcritureDate", "JournalCode", "EcritureNum"], kind="stable")
total_d, total_c = fec["Debit"].sum(), fec["Credit"].sum()

for col in ("EcritureDate", "PieceDate", "DateLet", "ValidDate"):
    fec[col] = pd.to_datetime(fec[col]).dt.strftime("%Y%m%d").fillna("")
for col in ("Debit", "Credit"):
    fec[col] = fec[col].map("{:.2f}".format).str.replace(".", ",", regex=False)

OUT.mkdir(exist_ok=True)
chemin_fec = OUT / f"{SIREN}FEC{FIN:%Y%m%d}.txt"
fec.to_csv(chemin_fec, sep="\t", index=False, encoding="utf-8")

gt = [(e["num"], e["j"], e["d"].strftime("%d/%m/%Y"), e["piece"], e["lib"], r2(sum(m[2] for m in e["mvts"])), a)
      for e in ordre for a in sorted(e["anom"])] + manquants
gt = pd.DataFrame(gt, columns=["EcritureNum", "Journal", "Date", "PieceRef", "Libelle", "Montant", "Anomalie"])
gt.to_csv(OUT / "anomalies_injectees.csv", sep=";", index=False, encoding="utf-8-sig", decimal=",")

print(f"\nFEC généré : {chemin_fec.name}")
print(f"{len(ecritures):,} écritures | {len(fec):,} lignes".replace(",", " "))
print(f"Total débit  : {total_d:>15,.2f}".replace(",", " "))
print(f"Total crédit : {total_c:>15,.2f}".replace(",", " "))
print(f"Écart        : {total_d - total_c:>15,.2f}".replace(",", " "))
print(f"\nAnomalies injectées ({len(gt)}) :")
print(gt["Anomalie"].value_counts().to_string())
print(f"\nFichiers dans : {OUT}")
