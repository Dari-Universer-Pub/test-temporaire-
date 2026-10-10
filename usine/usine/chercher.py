"""chercher : trouve des modeles 3D CC0 pour un sujet, sur plusieurs sources, et fait une planche numerotee.

    usine chercher "shark requin" [--max 20]
Sortie : recherche/<sujet>/candidats.json + recherche/<sujet>/planche.png (vignettes numerotees)
Ensuite : usine obtenir <sujet> <numero>

Sources (licence CC0 uniquement, verifiee par la source) :
  - Poly Haven (API officielle)
  - OpenGameArt (recherche filtree 3D + CC0)
  - packs itch.io de createurs 100 % CC0 (Quaternius, KayKit, Kenney) : le contenu des zips est indexe
    en lisant seulement leur sommaire (requete partielle), une fois, puis mis en cache
  - Sketchfab, seulement si un jeton est fourni (usine_jetons.json du projet ou SKETCHFAB_TOKEN)
"""
import os, sys, json, re, html, struct, time, subprocess
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *

CACHE = os.environ.get("USINE_CACHE", os.path.expanduser("~/.cache/usine"))
os.makedirs(CACHE, exist_ok=True)
CREATEURS_CC0 = ["quaternius", "kaylousberg", "kenney"]
ACCESSOIRES = {"bow", "arrow", "arrows", "quiver", "sword", "axe", "staff", "shield", "helmet", "hood", "cowl", "cloak", "hat",
               "spellbook", "book", "broken", "half", "weapon", "weapons", "dagger", "spear", "mace", "crossbow", "wand", "cape",
               "head", "skull", "hair", "beard", "accessory", "accessories", "prop", "props", "armor", "armour"}
EXT3D = (".glb", ".gltf", ".blend", ".fbx", ".obj", ".dae", ".stl", ".ply", ".usdz", ".usd", ".usdc", ".x3d", ".wrl", ".abc")


# ------------------------------------------------------------------ itch
def itch_packs(createur):
    t = http(f"https://{createur}.itch.io/")
    packs = []
    # cellule d'un jeu : balise <div> avec class="game_cell..." ET data-game_id, dans N'IMPORTE QUEL ordre
    # (itch.io sert les deux ordres selon les machines)
    for m in re.finditer(r'<div(?=[^>]*\bclass="game_cell[\s"])(?=[^>]*\bdata-game_id="(\d+)")[^>]*>.*?</div></div>', t, re.S):
        bloc = m.group(0)
        url = re.search(r'href="(https://[^"]+)"', bloc)
        titre = re.search(r'class="title game_link"[^>]*>([^<]+)<', bloc)
        img = re.search(r'data-lazy_src="([^"]+)"', bloc) or re.search(r'<img[^>]+src="([^"]+)"', bloc)
        if url and titre:
            packs.append({"url": url.group(1), "titre": html.unescape(titre.group(1)), "image": img.group(1) if img else None})
    vus = set(); res = []
    for p in packs:
        if p["url"] not in vus:
            vus.add(p["url"]); res.append(p)
    return res


def itch_fichiers(page):
    """URLs directes des fichiers d'un pack gratuit (meme parcours que le bouton 'telecharger')."""
    jar = os.path.join(CACHE, "jar_" + slug(page))
    t = http(page, jar=jar)
    tok = re.search(r'name="csrf_token" value="([^"]+)"', t)
    if not tok:
        return []
    r = json.loads(http(page + "/download_url", data={"csrf_token": tok.group(1)}, jar=jar))
    h = http(r["url"], jar=jar)
    tok2 = re.search(r'name="csrf_token" value="([^"]+)"', h).group(1)
    out = []
    for up in sorted(set(re.findall(r'data-upload_id="(\d+)"', h))):
        nom = re.search(rf'data-upload_id="{up}".{{0,600}}?title="([^"]+)"', h, re.S)
        j = json.loads(http(f"{page}/file/{up}?source=game_download", data={"csrf_token": tok2}, jar=jar))
        if "url" in j:
            out.append({"upload": up, "nom": nom.group(1) if nom else f"{up}.zip", "url": j["url"]})
    return out


