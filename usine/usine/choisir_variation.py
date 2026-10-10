"""choisir_variation : ecrit dans "modelage.reglages" de la recette les reglages de la version <n> (python standard).
    usine choisir_variation recettes/<id>.json <numero>"""
import json, sys, os
if len(sys.argv) < 3 or not sys.argv[2].strip().isdigit():
    raise SystemExit("usage : usine choisir_variation recettes/<id>.json <numero>   (lu sur variations.png)")
recette, n = sys.argv[1], int(sys.argv[2])
if not os.path.isfile(recette):
    raise SystemExit(f"ERREUR : recette introuvable : {recette}")
r = json.load(open(recette, encoding="utf-8-sig"))
fv = os.path.join(r.get("sortie", f"build/sprites/{r['id']}"), "variations.json")
if not os.path.isfile(fv):
    raise SystemExit(f"ERREUR : pas de planche de variations pour {r['id']} : lance d'abord usine variations {recette}")
vs = json.load(open(fv, encoding="utf-8"))
if not 1 <= n <= len(vs):
    raise SystemExit(f"ERREUR : numero {n} hors planche (1 a {len(vs)})")
r.setdefault("modelage", {})["reglages"] = vs[n - 1]
json.dump(r, open(recette, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"CHOIX : version {n} : {vs[n - 1]}\nEnsuite : usine modeler {recette}  puis  usine fabriquer {recette}")
