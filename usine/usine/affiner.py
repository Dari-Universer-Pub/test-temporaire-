"""affiner : regler une valeur de gout par CHOIX NUMEROTE (jamais un nombre devine).

Dans "modelage", remplace une valeur par {"affiner": [min, max]} (nombre ou liste de nombres), UNE a la fois. Ex. :
   {"faire": "poser", "quoi": "corne", ..., "incliner": {"affiner": [0, 40]}}
    usine affiner recettes/<id>.json            -> planche de 6 essais numerotes entre min et max
    usine choisir_affinage recettes/<id>.json 4 -> la valeur de l'essai 4 est ecrite dans la recette
Pour affiner encore : remets {"affiner": [...]} avec un intervalle plus etroit autour de la valeur choisie.
"""
import os, sys, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *

ARGS = sys.argv[sys.argv.index("--") + 1:]
RECETTE = ARGS[0]
R = lire_recette(RECETTE)
N = 6
def _compter(x):
    if isinstance(x, dict):
        return (1 if "affiner" in x and len(x) == 1 else 0) + sum(_compter(v) for v in x.values())
    if isinstance(x, list):
        return sum(_compter(v) for v in x)
    return 0
_n = _compter(R.get("modelage", {}))
if _n != 1:
    raise SystemExit(f"ERREUR : il faut UNE valeur {{\"affiner\": [min, max]}} dans \"modelage\" (trouve : {_n}). "
                     "Exemple : \"incliner\": {\"affiner\": [0, 40]}")
ICI = os.path.dirname(os.path.abspath(__file__))
import bpy
dossier = os.path.join("modeles", R["id"], "affinage")
os.makedirs(dossier, exist_ok=True)
for f in os.listdir(dossier):
    os.remove(os.path.join(dossier, f))
for k in range(1, N + 1):
    env = dict(os.environ, USINE_AFFINAGE=str(k), USINE_AFFINAGE_N=str(N))
    r = subprocess.run([bpy.app.binary_path, "-b", "--python", os.path.join(ICI, "modeler.py"), "--", "modeler", RECETTE],
                       capture_output=True, text=True, env=env, errors="replace")
    ligne = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith("AFFINAGE ") or ("Error" in l and "EGL" not in l) or "SystemExit" in l]
    print("  essai", k, ":", ligne[-1] if ligne else "?")
ims = [numeroter(lire_image(os.path.join(dossier, f"{k}.png")), k, k=3) for k in range(1, N + 1)
       if os.path.exists(os.path.join(dossier, f"{k}.png"))]
if not ims:
    raise SystemExit("aucun essai rendu (lis les messages ci-dessus ; une seule valeur {\"affiner\": [min, max]} dans la recette ?)")
p = os.path.join("modeles", R["id"], "affinage.png")
ecrire_image(p, grille(ims, colonnes=2, case=(ims[0].shape[1], ims[0].shape[0])))
vals = json.load(open(os.path.join(dossier, "valeurs.json"))) if os.path.exists(os.path.join(dossier, "valeurs.json")) else {}
print(f"\nREGARDE : {p}  (6 essais numerotes, de la plus petite valeur a la plus grande)")
for k in sorted(vals, key=int):
    print(f"   {k} = {vals[k]}")
print(f"Puis : usine choisir_affinage {RECETTE} <numero>")
