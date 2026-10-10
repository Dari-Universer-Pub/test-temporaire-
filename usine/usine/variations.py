"""variations : planche numerotee de N VERSIONS d'un asset construit par gabarit (proportions differentes),
en silhouette noire (face + cote) et en couleur (3/4). L'agent CHOISIT au lieu de regler.
    usine variations recettes/<id>.json [nombre=6]
    usine choisir_variation recettes/<id>.json <numero>
La version 1 est toujours la recette actuelle. Les autres tirent chaque reglage NUMERIQUE du gabarit entre 0,7 et 1,35
fois sa valeur (les couleurs ne changent pas). "variations_figees": ["tete", ...] dans "modelage" = reglages a ne pas toucher."""
import os, sys, json, random, runpy, shutil
import bpy
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import lire_image, ecrire_image, numeroter, grille, redimensionner

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    raise SystemExit("usage : usine variations recettes/<id>.json [nombre]")
RECETTE = argv[0]; N = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 6
if not 2 <= N <= 12:
    raise SystemExit("ERREUR : nombre de variations de 2 a 12")
R = json.load(open(RECETTE, encoding="utf-8-sig"))
M = R.get("modelage") or {}
if not M.get("gabarit"):
    raise SystemExit("ERREUR : variations : la recette doit construire par gabarit (\"modelage\": {\"gabarit\": ...})")
G = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gabarits", M["gabarit"] + ".json"), encoding="utf-8"))
base = dict(G.get("reglages", {})); base.update(M.get("reglages") or {})
figes = set(M.get("variations_figees", []))
num = [k for k, v in base.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and k not in figes]
rnd = random.Random(int(M.get("graine_variations", 1)))
versions = [dict(M.get("reglages") or {})]
for k in range(1, N):
    v = dict(M.get("reglages") or {})
    for c in num:
        v[c] = round(base[c] * rnd.uniform(0.7, 1.35), 3)
    versions.append(v)

ID = R["id"]; tmp = os.path.join("build", "variations", ID); os.makedirs(tmp, exist_ok=True)
MOD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modeler.py")
cases = []
for k, reg in enumerate(versions, 1):
    rv = {"id": f"{ID}__v{k}", "modelage": dict(M, reglages=reg)}
    p = os.path.join(tmp, f"v{k}.json"); json.dump(rv, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sys.argv = [sys.argv[0], "--", "modeler", p]
    try:
        runpy.run_path(MOD, run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            print(f"  version {k} : ECHEC ({e})"); cases.append(None); continue
    ap = os.path.join("modeles", f"{ID}__v{k}", "apercu.png")
    if not os.path.exists(ap):
        print(f"  version {k} : pas d'apercu"); cases.append(None); continue
    a = lire_image(ap); h_, w_ = a.shape[:2]; c = (w_ - 3 * 8) // 4   # 4 cases separees de 8 pixels
    vues = [a[:, i * (c + 8):i * (c + 8) + c] for i in range(4)]
    fond = vues[0][h_ - 3, c // 2, :3]
    t = []
    for i in (0, 1):   # silhouettes noires : face, cote
        v = vues[i]; m = np.abs(v[..., :3] - fond).max(-1) > 0.08
        m[:40, :60] = False   # le numero de la vue
        s = np.ones_like(v); s[m, :3] = 0.05; t.append(redimensionner(s, 200, 200))
    t.append(redimensionner(vues[3], 200, 200))
    case = np.concatenate([t[0], np.ones((200, 4, 4)), t[1], np.ones((200, 4, 4)), t[2]], 1)
    cases.append(numeroter(case, k))
    shutil.rmtree(os.path.join("modeles", f"{ID}__v{k}"), ignore_errors=True)
vide = np.ones((200, 608, 4)); vide[..., :3] = 0.7
planche = grille([c if c is not None else vide for c in cases], colonnes=2, case=(608, 200), marge=12)
sortie = os.path.join(R.get("sortie", f"build/sprites/{ID}"), "variations.png"); os.makedirs(os.path.dirname(sortie), exist_ok=True)
ecrire_image(sortie, planche)
json.dump(versions, open(os.path.join(os.path.dirname(sortie), "variations.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"VARIATIONS_OK {sum(c is not None for c in cases)}/{N}")
print(f"REGARDE : {sortie}  (silhouette face, silhouette cote, couleur 3/4 ; 1 = la recette actuelle)")
print(f"Puis : usine choisir_variation {RECETTE} <numero>   (la silhouette la plus lisible et la plus caracteristique)")
