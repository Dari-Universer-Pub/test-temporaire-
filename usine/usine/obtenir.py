"""obtenir : telecharge le candidat choisi, garde la preuve de licence, et montre le VRAI modele.

    usine obtenir "<sujet>" <numero>
Sortie : modeles/<id>/  (fichiers du modele, licence.html, provenance.json, apercu.png, infos.json)
apercu.png = le modele rendu sous 4 angles (face, profil, dessus, 3/4) + ses animations listees dans infos.json.
"""
import os, sys, json, re, shutil, zipfile, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *
import bpy, math
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
if len(args) < 2 or not args[-1].isdigit():
    raise SystemExit('usage : usine obtenir "<sujet tel que tape dans chercher>" <numero>')
sujet, numero = " ".join(args[:-1]), int(args[-1])
fc = os.path.join("recherche", slug(sujet), "candidats.json")
if not os.path.isfile(fc):
    deja = sorted(os.listdir("recherche")) if os.path.isdir("recherche") else []
    raise SystemExit(f"ERREUR : pas de recherche '{sujet}'. Lance d'abord usine chercher \"{sujet}\" "
                     f"(meme texte). Recherches faites : {deja}")
d = json.load(open(fc))
c = next((x for x in d["candidats"] if x["numero"] == numero), None)
if c is None:
    raise SystemExit(f"ERREUR : pas de numero {numero} dans la planche '{sujet}' (1 a {len(d['candidats'])})")
CACHE = os.environ.get("USINE_CACHE", os.path.expanduser("~/.cache/usine"))
ident = slug(c["titre"].split("  [")[0].split("(")[0]) or f"modele_{numero}"
def _meme_modele(d):
    """le dossier contient-il deja CE candidat (meme page) ? Alors on le remplace ; sinon on ne l'ecrase jamais."""
    try:
        return json.load(open(os.path.join(d, "provenance.json"))).get("url") == c["page"] and \
            json.load(open(os.path.join(d, "provenance.json"))).get("candidat") in (None, c.get("titre"))
    except Exception:
        return not os.listdir(d)
base_ident, k_ = ident, 2
while os.path.isdir(os.path.join("modeles", ident)) and not _meme_modele(os.path.join("modeles", ident)):
    ident = f"{base_ident}_{k_}"; k_ += 1
dossier = os.path.join("modeles", ident)
if os.path.isdir(dossier):
    shutil.rmtree(dossier)
os.makedirs(dossier)
t = c["telechargement"]
PRIORITE = [".glb", ".gltf", ".blend", ".fbx", ".obj", ".usdz", ".usd", ".usdc", ".stl", ".ply", ".x3d", ".wrl", ".abc", ".dae"]


def extraire(z, vers):
    with zipfile.ZipFile(z) as f:
        f.extractall(vers)


fichier_modele = None
AUTRES = []  # autres fichiers 3D du candidat, essayes si le premier ne s'ouvre pas
if t["type"] == "itch":
    exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "chercher.py")).read().split("\n# ------------------------------------------------------------------ main")[0])
    src = os.path.join(CACHE, "packs", slug(t["page"]) + "_" + slug(t["fichier"]))
    if not os.path.exists(os.path.join(src, ".complet")):
        # telechargement dans un dossier temporaire puis renommage : un pack coupe ou en cours ailleurs n'est jamais pris
        import time as _t
        tmp = f"{src}.tmp{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        f = next(x for x in itch_fichiers(t["page"]) if x["nom"] == t["fichier"])
        z = os.path.join(tmp, "_pack.zip")
        print("telechargement du pack", t["fichier"], "...", flush=True)
        http(f["url"], sortie=z, timeout=1800)
        extraire(z, tmp)
        open(os.path.join(tmp, ".complet"), "w").write("ok")
        if os.path.exists(os.path.join(src, ".complet")):  # un autre telechargement a fini avant
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            shutil.rmtree(src, ignore_errors=True)
            os.replace(tmp, src)
    membre = os.path.join(src, t["membre"])
    rep = os.path.dirname(membre)
    # le modele + tout son dossier (textures, .bin...) ; les textures d'un dossier voisin aussi
    shutil.copytree(rep, os.path.join(dossier, "source"), dirs_exist_ok=True)
    for voisin in glob.glob(os.path.join(os.path.dirname(rep), "*[Tt]extur*")):
        if os.path.isdir(voisin):
            shutil.copytree(voisin, os.path.join(dossier, os.path.basename(voisin)), dirs_exist_ok=True)
    fichier_modele = os.path.join(dossier, "source", os.path.basename(membre))
    sha = sha256(os.path.join(src, "_pack.zip"))
