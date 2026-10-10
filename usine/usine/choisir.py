"""choisir : ecrit dans la recette le reglage numero <n> de la planche de variantes (python standard).
    usine choisir recettes/<id>.json <numero>"""
import json, sys, os
if len(sys.argv) < 3 or not sys.argv[2].strip().isdigit():
    raise SystemExit("usage : usine choisir recettes/<id>.json <numero>   (le numero lu sur la planche de variantes)")
recette, n = sys.argv[1], int(sys.argv[2])
if not os.path.isfile(recette):
    raise SystemExit(f"ERREUR : recette introuvable : {recette}")
r = json.load(open(recette, encoding="utf-8-sig"))
fv = os.path.join(r.get("sortie", f"build/sprites/{r['id']}"), "variantes.json")
if not os.path.isfile(fv):
    raise SystemExit(f"ERREUR : pas de planche de variantes pour {r['id']} : lance d'abord usine variantes {recette}")
vs = json.load(open(fv, encoding="utf-8"))
if not 1 <= n <= len(vs):
    raise SystemExit(f"ERREUR : numero {n} hors planche (1 a {len(vs)})")
v = vs[n - 1]
r.update(v); json.dump(r, open(recette, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"CHOIX : recette mise a jour avec la variante {n} : {v}")
