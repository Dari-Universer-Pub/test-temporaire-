"""accessoire : poser un accessoire (casque, chapeau, arme...) sur un personnage UNIQUEMENT par choix numerotes.

    usine accessoire recettes/<id>.json          -> planche de l'etape en cours (numerotee)
    usine accessoire recettes/<id>.json <numero> -> applique le choix et montre l'etape suivante

Dans la recette, l'IA ecrit seulement :  "accessoires": [{"modele": "modeles/.../casque.obj", "os": "tete"}]
(+ "couleur": "#rrggbb" si le modele n'a pas de couleur). Etapes : orientation (6) -> face (4) -> placement (9).
Chaque case montre l'accessoire sur le personnage, de PROFIL (gauche) et de FACE (droite).
"""
import os, sys, json, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *
import bpy
from mathutils import Vector, Matrix, Euler

ARGS = sys.argv[sys.argv.index("--") + 1:]
RECETTE = ARGS[0]
CHOIX = int(ARGS[1]) if len(ARGS) > 1 else None
R = lire_recette(RECETTE)
PROJ = json.load(open("usine_projet.json")) if os.path.exists("usine_projet.json") else {}
ID = R["id"]
SORTIE = R.get("sortie", f"build/sprites/{ID}")
os.makedirs(SORTIE, exist_ok=True)
accs = R.get("accessoires", [])
ia = next((i for i, a in enumerate(accs) if not a.get("regle")), None)
if ia is None:
    raise SystemExit("Tous les accessoires sont regles. Lance : usine fabriquer " + RECETTE)
ACC = accs[ia]

ORIENTATIONS = [[0, 0, 0], [180, 0, 0], [90, 0, 0], [-90, 0, 0], [0, 90, 0], [0, -90, 0]]
FACES = [0, 90, 180, 270]
PLACEMENTS = [{"echelle": e, "hauteur": h} for h in (0.25, 0.0, -0.25) for e in (0.8, 1.0, 1.25)]
ETAPES = ["orientation", "face", "placement"]
etape = next(e for e in ETAPES if e not in ACC.get("_choix", {}))

# ------------------------------------------------- appliquer le choix demande
if CHOIX is not None:
    ch = ACC.setdefault("_choix", {})
    liste = {"orientation": ORIENTATIONS, "face": FACES, "placement": PLACEMENTS}[etape]
    if not 1 <= CHOIX <= len(liste):
        raise SystemExit(f"numero entre 1 et {len(liste)}")
    ch[etape] = liste[CHOIX - 1]
    if etape == "placement":
        ACC["regle"] = True
    json.dump(R, open(RECETTE, "w"), indent=1, ensure_ascii=False)
    print(f"choix {CHOIX} enregistre pour l'etape '{etape}'")
    if ACC.get("regle"):
        print(f"ACCESSOIRE REGLE. Lance : usine fabriquer {RECETTE}")
        sys.exit(0)
    etape = ETAPES[ETAPES.index(etape) + 1]

# ------------------------------------------------------------- scene
import geometrie as _G
importer = _G.importer

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
objets = importer(R["modele"])
for nom in R.get("cacher", []):
    for o in objets:
        if nom.lower() in o.name.lower(): o.hide_render = True
arm = next((o for o in objets if o.type == "ARMATURE"), None)
if arm: arm.data.pose_position = "REST"
bpy.context.view_layer.update()
corps = [o for o in objets if o.type == "MESH" and not o.hide_render]
nom_os = resoudre_os(arm, ACC.get("os", "tete"))
if ACC.get("os") and not nom_os:
    raise SystemExit(f"os '{ACC.get('os')}' introuvable. Os disponibles : {[b.name for b in arm.data.bones] if arm else 'aucun squelette'}")
taille0 = ACC.get("taille_m") or taille_base_accessoire(corps, nom_os)
cible0 = point_attache(arm, nom_os, taille0) if nom_os else Vector(ACC.get("decalage", [0, 0, 0]))