def zip_sommaire(url):
    """Noms des fichiers d'un zip distant en ne lisant que sa fin (requetes HTTP partielles)."""
    def plage(a, b):
        r = subprocess.run(["curl", "-sSL", "--max-time", "120", "-r", f"{a}-{b}", url], capture_output=True)
        return r.stdout
    tete = subprocess.run(["curl", "-sSL", "--max-time", "60", "-r", "0-0", "-D", "-", "-o", os.devnull, url],
                          capture_output=True).stdout.decode(errors="replace")
    tailles = re.findall(r"(?i)content-range:\s*bytes\s+\d+-\d+/(\d+)", tete)
    if not tailles:
        return []
    taille = int(tailles[-1])
    fin = plage(max(0, taille - 65557), taille - 1)
    i = fin.rfind(b"PK\x05\x06")
    if i < 0:
        return []
    cd_taille, cd_debut = struct.unpack("<II", fin[i + 12:i + 20])
    cd = plage(cd_debut, cd_debut + cd_taille - 1)
    noms, j = [], 0
    while j + 46 <= len(cd) and cd[j:j + 4] == b"PK\x01\x02":
        ln, le, lc = struct.unpack("<HHH", cd[j + 28:j + 34])
        noms.append(cd[j + 46:j + 46 + ln].decode("utf-8", errors="replace"))
        j += 46 + ln + le + lc
    return noms


def index_itch():
    p = os.path.join(CACHE, "index_itch.json")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 30 * 86400:
        try:
            idx = json.load(open(p))
        except Exception:
            idx = []
        if idx:  # un index vide (page itch mal lue, coupure) n'est jamais reutilise
            return idx
    print("Premiere recherche : indexation des packs CC0 itch.io (quelques minutes, une seule fois)...", flush=True)
    packs = []
    for c in CREATEURS_CC0:
        try:
            for pk in itch_packs(c):
                pk["createur"] = c; packs.append(pk)
        except Exception as e:
            print("  createur ignore", c, e)

    def un(pk):
        try:
            fichiers = itch_fichiers(pk["url"])
            for f in fichiers:
                if f["nom"].lower().endswith(".zip"):
                    f["contenu"] = [n for n in zip_sommaire(f["url"]) if n.lower().endswith(EXT3D)]
                f.pop("url", None)  # URL temporaire : on la redemande au telechargement
            pk["fichiers"] = fichiers
        except Exception as e:
            pk["fichiers"] = []; pk["erreur"] = str(e)[:200]
        return pk
    with ThreadPoolExecutor(6) as ex:
        packs = list(ex.map(un, packs))
    if not any(pk.get("fichiers") for pk in packs):
        print(f"  ATTENTION : {len(packs)} pack itch.io lisible : itch.io ignore pour cette recherche (index NON garde, "
              "il sera refait a la prochaine recherche). Les autres sources sont utilisees.", flush=True)
        return packs
    json.dump(packs, open(p, "w"), indent=0)
    print(f"  {len(packs)} packs indexes", flush=True)
    return packs


# --------------------------------------------------------------- sources
def mots(q):
    return [m for m in re.split(r"[\s,]+", q.lower()) if len(m) >= 3]


def score(texte, ms):
    """3 = mot entier (bear dans character_bear), 2 = debut de mot (bears, beartrap), 1 = ailleurs dans le texte."""
    t = texte.lower(); mots_t = jetons(texte)
    def un(m):
        if m in mots_t or m + "s" in mots_t or m + "es" in mots_t: return 3
        return 1 if m in t else 0  # foxtail, catfish, carrot, beartrap : un AUTRE mot qui commence pareil
    return sum(un(m) for m in ms)


