"""choisir_affinage : ecrit dans la recette la valeur de l'essai choisi (python standard, sans Blender).
    usine choisir_affinage recettes/<id>.json <numero>"""
import json, sys, os
if len(sys.argv) < 3 or not sys.argv[2].strip().isdigit():
    raise SystemExit("usage : usine choisir_affinage recettes/<id>.json <numero>   (le numero lu sur affinage.png)")
recette, n = sys.argv[1], sys.argv[2]
if not os.path.isfile(recette):
    raise SystemExit(f"ERREUR : recette introuvable : {recette}")
R = json.load(open(recette, encoding="utf-8-sig"))
fv = os.path.join("modeles", R["id"], "affinage", "valeurs.json")
if not os.path.isfile(fv):
    raise SystemExit(f"ERREUR : pas d'essais d'affinage pour {R['id']} : lance d'abord usine affiner {recette}")
vals = json.load(open(fv, encoding="utf-8"))
if str(int(n)) not in vals:
    raise SystemExit(f"ERREUR : essai {n} inexistant (essais : {', '.join(sorted(vals, key=int))})")
v = vals[str(int(n))]
fait = []
def remplacer(x):
    if isinstance(x, dict):
        if "affiner" in x and len(x) == 1:
            fait.append(1); return v
        return {k: remplacer(y) for k, y in x.items()}
    if isinstance(x, list):
        return [remplacer(y) for y in x]
    return x
R["modelage"] = remplacer(R.get("modelage", {}))
if not fait:
    raise SystemExit("ERREUR : aucun {\"affiner\": [...]} dans la recette")
json.dump(R, open(recette, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"CHOIX : valeur {v} ecrite dans la recette. Relance : usine modeler {recette}")