elif t["type"] == "polyhaven":
    files = json.loads(http(f"https://api.polyhaven.com/files/{t['id']}"))
    g = files["gltf"]["1k"]["gltf"]
    os.makedirs(os.path.join(dossier, "source"))
    fichier_modele = os.path.join(dossier, "source", os.path.basename(g["url"]))
    http(g["url"], sortie=fichier_modele)
    for rel, inc in g.get("include", {}).items():
        p = os.path.join(dossier, "source", rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        http(inc["url"], sortie=p)
    sha = sha256(fichier_modele)
elif t["type"] == "fichiers":
    rep = os.path.join(dossier, "source"); os.makedirs(rep)
    for u in t["urls"]:
        p = os.path.join(rep, urllib.parse.unquote(os.path.basename(u)))
        http(u, sortie=p, timeout=1800)
        if p.lower().endswith(".zip"):
            extraire(p, rep)
        elif p.lower().endswith((".tar.gz", ".tgz", ".tar")):
            import tarfile
            with tarfile.open(p) as tf:
                tf.extractall(rep, filter="data")
    for z_ in glob.glob(os.path.join(rep, "**", "*.zip"), recursive=True):  # zips dans le zip
        if os.path.abspath(z_) != os.path.abspath(p):
            try:
                extraire(z_, os.path.dirname(z_))
            except Exception:
                pass
    sha = sha256(p)
elif t["type"] == "sketchfab":
    j = json.loads(http(f"https://api.sketchfab.com/v3/models/{t['uid']}/download"))
    if "gltf" not in j:
        raise SystemExit("Sketchfab refuse le telechargement (jeton absent, faux ou revoque : verifie usine_jetons.json). "
                         "Choisis un autre numero ou corrige le jeton. Reponse : " + json.dumps(j)[:200])
    rep = os.path.join(dossier, "source"); os.makedirs(rep)
    z = os.path.join(rep, "_sketchfab.zip"); http(j["gltf"]["url"], sortie=z, timeout=1800); extraire(z, rep)
    sha = sha256(z)

if fichier_modele is None:
    cands = [p for p in glob.glob(os.path.join(dossier, "source", "**", "*"), recursive=True)
             if os.path.splitext(p)[1].lower() in PRIORITE]
    ms = [m for m in re.split(r"\W+", sujet.lower()) if len(m) >= 3]
    cands.sort(key=lambda p: (-sum(m in os.path.basename(p).lower() for m in ms),
                              PRIORITE.index(os.path.splitext(p)[1].lower())))
    if not cands:
        raise SystemExit("aucun fichier 3D dans ce candidat : choisis un autre numero")
    fichier_modele, AUTRES = cands[0], cands[1:]

# preuve de licence
try:
    http(c["page"], sortie=os.path.join(dossier, "licence.html"))
except Exception:
    pass
sha = sha256(fichier_modele)  # le SHA-256 du fichier cite (verifie par le controle du kit)
ap = sorted(glob.glob(os.path.join("recherche", slug(sujet), "apercus", f"{numero:02d}.*")))
if ap:
    shutil.copyfile(ap[0], os.path.join(dossier, "vignette_officielle" + os.path.splitext(ap[0])[1]))
prov = {"id": ident, "type": "modele3d", "url": c["page"], "licence": c["licence"], "auteur": c["auteur"],
        "fichier": fichier_modele, "sha256": sha, "page_licence": os.path.join(dossier, "licence.html"),
        "source": c["source"], "candidat": c.get("titre")}
json.dump(prov, open(os.path.join(dossier, "provenance.json"), "w"), indent=1, ensure_ascii=False)

# ------------------------------------------------- apercu reel du modele
bpy.ops.wm.read_factory_settings(use_empty=True)
import geometrie as _G
for essai in [fichier_modele] + AUTRES:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        _G.importer(essai)
        if essai != fichier_modele:
            print(f"  ({os.path.basename(fichier_modele)} ne s'ouvre pas : {os.path.basename(essai)} pris a la place)")
            fichier_modele = essai
        break
    except SystemExit as e:
        err = str(e)
else:
    raise SystemExit(f"{err}\nLe modele est telecharge dans {dossier} mais aucun de ses fichiers ne s'ouvre : choisis un autre numero.")
if prov["fichier"] != fichier_modele:
    prov["fichier"] = fichier_modele; prov["sha256"] = sha256(fichier_modele)
    json.dump(prov, open(os.path.join(dossier, "provenance.json"), "w"), indent=1, ensure_ascii=False)
scene = bpy.context.scene
n_rep = reparer_textures(dossier)
if n_rep:
    print(f"  textures reparees automatiquement : {n_rep}")
meshes = [o for o in scene.objects if o.type == "MESH" and _G.visible(o)]
bpy.context.view_layer.update()
pts = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in meshes])
lo, hi = pts.min(0), pts.max(0); centre = (lo + hi) / 2; taille = float((hi - lo).max())
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.light = "STUDIO"; scene.display.shading.color_type = "TEXTURE"
scene.display.shading.show_shadows = True; scene.display.shading.show_cavity = True
scene.render.film_transparent = True
scene.render.resolution_x = scene.render.resolution_y = 320
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam)
cam.data.type = "ORTHO"; cam.data.ortho_scale = taille * 1.15; cam.data.clip_end = taille * 20
scene.camera = cam
vues = {"face": (0, -1, 0), "profil": (-1, 0, 0), "dessus": (0, -0.0001, 1), "trois_quarts": (-1, -1, 0.8)}
images = []
for nom, v in vues.items():
    v = Vector(v).normalized()
    cam.location = Vector(centre) + v * taille * 5
    cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
    p = os.path.join(dossier, f"_vue_{nom}.png"); scene.render.filepath = p
    bpy.ops.render.render(write_still=True)
    images.append(ajuster(lire_image(p), 320, 320, fond=(0.75, 0.8, 0.85)))
    os.remove(p)