def jetons(texte):
    """mots d'un titre : coupe aussi les noms colles (ChickenCoop -> chicken coop, Statue_Horse -> statue horse)."""
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", texte)
    t = re.sub(r"([A-Za-z])(\d)", r"\1 \2", t)  # Fish1 -> fish 1
    return [x for x in re.split(r"[^a-z0-9]+", t.lower()) if x]


# mots qui disent que le candidat N'EST PAS le sujet lui-meme (une partie, un objet qui le represente, un piege...)
HORS_SUJET = {"statue", "statuette", "netsuke", "carving", "sculpture", "figurine", "fossil", "vessel", "bowl", "tureen",
              "vase", "jar", "box", "relief", "plaque", "medal", "coin", "cross", "brooch", "pendant", "jaw", "skull", "skin",
              "trap", "coop", "gibs", "debris", "broken", "pile", "holder", "wallmount", "mount", "roof", "fork", "knife",
              "toy", "scroll", "mask", "head", "skelton", "skeleton", "bones", "bone", "wing", "wings", "feet", "foot", "hand", "hands", "leg", "legs", "arm", "arms", "tail", "horn", "horns", "claw", "claws", "shoes", "shoe", "boots", "capital", "panel", "motif", "tent", "stall", "decal", "plate", "spoon", "cup", "mug", "glass", "frame", "costume", "drawn", "carriage", "kit", "pack", "set"}
MUSEE = re.compile(r"\b(\d{1,2}(st|nd|rd|th)[- ]?c(entury)?|bce|\d{4}\.\d+|museum|ancient|antique|dynasty|cabinet|jesus|christ|virgin|"
                   r"our lady|saint|st\.? [A-Z][a-z]+|god|goddess|deity|deified|buddha|heraldic|reliquary|ivory|cartouche|people|cave|"
                   r"uss|hms|sculpture|carved|engraved|cellar|figure of|kore|olmec|tomb|\d{4}s)\b"
                   r"|\bc\. ?\d{3,4}|\b\d{3,4}\s*(-\s*\d{3,4})?\s*(bc|ad|ce)\b", re.I)


# mots techniques d'un titre : ni le sujet ni un autre objet (Camel basemesh, Lighthouse Scene, Monkey 3D model. Rigged)
MOTS_TECHNIQUES = {"cc0", "low", "poly", "lowpoly", "model", "models", "3d", "animated", "animation", "rigged", "rigging", "rig",
                   "basemesh", "base", "mesh", "scene", "textured", "untextured", "pbr", "fbx", "obj", "blend", "blender", "gltf",
                   "glb", "game", "ready", "asset", "assets", "free", "stylized", "simple", "version", "v1", "v2", "v3", "hd",
                   "hq", "lp", "voxel", "sculpt", "and", "the", "a", "an", "with", "made", "by", "in", "new", "old"}


