"""banc du modeleur : le banc d'essai FIXE du superviseur (un brief par famille de formes).
    usine banc [<id> ...]        -> construit et rend chaque brief avec le canon, UNE planche avant/apres + resultats
Tout se passe dans build/banc_modeleur/ (le projet n'est pas touche). Le resultat precedent devient « avant ».
Regle du superviseur : on ne garde un changement de l'usine que si le banc ENTIER est au moins aussi bon (et
Julien juge la planche)."""
import os, sys, json, glob, shutil, subprocess, time
import bpy
import numpy as np
ICI = os.path.dirname(os.path.abspath(__file__)); USINE = os.path.dirname(ICI)
sys.path.insert(0, USINE)
from commun import lire_image, ecrire_image, numeroter, ajuster

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
GALERIE = next((a.split("=", 1)[1] for a in argv if a.startswith("--galerie=")), os.environ.get("USINE_GALERIE"))
argv = [a for a in argv if not a.startswith("--")]
BLENDER = json.loads(os.environ["USINE_BLENDER"]) if os.environ.get("USINE_BLENDER") else [bpy.app.binary_path]
D = os.path.abspath(os.path.join("build", "banc_modeleur")); os.makedirs(os.path.join(D, "recettes"), exist_ok=True)
os.makedirs(os.path.join(D, "art"), exist_ok=True)
shutil.copy2(os.path.join(ICI, "palette.json"), os.path.join(D, "art", "palette.json"))
json.dump({"palette": "art/palette.json", "canon": True}, open(os.path.join(D, "usine_projet.json"), "w"))
briefs = sorted(glob.glob(os.path.join(ICI, "briefs", "*.json")))
if argv:
    briefs = [b for b in briefs if any(os.path.basename(b).startswith(a) for a in argv)]


def lancer(script, *a):
    p = subprocess.run([*BLENDER, "-b", "--python", os.path.join(USINE, script), "--", *a], cwd=D,
                       capture_output=True, text=True, errors="replace")
    return p.stdout + p.stderr


res = []
for b in briefs:
    r = json.load(open(b, encoding="utf-8")); e = {"id": r["id"], "famille": r["_famille"], "brief": r["_brief"]}
    if r.get("_a_faire"):
        e["statut"] = "A_FAIRE"; res.append(e); print(f"  {r['id']:22s} A_FAIRE (famille {r['_famille']} pas encore construite)"); continue
    rec = {k: v for k, v in r.items() if not k.startswith("_")}
    rec["modele"] = f"modeles/{r['id']}/source/{r['id']}.blend"
    p = os.path.join("recettes", r["id"] + ".json"); json.dump(rec, open(os.path.join(D, p), "w"), indent=1)
    t0 = time.time()
    o = lancer("modeler.py", "modeler", p)
    if "MODELE :" not in o:
        e["statut"] = "ECHEC_MODELER"; e["erreur"] = next((l for l in o.splitlines() if "ERREUR" in l), o[-300:]).strip()
    else:
        o = lancer("fabriquer.py", "fabriquer", p)
        ok = [l for l in o.splitlines() if l.startswith("FABRIQUE_OK")]
        if not ok:
            e["statut"] = "ECHEC_FABRIQUER"; e["erreur"] = next((l for l in o.splitlines() if "ERREUR" in l), o[-300:]).strip()
        else:
            m = json.loads(ok[0][len("FABRIQUE_OK"):])
            e.update(statut="OK", canon=m.get("canon", {}), alertes=m.get("alertes", []), couleurs=m.get("couleurs"),
                     image=(sorted(glob.glob(os.path.join(D, "build", "sprites", r["id"], "pixel", "*_00.png"))) or [None])[0])
    e["secondes"] = round(time.time() - t0, 1); res.append(e)
    print(f"  {r['id']:22s} {e['statut']}" + (f"  {e.get('canon')}  alertes {len(e.get('alertes', []))}" if e["statut"] == "OK" else f"  {e.get('erreur', '')[:160]}"))

# ------------------------------------------------------------------ resultats + comparaison
f_res = os.path.join(D, "resultats.json"); f_av = os.path.join(D, "resultats_avant.json")
avant = {}
if os.path.exists(f_res):
    shutil.copy2(f_res, f_av)
    avant = {e["id"]: e for e in json.load(open(f_res))}
if argv and avant:   # banc partiel : les autres briefs gardent leur resultat (on compare toujours le banc ENTIER)
    nv = {e["id"]: e for e in res}
    res = [nv.get(i, e) for i, e in avant.items()] + [e for i, e in nv.items() if i not in avant]
json.dump(res, open(f_res, "w"), indent=1, ensure_ascii=False)


def score(es):
    ok = [e for e in es if e["statut"] == "OK"]
    return {"construits": len(ok), "a_faire": sum(e["statut"] == "A_FAIRE" for e in es),
            "echecs": sum(e["statut"].startswith("ECHEC") for e in es),
            "alertes": sum(len(e.get("alertes", [])) for e in ok),
            "isoles_moyen": round(float(np.mean([e["canon"].get("isoles_pct", 0) for e in ok])) if ok else 0, 2),
            "contraste_min": round(min([e["canon"].get("contraste_min", 100) for e in ok] or [0]), 1)}


s_ap = score(res); s_av = score(list(avant.values())) if avant else None

