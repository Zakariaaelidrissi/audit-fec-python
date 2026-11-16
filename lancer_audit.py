import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ETAPES = ["generer_donnees.py", "controles_conformite.py", "tests_audit.py", "score_risque.py"]

for i, script in enumerate(ETAPES, start=1):
    print(f"\n{'=' * 70}\nÉtape {i}/{len(ETAPES)} : {script}\n{'=' * 70}")
    if subprocess.run([sys.executable, str(BASE / script)], cwd=BASE).returncode:
        sys.exit(f"\nArrêt : {script} a échoué.")
print("\nAudit terminé. Résultats dans le dossier « resultats ».")