def ajuster_pertinence(c, ms):
    """baisse les candidats qui ne sont pas le sujet (objet de musee, piece detachee, objet qui contient le mot)."""
    tj = set(jetons(c["titre"].split(" (")[0] if c["source"].startswith("itch") else c["titre"]))
    if (tj & HORS_SUJET) - set(ms):
        c["score"] -= 3
    if MUSEE.search(c["titre"]):
        c["score"] -= 3
    if c["source"].startswith("itch"):  # dans un pack : le nom le plus court est le sujet seul (Tree_1 avant DeadTree_1)
        en_plus = [x for x in tj if not x.isdigit() and x not in ms and x.rstrip("s") not in ms]
        c["score"] -= 0.6 * min(len(en_plus), 4)
    if "LOURD" in c["titre"]:  # scan a plus d'un million de faces : mauvais pour du pixel art
        c["score"] -= 2
    emo = {"\U0001F41F": "fish", "\U0001F421": "fish", "\U0001F420": "fish", "\U0001F98B": "butterfly", "\U0001F41B": "worm"}
    for e, nature in emo.items():  # emoji du scan = ce qu'est VRAIMENT l'animal (parrot -> poisson-perroquet)
        if e in c["titre"] and nature not in ms and not ({"poisson", "papillon"} & set(ms)):
            c["score"] -= 4
    sans_pack = c["titre"].split(" (")[0] if c["source"].startswith("itch") else c["titre"]
    jt = [x for x in jetons(sans_pack) if not x.isdigit() and x not in ("cc0", "low", "poly", "lowpoly", "model", "3d", "animated", "rigged")]
    LIBRES = {"character", "char", "prop", "big", "small", "large", "medium", "old", "wooden", "wood", "stone", "metal", "iron",
              "gold", "golden", "silver", "simple", "cute", "toon", "loot", "tree", "sports", "a", "the", "my", "female", "male", "giant"}
    est = lambda x: any(x == m or x == m + "s" or x == m + "es" for m in ms)
    if jt and any(est(x) for x in jt):
        if c["source"].startswith("itch"):  # noms de pack : Sujet_Variante (Table_Large) ; Autre_Sujet (Anvil_Log) = pas le sujet
            if not est(jt[0]) and jt[0] not in LIBRES:
                c["score"] -= 2
        else:  # titres anglais : le dernier nom est le sujet (Angel Wing = une aile) ; "X of/from/as Y" = X
            coupe = re.split(r"\s(?:of|from|as|with|for|by)\s|[,|(\[]", re.sub(r"^\s*cc0\s+", "", sans_pack, flags=re.I), maxsplit=1, flags=re.I)
            tete = [x for x in jetons(coupe[0]) if not x.isdigit() and x not in MOTS_TECHNIQUES]
            if tete and not est(tete[-1]) and tete[-1] not in HORS_SUJET:
                c["score"] -= 3
    # sujet en plusieurs mots (fishing rod, tent pole) : bonus si les mots se suivent dans le titre
    tl = " ".join(jetons(c["titre"]))
    for a_, b_ in zip(ms, ms[1:]):
        if f"{a_} {b_}" in tl or f"{a_}{b_}" in tl.replace(" ", ""):
            c["score"] += 3
    c["mot_exact"] = any(m in tj or m + "s" in tj or m + "es" in tj for m in ms)
    if not c["mot_exact"]:
        c["score"] -= 2


def src_itch(ms):
    res = []
    for pk in index_itch():
        for f in pk.get("fichiers", []):
            for n in f.get("contenu", []):
                base = os.path.splitext(os.path.basename(n))[0]
                s = score(base, ms) * 2 + score(pk["titre"], ms)
                # dans un pack, les accessoires (arc, casque, fleche...) portent souvent le nom du sujet :
                # ils passent apres le sujet lui-meme, sauf si la recherche les demande
                mots_base = set(jetons(base))
                if ((mots_base & ACCESSOIRES) or re.search(r"(arm|leg|hand|foot|head)_?(left|right|l|r)\b", base.lower())) \
                        and not (set(ms) & ACCESSOIRES):
                    s -= 4
                if re.search(r"charact|personnage|/chars?/", n.lower()):
                    s += 2
                if s >= 3:
                    res.append({"source": "itch:" + pk["createur"], "titre": f"{base} ({pk['titre']})", "score": s + 1,
                                "licence": "CC0", "auteur": pk["createur"], "page": pk["url"], "apercu": pk["image"],
                                "telechargement": {"type": "itch", "page": pk["url"], "fichier": f["nom"], "membre": n}})
    # un seul format par modele : on prefere glb/gltf > blend > fbx > obj
    ordre = {".glb": 0, ".gltf": 0, ".blend": 1, ".fbx": 2, ".obj": 3, ".dae": 4}
    meilleurs = {}
    for r in res:
        cle = (r["page"], os.path.splitext(os.path.basename(r["telechargement"]["membre"]))[0].lower())
        e = os.path.splitext(r["telechargement"]["membre"])[1].lower()
        if cle not in meilleurs or ordre.get(e, 9) < ordre.get(os.path.splitext(meilleurs[cle]["telechargement"]["membre"])[1].lower(), 9):
            meilleurs[cle] = r
    return list(meilleurs.values())