ecrire_image(os.path.join(dossier, "apercu.png"), grille(images, colonnes=4, case=(320, 320)))
sat = saturation_moyenne(np.concatenate([i.reshape(-1, 4) for i in images])[None])
infos = {"id": ident, "fichier": fichier_modele, "dimensions_m": [round(float(x), 3) for x in hi - lo],
         "objets": [o.name for o in meshes], "materiaux": sorted({m.name for o in meshes for m in o.data.materials if m}),
         "armature": any(o.type == "ARMATURE" for o in scene.objects),
         "animations": sorted(a.name for a in bpy.data.actions if courbes_action(a)),
         "animations_vides": sorted(a.name for a in bpy.data.actions if not courbes_action(a)),
         "vues_apercu": list(vues), "saturation": round(sat, 3), "gris": sat < 0.08}
json.dump(infos, open(os.path.join(dossier, "infos.json"), "w"), indent=1, ensure_ascii=False)
print(f"\nMODELE OBTENU : {dossier}")
print(f"  REGARDE : {dossier}/apercu.png  (vues : face, profil, dessus, 3/4)")
print(f"  fichier : {fichier_modele}")
print(f"  animations : {infos['animations'] or 'aucune (animation procedurale possible)'}")
print(f"  materiaux : {infos['materiaux']}")
if infos["gris"]:
    print("  ATTENTION : modele GRIS (pas de couleurs/textures). Soit tu choisis un autre numero,")
    print("              soit tu donnes ses couleurs dans la recette (\"couleurs\": {materiau: \"#hex\"}).")
print(f"  provenance : {dossier}/provenance.json (licence {c['licence']}, auteur {c['auteur']})")
