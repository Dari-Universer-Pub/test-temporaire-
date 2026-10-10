"""references : planche numerotee d'images de REFERENCE libres pour un sujet (Openverse : Wikimedia Commons, musees,
Flickr sous licences Creative Commons), avec source et licence. On s'en INSPIRE et on MESURE, on ne copie jamais.
    usine references "<sujet en anglais>" [--pixel] [--famille <f>]  -> references/<sujet>/planche.png + sources.json
      --pixel : ajoute quelques exemples PIXEL ART libres (numeros bleus) : pour voir comment on SIMPLIFIE le sujet
                (un oeil en 2 pixels, un reflet), jamais pour copier un style. La forme vient des images reelles.
    usine choisir_references "<sujet>" <n> [<n> ...]   -> garde 2 ou 3 images + leurs reperes (couleurs, contraste)
Galerie « qualite » privee (exemples du niveau vise, JAMAIS dans le kit) : "galerie_qualite": "<dossier sur ta machine>"
dans usine_projet.json -> ses images s'ajoutent a la planche (numeros jaunes). Rangee en sous-dossiers par FAMILLE
(personnages, creatures, decors, tuiles, fonds, effets, interface) : --famille <f> montre celle de l'asset (8 images au plus)."""
import os, sys, json, re, glob, shutil
import bpy
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import http, lire_image, ecrire_image, numeroter, grille, ajuster

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv or argv[0] not in ("chercher", "choisir") or len(argv) < 2:
    raise SystemExit("usage : usine references \"<sujet>\"   |   usine choisir_references \"<sujet>\" <n> [<n> ...]")
OPTS = argv[2:]
PIXEL = "--pixel" in OPTS
FAMILLE = OPTS[OPTS.index("--famille") + 1] if "--famille" in OPTS and OPTS.index("--famille") + 1 < len(OPTS) else None
SUJET = argv[1].strip()
SLUG = re.sub(r"[^a-z0-9]+", "_", SUJET.lower()).strip("_") or "sujet"
DOS = os.path.join("references", SLUG)


def projet():
    for d in (".", ".."):
        p = os.path.join(d, "usine_projet.json")
        if os.path.exists(p):
            try:
                return json.load(open(p, encoding="utf-8-sig"))
            except Exception:
                return {}
    return {}