pieces = [o for o in importer(ACC["modele"]) if o.type == "MESH"]
for o in pieces:
    if ACC.get("couleur"):
        rgb = list(hex_rgb(ACC["couleur"]))
        img = bpy.data.images.new("acc_uni", 4, 4); img.pixels.foreach_set([*rgb, 1.0] * 16)
        mat = bpy.data.materials.new("acc_mat"); mat.use_nodes = True
        t = mat.node_tree.nodes.new("ShaderNodeTexImage"); t.image = img; mat.node_tree.nodes.active = t
        o.data.materials.clear(); o.data.materials.append(mat)
base_mw = {o.name: o.matrix_world.copy() for o in pieces}
pts = np.concatenate([np.array([base_mw[o.name] @ v.co for v in o.data.vertices]) for o in pieces])
c0 = Vector((pts.min(0) + pts.max(0)) / 2); dim0 = float((pts.max(0) - pts.min(0)).max())

def poser(orientation, face, echelle=1.0, hauteur=0.0):
    rot = Matrix.Rotation(math.radians(face), 4, "Z") @ Euler([math.radians(a) for a in orientation]).to_matrix().to_4x4()
    k = taille0 * echelle / dim0
    cible = cible0 + Vector((0, 0, hauteur * taille0))
    for o in pieces:
        o.matrix_world = Matrix.Translation(cible) @ rot @ Matrix.Scale(k, 4) @ Matrix.Translation(-c0) @ base_mw[o.name]
    bpy.context.view_layer.update()
    return cible

scene.render.engine = "BLENDER_WORKBENCH"
sh = scene.display.shading; sh.light = "STUDIO"; sh.color_type = "TEXTURE"; sh.show_shadows = True; sh.show_cavity = True
scene.render.film_transparent = True; scene.render.resolution_x = scene.render.resolution_y = 220
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam)
cam.data.type = "ORTHO"; scene.camera = cam

def vue(centre, az):
    a = math.radians(az); d = Vector((math.cos(a), math.sin(a), 0))  # direction de visee
    cam.data.ortho_scale = taille0 * 2.4
    cam.location = centre - d * 10; cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = 50
    p = os.path.join(SORTIE, f"_acc_{os.getpid()}.png"); scene.render.filepath = p
    bpy.ops.render.render(write_still=True)
    im = ajuster(lire_image(p), 220, 220, fond=(0.75, 0.82, 0.88)); os.remove(p)
    return im

ch = ACC.get("_choix", {})
if etape == "orientation":
    options = [dict(orientation=o, face=0) for o in ORIENTATIONS]
    consigne = "Choisis le numero ou l'accessoire est A L'ENDROIT (le haut en haut, il coiffe/tient bien)."
elif etape == "face":
    options = [dict(orientation=ch["orientation"], face=f) for f in FACES]
    consigne = "Choisis le numero ou l'AVANT de l'accessoire (visiere, hublot, face) regarde du meme cote que le visage."
else:
    options = [dict(orientation=ch["orientation"], face=ch["face"], **p) for p in PLACEMENTS]
    consigne = "Choisis le numero ou la TAILLE et la HAUTEUR sont justes (ni flottant, ni enfonce, proportions naturelles)."

cases = []
for n, opt in enumerate(options, 1):
    c = poser(**opt)
    centre = c - Vector((0, 0, taille0 * 0.25))
    paire = np.concatenate([vue(centre, 0), np.ones((220, 6, 4)), vue(centre, 90)], 1)
    cases.append(numeroter(paire, n, k=3))
planche = grille(cases, colonnes=3, case=(cases[0].shape[1], cases[0].shape[0]))
p = os.path.join(SORTIE, f"accessoire_{ia + 1}_{etape}.png")
ecrire_image(p, planche)
kit_iteration(ID, p, f"accessoire {os.path.basename(ACC['modele'])} sur l'os {nom_os} : etape {etape} ({len(options)} choix numerotes)")
print(f"ETAPE {ETAPES.index(etape) + 1}/3 : {etape.upper()}  (os : {nom_os}, taille de depart {taille0} m)")
print(f"REGARDE : {p}   (dans chaque case : profil a gauche, face a droite)")
print(consigne)
print(f"Puis : usine accessoire {RECETTE} <numero>")