def src_polyhaven(ms):
    d = json.loads(http("https://api.polyhaven.com/assets?t=models"))
    res = []
    for k, v in d.items():
        s = score(" ".join([k, v.get("name", "")] + v.get("tags", []) + v.get("categories", [])), ms)
        if s >= 3:
            res.append({"source": "polyhaven", "titre": v.get("name", k), "score": s, "licence": "CC0",
                        "auteur": ", ".join(v.get("authors", {}).keys()), "page": f"https://polyhaven.com/a/{k}",
                        "apercu": f"https://cdn.polyhaven.com/asset_img/thumbs/{k}.png?width=256&height=256",
                        "telechargement": {"type": "polyhaven", "id": k}})
    return res


def src_oga(ms):
    pages = []
    for m in ms:  # un mot a la fois (les requetes melangeant anglais/francais ne renvoient rien)
        t = http(f"https://opengameart.org/art-search-advanced?keys={urllib.parse.quote(m)}&field_art_type_tid%5B%5D=10"
                 f"&field_art_licenses_tid%5B%5D=4&items_per_page=24")
        pages += [p for p in re.findall(r'href="(/content/[a-z0-9-]+)"', t) if p != "/content/faq"]
    pages = list(dict.fromkeys(pages))[:12]

    def un(p):
        try:
            h = http("https://opengameart.org" + p)
        except Exception:
            return None
        titre = re.search(r"<title>([^|<]+)", h)
        lic = re.search(r"License\(s\):(.{0,1500}?)</div>\s*</div>", h, re.S)
        lic_txt = re.sub("<[^>]+>", " ", lic.group(1)) if lic else ""
        if "CC0" not in lic_txt:
            return None
        fichiers = [f for f in re.findall(r'href="(https://opengameart\.org/sites/default/files/[^"]+)"', h)
                    if f.lower().endswith(EXT3D + (".zip", ".tar.gz", ".tgz", ".tar"))]  # .7z/.rar : illisibles sans outil externe
        imgs = [i for i in re.findall(r'(https://opengameart\.org/sites/default/files/(?:styles/medium/public/)?[^"\']+\.(?:png|jpg|jpeg|gif))', h)
                if "css" not in i and "license_images" not in i and "/misc/" not in i]  # badge CC0 != image du modele
        auteur = re.search(r'Author:.{0,300}?<a[^>]*>([^<]+)</a>', h, re.S)
        def utile(f):  # un zip sans aucun fichier 3D lisible (format d'un autre logiciel) ne sert a rien
            if f.lower().endswith(".dae"):
                return False  # Collada : plus lu par Blender 5
            if not f.lower().endswith(".zip"):
                return True
            try:
                return any(n.lower().endswith(tuple(e for e in EXT3D if e != ".dae") + (".zip",)) for n in zip_sommaire(f))
            except Exception:
                return True  # sommaire illisible : on laisse obtenir essayer
        fichiers = [f for f in fichiers if utile(f)]
        if not fichiers:
            return None
        return {"source": "opengameart", "titre": html.unescape(titre.group(1).strip()) if titre else p, "score": score(p, ms) + 2,
                "licence": "CC0", "auteur": auteur.group(1) if auteur else "?", "page": "https://opengameart.org" + p,
                "apercu": imgs[0] if imgs else None, "telechargement": {"type": "fichiers", "urls": fichiers}}
    with ThreadPoolExecutor(6) as ex:
        return [r for r in ex.map(un, pages) if r]