def couleurs_dominantes(a, k=5):
    """k couleurs dominantes (k-moyennes simples) + contraste (ecart des luminosites)."""
    px = a[..., :3].reshape(-1, 3)[:: max(1, a.shape[0] * a.shape[1] // 6000)]
    rnd = np.random.default_rng(1); c = px[rnd.choice(len(px), k, replace=False)]
    for _ in range(12):
        lab = ((px[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        c = np.array([px[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
    part = np.bincount(lab, minlength=k) / len(lab); o = np.argsort(-part)
    lum = px @ np.array([0.299, 0.587, 0.114])
    return [{"hex": "#%02x%02x%02x" % tuple(int(v * 255) for v in c[j]), "part": round(float(part[j]), 2)} for j in o], \
        round(float(lum.std()), 3)


if argv[0] == "chercher":
    os.makedirs(DOS, exist_ok=True)
    for f in glob.glob(os.path.join(DOS, "[0-9][0-9].*")):
        os.remove(f)
    import urllib.parse
    res = []
    def openverse(q, pages):
        r_ = []
        for page in pages:   # sans compte : 20 resultats par page au plus
            url = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode({"q": q, "page_size": 20, "page": page, "mature": "false"})
            try:
                r_ += json.loads(http(url, timeout=60) or "{}").get("results", [])
            except Exception as e:
                if not r_:
                    print(f"ATTENTION : recherche impossible ({str(e)[:160]})")
                break
        return r_
    res = openverse(SUJET, (1, 2))
    if PIXEL:   # 4 exemples pixel art au plus, apres les images reelles
        # le pixel art libre est rare et les moteurs renvoient souvent autre chose : on ne garde que les images
        # marquees « pixel » (titre ou mots-cles)
        def est_pixel(r):
            return "pixel" in (r.get("title") or "").lower() or any("pixel" in (g.get("name") or "").lower() for g in r.get("tags") or [])
        px = []
        for q in (SUJET + " pixel art", SUJET + " pixel", SUJET + " sprite"):
            px += [dict(r, _pixel=True) for r in openverse(q, (1,)) if est_pixel(r) and r.get("id") not in {p.get("id") for p in px}]
            if len(px) >= 4:
                break
        if not px:
            print("ATTENTION : aucun exemple pixel art libre pour ce sujet (c'est frequent) -> regarde ta galerie qualite (--famille)")
    else:
        px = []
    sources, cases = [], []
    vus_aut, vus_tit = {}, set()
    n_px = 0
    for r in res + px:
        if r.get("_pixel"):
            if n_px >= 4:
                break
        elif len(sources) >= 10:
            continue
        aut = (r.get("creator") or "?").lower(); tit = re.sub(r"[^a-z]+", "", (r.get("title") or "").lower())[:20]
        if vus_aut.get(aut, 0) >= 2 or (tit and tit in vus_tit):   # variete : 2 images par auteur, pas de doublon
            continue
        vus_aut[aut] = vus_aut.get(aut, 0) + 1; vus_tit.add(tit)
        f = os.path.join(DOS, f"{len(sources) + 1:02d}.jpg")
        try:
            http(r.get("thumbnail") or r["url"], sortie=f, timeout=60)
            a = lire_image(f)
        except Exception:
            continue
        sources.append({"numero": len(sources) + 1, "fichier": f, "titre": r.get("title"), "auteur": r.get("creator"),
                        "licence": f"{r.get('license', '?').upper()} {r.get('license_version') or ''}".strip(),
                        "source": r.get("foreign_landing_url") or r.get("url"), "origine": r.get("source"),
                        **({"usage": "pixel art : lisibilite seulement, jamais copier"} if r.get("_pixel") else {})})
        if r.get("_pixel"):
            n_px += 1
        cases.append(numeroter(ajuster(a, 240, 240), len(sources), **({"couleur": (0.3, 0.7, 1.0)} if r.get("_pixel") else {})))
    gq = projet().get("galerie_qualite")
    if gq and os.path.isdir(gq):   # galerie privee de Julien : lue sur place, jamais copiee dans le kit
        fams = sorted(d for d in os.listdir(gq) if os.path.isdir(os.path.join(gq, d)))
        dos_g = gq
        if FAMILLE:
            if FAMILLE in fams:
                dos_g = os.path.join(gq, FAMILLE)
            else:
                print(f"ATTENTION : famille '{FAMILLE}' absente de la galerie qualite (familles : {fams or 'aucune'})")
                dos_g = None
        elif fams:
            print(f"ATTENTION : la galerie qualite est rangee par familles {fams} -> ajoute --famille <f> (sinon : images de la racine seulement)")
        imgs_g = sorted(glob.glob(os.path.join(dos_g, "*"))) if dos_g else []
        for f in [x for x in imgs_g if x.lower().endswith((".png", ".jpg", ".jpeg"))][:8]:
            if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            try:
                a = lire_image(os.path.abspath(f))
            except Exception:
                continue
            sources.append({"numero": len(sources) + 1, "fichier": os.path.abspath(f), "titre": os.path.basename(f),
                            "licence": "PRIVEE (galerie qualite : ne pas copier, ne pas publier)", "origine": "galerie_qualite"})
            cases.append(numeroter(ajuster(a, 240, 240), len(sources), couleur=(1, 0.85, 0.2)))
    if not cases:
        raise SystemExit(f"ERREUR : aucune reference trouvee pour '{SUJET}' (essaie un autre mot, en anglais : "
                         "'medieval knight armor', 'deep sea diver helmet'...). Sans internet : la galerie qualite seule.")
    ecrire_image(os.path.join(DOS, "planche.png"), grille(cases, colonnes=5, case=(240, 240)))
    json.dump(sources, open(os.path.join(DOS, "sources.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"REFERENCES_OK {len(sources)} image(s)")
    print(f"REGARDE : {DOS}/planche.png   (sources et licences : {DOS}/sources.json ; numeros jaunes = galerie qualite ;"
          " numeros bleus = pixel art, pour la lisibilite seulement)")
    print(f"Puis : usine choisir_references \"{SUJET}\" <n> <n> [<n>]   (2 ou 3 : forme, proportions, couleurs)")
else:
    fs = os.path.join(DOS, "sources.json")
    if not os.path.exists(fs):
        raise SystemExit(f"ERREUR : lance d'abord usine references \"{SUJET}\"")
    src = json.load(open(fs, encoding="utf-8")); nums = [int(x) for x in argv[2:] if x.isdigit()]
    if not nums or any(not 1 <= n <= len(src) for n in nums):
        raise SystemExit(f"ERREUR : numeros de 1 a {len(src)} (lus sur {DOS}/planche.png)")
    choix = []
    for n in nums:
        s = dict(src[n - 1]); cd, ct = couleurs_dominantes(lire_image(os.path.abspath(s["fichier"])))
        s["reperes"] = {"couleurs_dominantes": cd, "contraste": ct}; choix.append(s)
    json.dump(choix, open(os.path.join(DOS, "choix.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"CHOIX_OK {nums} -> {DOS}/choix.json (reperes : couleurs dominantes, contraste)")
    print("Sers-t'en pour : la silhouette (usine variations), les reglages du gabarit et les couleurs de la tenue ; "
          "jamais pour copier. Note la source dans le journal si l'asset s'en inspire nettement.")