# planche : une case par brief (pixel art x3 sur fond sombre), image d'avant au-dessus si elle existe
C = 200
def case(img_path, statut, n):
    c = np.ones((C, C, 4)); c[..., :3] = (0.16, 0.17, 0.23)
    if statut == "A_FAIRE":
        c[..., :3] = (0.35, 0.3, 0.2)
    elif not statut.startswith("OK"):
        c[..., :3] = (0.45, 0.12, 0.12)
    elif img_path and os.path.exists(img_path):
        a = lire_image(img_path); h, w = a.shape[:2]; k = max(1, min(C // w, C // h))
        a = np.repeat(np.repeat(a, k, 0), k, 1); h, w = a.shape[:2]; y0, x0 = (C - h) // 2, (C - w) // 2
        al = a[..., 3:4]; c[y0:y0 + h, x0:x0 + w, :3] = c[y0:y0 + h, x0:x0 + w, :3] * (1 - al) + a[..., :3] * al
    return numeroter(c, n, k=3)

# copie des images actuelles (elles deviendront « avant » au prochain banc)
os.makedirs(os.path.join(D, "images"), exist_ok=True)
for e in res:
    if e.get("image") and os.path.exists(e["image"]) and (not argv or any(e["id"].startswith(a) for a in argv)):
        av = os.path.join(D, "images", e["id"] + ".png")
        if os.path.exists(av):
            os.makedirs(os.path.join(D, "avant"), exist_ok=True); shutil.copy2(av, os.path.join(D, "avant", e["id"] + ".png"))
        shutil.copy2(e["image"], av)
lignes = []
if avant:
    lignes.append([case(os.path.join(D, "avant", e["id"] + ".png"), avant.get(e["id"], {}).get("statut", "A_FAIRE"), i + 1)
                   for i, e in enumerate(res)])
lignes.append([case(os.path.join(D, "images", e["id"] + ".png"), e["statut"], i + 1) for i, e in enumerate(res)])
col = 8; blocs = []
for i0 in range(0, len(res), col):
    for l in lignes:
        r_ = l[i0:i0 + col] + [np.ones((C, C, 4))] * (col - len(l[i0:i0 + col]))
        blocs.append(np.concatenate(sum([[x, np.ones((C, 6, 4))] for x in r_], [])[:-1], 1))
        blocs.append(np.ones((6 if l is not lignes[-1] else 24, blocs[-1].shape[1], 4)))
planche = np.concatenate(blocs[:-1], 0)
ecrire_image(os.path.join(D, "banc.png"), planche)
# planche QUALITE : chaque sprite (grand) a cote d'exemples du niveau vise (galerie privee de Julien, jamais copiee)
PROCHE = {"creatures": ["creatures", "personnages"], "fonds": ["fonds", "decors"], "interface": ["interface", "effets", "decors"]}
def exemples(fam, n=2):
    if not GALERIE or not fam or not os.path.isdir(GALERIE):
        return []
    for d in PROCHE.get(fam, [fam]):
        fs = sorted(glob.glob(os.path.join(GALERIE, d, "*")))
        fs = [x for x in fs if x.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        if fs:
            return fs[:n]
    return []
if GALERIE:
    GAL = {json.load(open(b, encoding="utf-8"))["id"]: json.load(open(b, encoding="utf-8")).get("_galerie")
           for b in glob.glob(os.path.join(ICI, "briefs", "*.json"))}
    Q = 300; lig = []
    for i, e in enumerate(res, 1):
        im = os.path.join(D, "images", e["id"] + ".png")
        cs = [case(im, e["statut"], i)]
        cs[0] = ajuster(cs[0], Q, Q)
        for x in exemples(GAL.get(e["id"])):
            try:
                cs.append(ajuster(lire_image(os.path.abspath(x)), Q, Q))
            except Exception as ex:
                print(f"  galerie : {os.path.basename(x)} illisible ({str(ex)[:80]})")
        while len(cs) < 3:
            v = np.ones((Q, Q, 4)); v[..., :3] = 0.85; cs.append(v)
        lig.append(np.concatenate(sum([[c, np.ones((Q, 6, 4))] for c in cs], [])[:-1], 1))
    for k0 in range(0, len(lig), 5):
        bloc = lig[k0:k0 + 5]
        ecrire_image(os.path.join(D, f"qualite_{k0 // 5 + 1}.png"),
                     np.concatenate(sum([[l, np.ones((10, l.shape[1], 4))] for l in bloc], [])[:-1], 0))
    print(f"QUALITE : {D}/qualite_*.png  (a gauche le sprite, a droite le niveau vise de la meme famille)")
f_notes = os.path.join(D, "notes.json")
if os.path.exists(f_notes):   # notes de Julien (1 a 5 par brief) : le vrai critere de qualite
    nt = json.load(open(f_notes)); vals = [v for v in nt.values() if isinstance(v, (int, float))]
    if vals:
        s_ap["note_julien"] = round(sum(vals) / len(vals), 2)
else:
    json.dump({e["id"]: None for e in res}, open(f_notes, "w"), indent=1)
print("\nBANC_OK " + json.dumps(s_ap, ensure_ascii=False))
if s_av:
    print("AVANT   " + json.dumps(s_av, ensure_ascii=False))
    mieux = (s_ap["construits"], -s_ap["echecs"], -s_ap["alertes"]) >= (s_av["construits"], -s_av["echecs"], -s_av["alertes"])
    print("VERDICT DES MESURES : " + ("au moins aussi bon -> regarde la planche (Julien juge)" if mieux else "MOINS BON -> rejette le changement"))
print(f"REGARDE : {D}/banc.png  (une case par brief, dans l'ordre ; si un « avant » existe : ligne du haut = avant ;"
      " brun = famille a faire, rouge = echec)")
for i, e in enumerate(res, 1):
    print(f"  {i:2d} {e['id']} : {e['brief']}")