def src_sketchfab(ms):
    if not jeton_sketchfab():
        print("  sketchfab : desactive (optionnel : jeton dans usine_jetons.json, voir LISEZMOI)", flush=True)
        return []
    vus, res = set(), []
    # un mot a la fois, puis la requete entiere : Sketchfab exige TOUS les mots (anglais + francais melanges -> 0 resultat)
    for q in list(dict.fromkeys(ms + [" ".join(ms)])):
        d = json.loads(http(f"https://api.sketchfab.com/v3/search?type=models&q={urllib.parse.quote(q)}&downloadable=true&license=cc0&count=24"))
        for r in d.get("results", []):
            if r["uid"] in vus:
                continue
            vus.add(r["uid"])
            imgs = sorted(r.get("thumbnails", {}).get("images", []), key=lambda i: abs(i["width"] - 256))
            faces = int(r.get("faceCount") or 0)
            lourd = faces > 300000  # scans/photogrammetrie : tres lourds, peu lisibles en pixel art
            res.append({"source": "sketchfab", "titre": r["name"] + (f"  [LOURD : {faces // 1000}k faces]" if lourd else ""),
                        "score": score(r["name"], ms) + min(1, score(" ".join(t["name"] for t in r.get("tags", [])), ms))
                        + 1 + (2 if r.get("animationCount") else 0) - (4 if lourd else 0), "faces": faces,
                        "licence": "CC0", "auteur": r["user"]["username"], "page": r["viewerUrl"],
                        "apercu": imgs[0]["url"] if imgs else None, "anime": bool(r.get("animationCount")),
                        "telechargement": {"type": "sketchfab", "uid": r["uid"]}})
    return res


# ------------------------------------------------------------------ main
def main():
    args = sys.argv[sys.argv.index("--") + 1:]
    nmax = 20
    if "--max" in args:
        i = args.index("--max"); nmax = int(args[i + 1]); del args[i:i + 2]
    sujet = " ".join(args)
    ms = mots(sujet)
    dossier = os.path.join("recherche", slug(sujet))
    os.makedirs(os.path.join(dossier, "apercus"), exist_ok=True)
    tous = []
    for nom, f in [("itch", src_itch), ("polyhaven", src_polyhaven), ("opengameart", src_oga), ("sketchfab", src_sketchfab)]:
        try:
            r = f(ms); tous += r; print(f"  {nom} : {len(r)} resultat(s)", flush=True)
        except Exception as e:
            print(f"  {nom} : indisponible ({str(e)[:120]})", flush=True)
    for c in tous:
        ajuster_pertinence(c, ms)
    tous.sort(key=lambda r: -r["score"])
    tous = tous[:nmax]
    if tous and (not any(c["mot_exact"] for c in tous[:5]) or tous[0]["score"] < 3):
        print(f"\n  ATTENTION : aucun des premiers candidats ne porte le nom du sujet ({', '.join(ms)}) : sans doute AUCUN bon "
              "modele libre. Essaie un autre mot anglais (synonyme), ou usine gabarit, ou construis-le avec modeler.")
    vignettes = []
    for i, c in enumerate(tous, 1):
        c["numero"] = i
        img = np.ones((256, 256, 4)) * 0.85
        if c.get("apercu") and not os.environ.get("USINE_SANS_APERCUS"):  # TESTS SEULEMENT
            p = os.path.join(dossier, "apercus", f"{i:02d}" + os.path.splitext(urllib.parse.urlparse(c["apercu"]).path)[1][:5])
            try:
                http(c["apercu"], sortie=p); img = ajuster(lire_image(p), 256, 256)
            except Exception:
                pass
        vignettes.append(numeroter(img, i))
    json.dump({"sujet": sujet, "candidats": tous}, open(os.path.join(dossier, "candidats.json"), "w"), indent=1, ensure_ascii=False)
    if vignettes:
        ecrire_image(os.path.join(dossier, "planche.png"), grille(vignettes))
    print(f"\n{len(tous)} candidat(s) pour '{sujet}'. REGARDE : {dossier}/planche.png")
    for c in tous:
        print(f"  {c['numero']:>2}. {c['titre'][:70]}  [{c['source']}]")
    print(f"Puis : usine obtenir \"{sujet}\" <numero>")


main()
