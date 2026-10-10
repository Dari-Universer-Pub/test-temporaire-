"""fabriquer : recette JSON -> sprites pixel art (toutes vues, toutes palettes, animations du modele ou procedurales).

    usine fabriquer recettes/<id>.json            -> sprites + planche + mesures
    usine variantes recettes/<id>.json            -> planche numerotee de reglages a comparer
    usine choisir   recettes/<id>.json <numero>   -> ecrit le reglage choisi dans la recette

Recette minimale :
  {"id": "chevalier", "modele": "modeles/knightcharacter/source/KnightCharacter.blend",
   "vue": "cote", "taille_px": 32, "palette": "auto",
   "animations": {"marche": {"action": "Walking", "images": 8}}}
Tout le reste a une valeur par defaut. Voir LISEZMOI.md pour toutes les cles.
"""
import os, sys, json, math, re, glob, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *
import bpy
from mathutils import Vector, Matrix, Euler

ARGS = sys.argv[sys.argv.index("--") + 1:]
MODE = ARGS[0]                      # fabriquer | variantes
RECETTE = os.path.abspath(ARGS[1])
R = lire_recette(RECETTE)
# style commun du projet : usine_projet.json (palette, vue, taille...) ; la recette peut surcharger
if os.path.exists("usine_projet.json"):
    R = {**{k: v for k, v in json.load(open("usine_projet.json")).items() if not k.startswith("_")}, **R}
verifier_recette_fabriquer(R)
ID = R["id"]
SORTIE = R.get("sortie", f"build/sprites/{ID}")
SUR = int(R.get("surechantillonnage", 8))
import canon as _canon
CANON = _canon.regler(R["canon"], R.get("contour")) if R.get("canon") else None
if R.get("canon"):
    _e = _canon.verifier(R["canon"])
    if _e:
        raise SystemExit("ERREUR dans le canon (usine_projet.json) :\n  - " + "\n  - ".join(_e))
    if MODE == "variantes":
        raise SystemExit("ERREUR : en mode canon, la lumiere et la palette sont fixees par le projet : pas de variantes "
                         "de pixelisation. Change le canon dans usine_projet.json (pour tout le jeu) si le rendu ne va pas.")
for d in ("hd", "pixel", "normales", "emission"):
    if MODE == "fabriquer" and os.path.isdir(os.path.join(SORTIE, d)):
        shutil.rmtree(os.path.join(SORTIE, d))  # plus d'images d'une fabrication precedente (autres tags, plus d'images)
for d in ("hd", "pixel"):
    os.makedirs(os.path.join(SORTIE, d), exist_ok=True)

VUES = {  # azimut (0 = la camera regarde l'avant du modele de cote, avant vers la droite), elevation
    "cote": (0, 0), "cote_droite": (0, 0), "cote_gauche": (180, 0), "face": (90, 0), "dos": (-90, 0),
    "dessus": (90, 89.9), "rpg": (90, 45), "rpg_bas": (90, 35), "iso": (45, 30), "iso_gauche": (135, 30),
    "trois_quarts": (45, 15)}

# ----------------------------------------------------------------- import
import geometrie as _G
importer = _G.importer


bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
objets = importer(R["modele"])
armature = _G.squelette_principal(objets)
if R.get("animations_depuis"):
    autres = importer(R["animations_depuis"])
    for a in bpy.data.actions:
        a.use_fake_user = True
    for o in autres:
        bpy.data.objects.remove(o, do_unlink=True)
for nom in R.get("cacher", []):
    for o in objets:
        if nom.lower() in o.name.lower():
            o.hide_render = True
meshes = [o for o in objets if o.type == "MESH" and o.name in bpy.data.objects and _G.visible(o)]

def srgb_lin(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def couleur_materiau(m, couleur):
    r, g, b = (srgb_lin(c) for c in hex_rgb(couleur))
    m.diffuse_color = (r, g, b, 1)
    if m.use_nodes:  # remplace aussi la texture (unie ou non) affichee par le rendu
        for nd in list(m.node_tree.nodes):
            if nd.type == "TEX_IMAGE":
                m.node_tree.nodes.remove(nd)
        img = bpy.data.images.new(f"uni_{m.name}_r", 4, 4)
        img.pixels.foreach_set([*hex_rgb(couleur), 1.0] * 16)
        tex = m.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img; m.node_tree.nodes.active = tex
    if m.use_nodes:
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf:
            for l in list(bsdf.inputs["Base Color"].links):
                m.node_tree.links.remove(l)
            bsdf.inputs["Base Color"].default_value = (r, g, b, 1)

def appliquer_couleurs():
    for nom_mat, couleur in R.get("couleurs", {}).items():
        for m in bpy.data.materials:
            if nom_mat.lower() in m.name.lower():
                couleur_materiau(m, couleur)


appliquer_couleurs()

# ------------------------------------------------------------ accessoires
# reglage par choix numerotes (usine accessoire) : _choix = {orientation, face, placement}
for acc in R.get("accessoires", []):
    ch = acc.get("_choix", {})
    if armature:
        armature.data.pose_position = "REST"; bpy.context.view_layer.update()
    nom_os = resoudre_os(armature, acc.get("os"))
    corps = [o for o in meshes]
    taille = (acc.get("taille_m") or taille_base_accessoire(corps, nom_os)) * ch.get("placement", {}).get("echelle", 1.0)
    nouveaux = [o for o in importer(acc["modele"]) if o.type == "MESH"]
    base = {o.name: o.matrix_world.copy() for o in nouveaux}
    pts = np.concatenate([np.array([base[o.name] @ v.co for v in o.data.vertices]) for o in nouveaux])
    c0 = Vector((pts.min(0) + pts.max(0)) / 2); dim0 = float((pts.max(0) - pts.min(0)).max())
    if "orientation" in ch:
        rot = Matrix.Rotation(math.radians(ch.get("face", 0)), 4, "Z") @ Euler([math.radians(a) for a in ch["orientation"]]).to_matrix().to_4x4()
    else:
        rot = Euler([math.radians(a) for a in acc.get("rotation", [0, 0, 0])]).to_matrix().to_4x4()
    taille0 = taille / ch.get("placement", {}).get("echelle", 1.0)
    cible = Vector(acc.get("decalage", [0, 0, 0]))
    if nom_os:
        cible += point_attache(armature, nom_os, taille0)
    cible += Vector((0, 0, ch.get("placement", {}).get("hauteur", 0.0) * taille / ch.get("placement", {}).get("echelle", 1.0)))
    for o in nouveaux:
        o.matrix_world = Matrix.Translation(cible) @ rot @ Matrix.Scale(taille / dim0, 4) @ Matrix.Translation(-c0) @ base[o.name]
        if acc.get("couleur"):
            m = bpy.data.materials.new(f"acc_{o.name}"); m.use_nodes = True; couleur_materiau(m, acc["couleur"])
            o.data.materials.clear(); o.data.materials.append(m)
        if nom_os:
            mw = o.matrix_world.copy()
            o.parent = armature; o.parent_type = "BONE"; o.parent_bone = nom_os
            bpy.context.view_layer.update(); o.matrix_world = mw
    if armature:
        armature.data.pose_position = "POSE"
    objets += nouveaux; meshes += nouveaux
if R.get("accessoires"):
    appliquer_couleurs()  # les materiaux des accessoires existent seulement maintenant

# ------------------------------------------------------- orientation / echelle
# Un pivot neutre (jamais anime par le fichier) porte la rotation de la recette et les mouvements proceduraux du corps
# entier : ca marche quel que soit le mode de rotation du fichier (glTF = quaternions) et meme si le fichier anime
# ses propres objets.
if not meshes:
    raise SystemExit("ERREUR : rien a rendre (tous les objets sont caches : verifie 'cacher' dans la recette).")
racines = [o for o in objets if o.parent is None and o.name in bpy.data.objects]
bpy.context.view_layer.update()
_p = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in meshes])
PIVOT = bpy.data.objects.new("usine_pivot", None); scene.collection.objects.link(PIVOT)
PIVOT.location = Vector((float(_p[:, 0].min() + _p[:, 0].max()) / 2, float(_p[:, 1].min() + _p[:, 1].max()) / 2, float(_p[:, 2].min())))
bpy.context.view_layer.update()
for o in racines:
    o.parent = PIVOT; o.matrix_parent_inverse = PIVOT.matrix_world.inverted()
PIVOT.rotation_euler.z = math.radians(float(R.get("rotation_z", 0)))
bpy.context.view_layer.update()
PIV0 = (PIVOT.location.copy(), PIVOT.rotation_euler.copy())

# ------------------------------------------------------------ animations
# qui joue quelle animation dans le fichier (squelette ET animations d'objets sans squelette), puis on coupe le
# melange automatique (NLA) : une seule animation a la fois, celle de la recette
ACT_OBJ = {}
for o in bpy.data.objects:
    ad = o.animation_data
    if not ad:
        continue
    if ad.action:
        ACT_OBJ.setdefault(ad.action.name, []).append((o, getattr(ad, "action_slot", None)))
    for tr in ad.nla_tracks:
        for st in tr.strips:
            if st.action and o not in [x for x, _ in ACT_OBJ.get(st.action.name, [])]:
                ACT_OBJ.setdefault(st.action.name, []).append((o, getattr(st, "action_slot", None)))
    ad.use_nla = False
ANIMES = {o for v in ACT_OBJ.values() for o, _ in v} | {x for x in objets if x.type == "ARMATURE" and x.name in bpy.data.objects}

def action(nom):
    a = trouver_action(nom)
    if a is None:
        raise SystemExit(f"ERREUR : animation '{nom}' introuvable. Disponibles : {sorted(x.name for x in bpy.data.actions)}")
    return a

# deformations de sommets (onde, pulsation, balancement) : tous les maillages, y compris ceux portes par un squelette
ORIG = {o.name: np.array([v.co[:] for v in o.data.vertices]) for o in meshes}
pts0 = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in meshes])
LO0, HI0 = pts0.min(0), pts0.max(0); TAILLE0 = float((HI0 - LO0).max())

def procedural(nom, t, force):
    """t dans [0,1[ : boucle parfaite. Deforme les objets ou les sommets, sans squelette."""
    s2 = math.sin(2 * math.pi * t); c2 = math.cos(2 * math.pi * t)
    PIVOT.location, PIVOT.rotation_euler, PIVOT.scale = PIV0[0].copy(), PIV0[1].copy(), (1, 1, 1)
    if nom == "flottement":
        PIVOT.location.z += 0.05 * force * TAILLE0 * s2; PIVOT.rotation_euler.y += math.radians(4 * force) * c2
    elif nom == "rebond":
        sq = max(0.2, 1 + 0.18 * force * s2)  # force tres grande : jamais d'echelle nulle ou negative
        PIVOT.scale = (1 / math.sqrt(sq), 1 / math.sqrt(sq), sq)
        PIVOT.location.z += max(0, s2) * 0.12 * force * TAILLE0
    elif nom == "rotation":
        PIVOT.rotation_euler.z += 2 * math.pi * t
    elif nom == "respiration":
        PIVOT.scale = (1, 1 + 0.02 * force * s2, 1 + 0.04 * force * s2)
    elif nom not in ("onde", "pulsation", "balancement"):
        raise SystemExit(f"ERREUR : procedural '{nom}' inconnu. Choix : onde, pulsation, balancement, rebond, rotation, flottement, respiration")
    if nom in ("onde", "pulsation", "balancement"):
        for o in meshes:
            if o.name not in ORIG:
                continue
            co = ORIG[o.name].copy()
            lo, hi = co.min(0), co.max(0); L = np.maximum(hi - lo, 1e-6)
            if nom == "onde":      # poisson, anguille, serpent : onde laterale qui grossit vers la queue
                ax = int(np.argmax(L[:2])); lat = 1 - ax
                u = (co[:, ax] - lo[ax]) / L[ax]
                queue = (1 - u) if R.get("tete_vers_max", True) else u
                co[:, lat] += 0.12 * force * L[ax] * queue ** 2 * np.sin(2 * math.pi * (t - 1.2 * u))
            elif nom == "pulsation":  # meduse : la cloche se contracte, les filaments ondulent
                h = (co[:, 2] - lo[2]) / L[2]; cx, cy = (lo[:2] + hi[:2]) / 2
                k = 1 + 0.12 * force * s2 * (0.4 + 0.6 * h)
                co[:, 0] = cx + (co[:, 0] - cx) * k; co[:, 1] = cy + (co[:, 1] - cy) * k
                co[:, 2] += (1 - h) ** 2 * 0.06 * force * L[2] * np.sin(2 * math.pi * (t + 2 * h))
                co[:, 2] -= 0.04 * force * L[2] * s2 * h
            elif nom == "balancement":  # plante, arbre, drapeau : plie plus fort vers le haut
                h = np.clip((co[:, 2] - lo[2]) / L[2], 0, 1)
                co[:, 0] += 0.08 * force * L[2] * h ** 2 * s2
                co[:, 1] += 0.03 * force * L[2] * h ** 2 * c2
            o.data.vertices.foreach_set("co", co.ravel())
            if o.data.shape_keys:  # avec des formes cles, c'est la forme de reference qui compte
                o.data.shape_keys.reference_key.data.foreach_set("co", co.ravel())
            o.data.update()

ANIMS = R.get("animations") or {"fixe": {"images": 1}}
# directions : 1 (defaut), 2, 4 ou 8 vues du MEME modele, tournees autour de son axe vertical
NDIR = int(R.get("directions", 1))
NOMS_DIR8 = ["face", "face_droite", "droite", "dos_droite", "dos", "dos_gauche", "gauche", "face_gauche"]
PLAN = []
for tag, spec in ANIMS.items():
    n = int(spec.get("images", 8))
    if spec.get("action"):
        a = action(spec["action"]); d, f = a.frame_range
        if not courbes_action(a):
            pleines = sorted(x.name for x in bpy.data.actions if courbes_action(x))
            raise SystemExit(f"ERREUR : l'animation '{a.name}' est VIDE (aucune image cle) : elle ne bouge pas. "
                             f"Animations qui bougent : {pleines or 'aucune -> prends un procedural'}")
        _oa = os_de_action(a)
        _tous_os = {b.name for x in objets if x.type == "ARMATURE" and x.name in bpy.data.objects for b in x.data.bones}
        if armature and _oa and len(_oa & _tous_os) < 0.3 * len(_oa):
            raise SystemExit(f"ERREUR : l'animation '{a.name}' vient d'un autre squelette ({len(_oa & _tous_os)} os "
                             f"en commun sur {len(_oa)}) : "
                             "elle ne bougerait rien. Pour reprendre l'animation d'un autre modele : operation \"reprendre\" "
                             "dans \"modelage\" (LISEZMOI section 5).")
        e_ = float(spec.get("elan", 0))   # elan : le debut (preparation) dure plus longtemps, le coup part vite
        if not 0 <= e_ <= 2:
            raise SystemExit(f"ERREUR : animation '{tag}' : elan de 0 (regulier) a 2 (preparation tres longue)")
        for i in range(n):
            PLAN.append((tag, i, ("action", a), d + (i / n) ** (1 + e_) * (f - d)))
    elif spec.get("procedural"):
        for i in range(n):
            PLAN.append((tag, i, ("proc", spec["procedural"], float(spec.get("force", 1.0))), i / n))
    else:
        PLAN.append((tag, 0, ("fixe",), 0))

PLAN = [(tag, i, quoi, t, 0.0) for tag, i, quoi, t in PLAN]
if NDIR > 1:
    PLAN = [(tag, i, quoi, t, 360.0 * k / NDIR) for k in range(NDIR) for tag, i, quoi, t, _ in PLAN]


SECONDAIRE = R.get("secondaire") or []
if SECONDAIRE and not armature:
    raise SystemExit("ERREUR : \"secondaire\" demande un modele avec squelette")
for _s in SECONDAIRE:
    if not isinstance(_s, dict) or not _s.get("chaine"):
        raise SystemExit("ERREUR : \"secondaire\" : [{\"chaine\": \"<debut du nom des os>\", \"retard\": 0.08, \"force\": 1}]")
    _ch = [b.name for b in armature.data.bones if b.name.startswith(_s["chaine"])]
    if not _ch:
        raise SystemExit(f"ERREUR : secondaire : aucun os ne commence par '{_s['chaine']}'. Os : {[b.name for b in armature.data.bones][:40]}")


def mouvement_secondaire(act, t):
    """Mouvement secondaire (queue, cheveux, oreilles, sac, tentacule) : le BOUT de chaque os de la chaine vise la
    place qu'il occupait un peu PLUS TOT (retard croissant le long de la chaine) -> la chaine traine derriere les
    mouvements du corps (rotations ET deplacements), puis rattrape."""
    d_, f_ = act.frame_range; cyc = max(f_ - d_, 1)
    W = armature.matrix_world
    def a_temps(tt):
        tt = d_ + (tt - d_) % cyc; scene.frame_set(int(math.floor(tt)), subframe=tt - math.floor(tt))
    for sp in SECONDAIRE:
        ch = sorted([b.name for b in armature.data.bones if b.name.startswith(sp["chaine"])],
                    key=lambda n: len(armature.data.bones[n].parent_recursive))
        ret = float(sp.get("retard", 0.08)) * cyc; fo = max(0.0, min(float(sp.get("force", 1.0)), 1.0))
        vieux = {}
        for k, n in enumerate(ch):
            a_temps(t - ret * (k + 1)); vieux[n] = W @ armature.pose.bones[n].tail
        a_temps(t)
        for n in ch:   # de la base vers le bout
            pb = armature.pose.bones[n]; h = W @ pb.head; q = W @ pb.tail
            cur = (q - h).normalized(); vis = (vieux[n] - h)
            if vis.length < 1e-6:
                continue
            vis = cur.lerp(vis.normalized(), fo).normalized()
            rot = cur.rotation_difference(vis).to_matrix().to_4x4()
            Mw = W @ pb.matrix
            M_ = Matrix.Translation(h) @ rot @ Matrix.Translation(-h) @ Mw
            pb.matrix = W.inverted() @ M_
            bpy.context.view_layer.update()
            if os.environ.get("USINE_DEBUG"):
                print("SECONDAIRE", n, round(t, 2), round(math.degrees(cur.angle(vis)), 1))


def poser(quoi, t):
    if quoi[0] == "action":
        _arms = [x for x in objets if x.type == "ARMATURE" and x.name in bpy.data.objects]
        _oa = os_de_action(quoi[1])
        _arm = max(_arms, key=lambda x: len(_oa & {b.name for b in x.data.bones})) if _arms and _oa else armature
        cibles = ACT_OBJ.get(quoi[1].name) or ([(_arm, None)] if _arm else [])
        if not cibles:  # action sans proprietaire connu : on la donne a tout objet qu'elle sait animer
            cibles = [(o, None) for o in objets if o.type in ("ARMATURE", "MESH", "EMPTY") and o.name in bpy.data.objects][:1]
        for o in ANIMES - {c for c, _ in cibles}:
            if o.animation_data:
                o.animation_data.action = None
        for o, slot in cibles:
            ad = o.animation_data_create()
            if ad.action != quoi[1]:
                ad.action = quoi[1]
            choisir_slot(o, quoi[1], slot)
        scene.frame_set(int(math.floor(t)), subframe=t - math.floor(t))
        if SECONDAIRE:
            mouvement_secondaire(quoi[1], t)
    elif quoi[0] == "proc":
        procedural(quoi[1], t, quoi[2]); bpy.context.view_layer.update()
    else:
        bpy.context.view_layer.update()

# ------------------------------------------------------------------ camera
az0, el = VUES.get(R.get("vue", "cote"), (0, 0)) if isinstance(R.get("vue", "cote"), str) else R["vue"]
el = math.radians(el)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam)
cam.data.type = "ORTHO"; scene.camera = cam

def axes_camera(angle):
    """direction (camera -> modele), droite et haut de l'image, pour une direction de vue tournee de 'angle' degres."""
    az = math.radians(az0 + R.get("azimut_plus", 0) + angle)
    # avant du modele : -Y (convention glTF et modeles de l'usine) ; azimut 0 = camera sur -X, l'avant apparait a droite
    d = -Vector((-math.cos(az) * math.cos(el), -math.sin(az) * math.cos(el), math.sin(el)))
    q = d.to_track_quat("-Z", "Y")
    Mq = q.to_matrix()
    return d, Vector(Mq.col[0]), Vector(Mq.col[1]), q.to_euler()

def nom_direction(angle):
    """Nom de la direction ou le sujet regarde A L'ECRAN (face = vers toi, droite = vers la droite de l'image)."""
    d, dr, ht, _ = axes_camera(angle)
    F = Vector((0, -1, 0)); vers_cam = Vector((-d.x, -d.y, 0)).normalized()
    phi = math.degrees(math.atan2(F.dot(dr), F.dot(vers_cam))) % 360
    return NOMS_DIR8[int(round(phi / 45)) % 8]

def points():
    dg = bpy.context.evaluated_depsgraph_get(); pts = []
    for o in meshes:
        e = o.evaluated_get(dg); me = e.to_mesh()
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        mw = e.matrix_world; pts.append(co @ np.array(mw.to_3x3()).T + np.array(mw.translation)); e.to_mesh_clear()
    return np.concatenate(pts)

ANGLES = sorted({it[4] for it in PLAN})
CADR = {a: [np.array([1e9, 1e9]), np.array([-1e9, -1e9])] for a in ANGLES}
lo3 = np.array([1e9] * 3); hi3 = -lo3
for tag, i, quoi, t, ang in PLAN:
    poser(quoi, t); p = points()
    _, dr, ht, _ = axes_camera(ang)
    uv = np.stack([p @ np.array(dr), p @ np.array(ht)], 1)
    CADR[ang][0] = np.minimum(CADR[ang][0], uv.min(0)); CADR[ang][1] = np.maximum(CADR[ang][1], uv.max(0))
    lo3 = np.minimum(lo3, p.min(0)); hi3 = np.maximum(hi3, p.max(0))
if any(any(m.type == "CLOTH" for m in o.modifiers) for o in bpy.data.objects):  # le tissu bouge plus que prevu au cadrage
    for a_ in ANGLES:
        c_, e_ = (CADR[a_][0] + CADR[a_][1]) / 2, (CADR[a_][1] - CADR[a_][0]) / 2 * 1.25
        CADR[a_] = [c_ - e_, c_ + e_]
RACCORD = R.get("raccord")   # tuile / plan de fond qui se repete : {"axes": "x" | "xy", "base": "<objet qui fixe la case>"}
if RACCORD:
    if NDIR != 1:
        raise SystemExit("ERREUR : raccord : une seule direction (pas de 'directions')")
    _ax = RACCORD.get("axes", "xy") if isinstance(RACCORD, dict) else str(RACCORD)
    _bn = (RACCORD.get("base") if isinstance(RACCORD, dict) else None) or "dalle"
    _base = [o for o in meshes if _bn.lower() in o.name.lower()]
    if not _base:
        raise SystemExit(f"ERREUR : raccord : aucun objet '{_bn}' (la plaque qui fixe la case) -> donne \"base\": \"<nom>\" "
                         f"(objets : {[o.name for o in meshes][:12]})")
    _, _dr, _ht, _ = axes_camera(ANGLES[0]); bpy.context.view_layer.update()
    _pb = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in _base])
    _uv = np.stack([_pb @ np.array(_dr), _pb @ np.array(_ht)], 1)
    _lo, _hi = _uv.min(0), _uv.max(0); _P = _hi - _lo
    if "y" not in _ax:   # plan de fond : on garde la hauteur de tout le contenu
        _lo[1], _hi[1] = CADR[ANGLES[0]][0][1], CADR[ANGLES[0]][1][1]
    _dec = [(i, j) for i in (-1, 0, 1) for j in ((-1, 0, 1) if "y" in _ax else (0,)) if (i, j) != (0, 0)]
    for o in list(meshes):
        for i, j in _dec:
            c = o.copy(); scene.collection.objects.link(c); c.parent = None; c.animation_data_clear()
            for m in list(c.modifiers):
                if m.type == "ARMATURE":
                    c.modifiers.remove(m)
            c.matrix_world = Matrix.Translation(_dr * (_P[0] * i) + _ht * (_P[1] * j)) @ o.matrix_world
    bpy.context.view_layer.update()
    _m = np.array([_P[0], _P[1] if "y" in _ax else 0.0])   # on rend la case ET ses voisines : contour, nettoyage et
    for a_ in ANGLES:                                       # reduction voient la suite du motif ; on garde le centre
        CADR[a_] = [_lo - _m, _hi + _m]
    R["marge_px"] = 0
taille_px = int(R.get("taille_px", 32))
selon = R.get("taille_selon", "max")
ext = np.max([CADR[a][1] - CADR[a][0] for a in ANGLES], axis=0)
ext0 = CADR[0.0][1] - CADR[0.0][0] if 0.0 in CADR else ext
ppu = taille_px / {"hauteur": ext0[1], "largeur": ext0[0]}.get(selon, ext0.max())
marge = int(R.get("marge_px", 2))
cw = int(math.ceil((ext[0] * ppu + 2 * marge) / 2) * 2); ch = int(math.ceil((ext[1] * ppu + 2 * marge) / 2) * 2)
if R.get("case"):
    cw, ch = R["case"]
if RACCORD:
    ppu = taille_px / _P[0]
    RAC_CASE = (taille_px, max(2, int(round((_hi[1] - _lo[1]) * ppu))))
    cw = 3 * taille_px; ch = RAC_CASE[1] * (3 if "y" in _ax else 1)
    cam.data.ortho_scale = max(cw, ch) / ppu
cam.data.ortho_scale = max(cw, ch) / ppu
cam.data.clip_end = TAILLE0 * 40
centre_monde = (lo3 + hi3) / 2

def placer_camera(ang):
    d, dr, ht, eul = axes_camera(ang)
    c2 = (CADR[ang][0] + CADR[ang][1]) / 2
    # bas commun : le sol (bas de la case) est au meme endroit pour toutes les directions
    centre = Vector(dr) * c2[0] + Vector(ht) * c2[1]
    profond = float(np.dot(centre_monde, np.array(d)))
    cam.location = centre + d * (profond - TAILLE0 * 10)
    cam.rotation_euler = eul
    bpy.context.view_layer.update()

placer_camera(0.0 if 0.0 in CADR else ANGLES[0])
direction, droite, haut, _ = axes_camera(0.0)
TAGS_DIR = {}  # (tag, angle) -> nom de tag final
for tag, i, quoi, t, ang in PLAN:
    TAGS_DIR[(tag, ang)] = tag if NDIR == 1 else f"{tag}_{nom_direction(ang)}"

scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x, scene.render.resolution_y = cw * SUR, ch * SUR
scene.render.film_transparent = True
sh = scene.display.shading
sh.light = "STUDIO"; sh.color_type = R.get("couleur_mode", "TEXTURE")
sh.show_shadows = R.get("ombres", True); sh.show_cavity = R.get("cavite", True)
scene.display.shadow_focus = 0.6
scene.view_settings.view_transform = "Standard"

if mode_kit() and MODE == "fabriquer":
    os.makedirs("art/source/blender", exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(f"art/source/blender/{ID}.blend"), copy=True)

# ------------------------------------------------------------- rendu HD
HD = []; NORM_HD = []; EMI_HD = []; ALB_HD = []; NORC_HD = []; MAT_HD = []; OCC_HD = []
DONNEES_IMG = []
from bpy_extras.object_utils import world_to_camera_view
EMISSIFS = [m for m in bpy.data.materials if m.get("usine_emission", 0) > 0]
# points suivis image par image : {"nom": "os:<os>" | "<zone humaine>" | "<objet>"}
SUIVIS = dict(R.get("points", {}))
if armature and not SUIVIS:
    try:
        _rep = _G.repere(meshes, armature); _Z = _G.zones(meshes, armature, _rep)
        for z in ("tete", "main_d", "main_g", "pied_d", "pied_g"):
            if z in _Z and _Z[z]["os"]:
                SUIVIS[z] = "os:" + _Z[z]["os"]
    except Exception as e:
        print("  (points automatiques indisponibles :", e, ")")
elif armature:
    _rep = _G.repere(meshes, armature); _Z = _G.zones(meshes, armature, _rep)
    SUIVIS = {k: ("os:" + _Z[v]["os"] if v in _Z and _Z[v]["os"] else v) for k, v in SUIVIS.items()}

def point_monde(cible):
    if cible.startswith("os:") and armature:
        pb = armature.pose.bones.get(cible[3:])
        return armature.matrix_world @ pb.tail if pb else None
    o = bpy.data.objects.get(cible) or next((x for x in meshes if cible.lower() in x.name.lower()), None)
    if o is None:
        return None
    dg = bpy.context.evaluated_depsgraph_get(); e = o.evaluated_get(dg); me = e.to_mesh()
    co = np.array([e.matrix_world @ v.co for v in me.vertices]); e.to_mesh_clear()
    return Vector(co.mean(0)) if len(co) else None

def en_pixels(pw):
    q = world_to_camera_view(scene, cam, pw)
    return [round(q.x * cw, 1), round((1 - q.y) * ch, 1)]

def boite_cible(cible):
    """boite [x, y, l, h] (pixels) d'un objet ou des sommets qui suivent surtout un os."""
    dg = bpy.context.evaluated_depsgraph_get(); pts = []
    for o in meshes:
        if not (cible.lower() in o.name.lower() or cible.startswith("os:")):
            continue
        e = o.evaluated_get(dg); me = e.to_mesh()
        if cible.startswith("os:"):
            g = o.vertex_groups.get(cible[3:])
            if g is None:
                if o.parent_bone == cible[3:]:
                    pts += [e.matrix_world @ v.co for v in me.vertices]
                e.to_mesh_clear(); continue
            ids = {v.index for v in o.data.vertices for ge in v.groups if ge.group == g.index and ge.weight > 0.5}
            pts += [e.matrix_world @ me.vertices[k].co for k in ids if k < len(me.vertices)]
        else:
            pts += [e.matrix_world @ v.co for v in me.vertices]
        e.to_mesh_clear()
    if not pts:
        return None
    xy = np.array([en_pixels(p) for p in pts[:: max(1, len(pts) // 400)]])
    lo, hi = xy.min(0), xy.max(0)
    return [round(float(lo[0]), 1), round(float(lo[1]), 1), round(float(hi[0] - lo[0]), 1), round(float(hi[1] - lo[1]), 1)]

# un evenement "contact" peut viser directement une zone (pied_d) : elle est alors suivie aussi
SUIVI_DE = {}
for nom_e, spec in R.get("evenements", {}).items():
    z = spec.get("contact") if isinstance(spec, dict) else None
    if z and z not in SUIVIS:
        if armature and z in (_Z if "_Z" in globals() else {}) and _Z[z]["os"]:
            SUIVIS[z] = "os:" + _Z[z]["os"]
        elif z.startswith("os:") or bpy.data.objects.get(z):
            SUIVIS[z] = z
for k, c in list(SUIVIS.items()):
    if point_monde(c) is None:
        print(f"  ATTENTION : point '{k}' -> '{c}' introuvable (os:<nom d'os>, zone humaine ou nom d'objet). Ignore.")
        SUIVIS.pop(k)
TISSUS = [o for o in bpy.data.objects if any(m.type == "CLOTH" for m in o.modifiers)]
if TISSUS:  # gravite a l'echelle : le tissu se comporte comme sur un sujet de taille humaine, quelle que soit l'echelle du fichier
    h_ = float(TISSUS[0].get("usine_H", HI0[2] - LO0[2]))
    scene.gravity = (0, 0, -9.81 * float(R.get("gravite_tissu", 1.0)) * h_ / 1.8)

def cycliques(act):
    """Animation en boucle avant et apres sa plage (pour la 'chauffe' du tissu)."""
    fcs = list(getattr(act, "fcurves", []))
    for l in getattr(act, "layers", []):
        for st in l.strips:
            for cb in st.channelbags:
                fcs += list(cb.fcurves)
    for fc in fcs:
        if not any(m.type == "CYCLES" for m in fc.modifiers):
            fc.modifiers.new("CYCLES")

groupe_courant = None; image_courante = None
ang_courant = None
for tag, i, quoi, t, ang in PLAN:
    if ang != ang_courant:
        placer_camera(ang); ang_courant = ang
    if TISSUS and quoi[0] == "action":
        # tissu : simulation image par image, avec un tour complet de chauffe avant la premiere image
        if groupe_courant != (tag, ang):
            groupe_courant = (tag, ang)
            act_ = quoi[1]; cycliques(act_)
            d_, f_ = act_.frame_range
            # un tour complet de chauffe (de d_ a f_), puis les images sont prises pendant le 2e tour (boucle)
            scene.frame_start = int(math.floor(d_)); scene.frame_end = int(math.ceil(f_ + (f_ - d_))) + 2
            decal_tissu = f_ - d_
            for o in TISSUS:
                for m in o.modifiers:
                    if m.type == "CLOTH":
                        m.point_cache.frame_start = scene.frame_start; m.point_cache.frame_end = scene.frame_end
            poser(quoi, scene.frame_start)
            scene.frame_set(scene.frame_start); image_courante = scene.frame_start
        cible_f = int(round(t + decal_tissu))
        poser(quoi, image_courante)
        while image_courante < cible_f:
            image_courante += 1; scene.frame_set(image_courante)
    else:
        poser(quoi, t)
    nt = TAGS_DIR[(tag, ang)]
    p = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}.png")
    if os.path.exists(p): os.remove(p)
    scene.render.filepath = p; bpy.ops.render.render(write_still=True)
    HD.append(lire_image(p))
    # donnees de l'image : points suivis, boites demandees, origine (sol sous le centre du modele au repos)
    dimg = {"tag": nt, "image": i, "points": {}, "boites": {}}
    for k, c in SUIVIS.items():
        pw = point_monde(c)
        if pw is not None:
            dimg["points"][k] = en_pixels(pw); dimg.setdefault("_z", {})[k] = float(pw.z)
    for k, c in R.get("boites", {}).items():
        b_ = boite_cible(c)
        if b_:
            dimg["boites"][k] = b_
    dimg["origine"] = en_pixels(Vector(((LO0[0] + HI0[0]) / 2, (LO0[1] + HI0[1]) / 2, LO0[2])))
    DONNEES_IMG.append(dimg)
    if CANON:  # passes du rendu canon : couleur a plat, puis normales (la lumiere est calculee ensuite, par crans)
        sh_ = scene.display.shading; anc = (sh_.light, sh_.color_type, sh_.show_shadows, sh_.show_cavity)
        sh_.light = "FLAT"; sh_.show_shadows = False; sh_.show_cavity = False
        pa_ = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}_aplat.png"); scene.render.filepath = pa_
        bpy.ops.render.render(write_still=True); ALB_HD.append(lire_image(pa_))
        sh_.light = "MATCAP"; sh_.studio_light = "check_normal+y.exr"; sh_.color_type = "SINGLE"; sh_.single_color = (1, 1, 1)
        pn_ = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}_normcanon.png"); scene.render.filepath = pn_
        bpy.ops.render.render(write_still=True); NORC_HD.append(lire_image(pn_))
        # matieres : rouge = numero de matiere, vert = emet de la lumiere (ce qui brille reste clair)
        sauv = {m.name: tuple(m.diffuse_color) for m in bpy.data.materials}
        for m in bpy.data.materials:
            k_ = _canon.MATIERES.index(m.get("usine_matiere", "mat")) if m.get("usine_matiere", "mat") in _canon.MATIERES else 0
            m.diffuse_color = (k_ / 8, 1.0 if m.get("usine_emission", 0) > 0 else 0.0, 0, 1)
        sh_.light = "FLAT"; sh_.color_type = "MATERIAL"
        pm_ = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}_matiere.png"); scene.render.filepath = pm_
        bpy.ops.render.render(write_still=True); MAT_HD.append(lire_image(pm_))
        for m in bpy.data.materials:
            m.diffuse_color = sauv[m.name]
        # ombres de contact : ombre portee d'une partie sur l'autre + creux (cavite), sur un blanc uniforme
        sh_.light = "FLAT"; sh_.color_type = "SINGLE"; sh_.single_color = (1, 1, 1)
        sh_.show_shadows = True; sh_.show_cavity = True; sh_.cavity_type = "WORLD"
        anc_sh = (sh_.shadow_intensity, tuple(scene.display.light_direction))
        sh_.shadow_intensity = 1.0
        Lc = CANON["_L"]; cam_m = scene.camera.matrix_world.to_3x3()
        scene.display.light_direction = tuple((cam_m @ Vector((Lc[0], Lc[1], Lc[2]))).normalized())
        po_ = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}_ombre.png"); scene.render.filepath = po_
        bpy.ops.render.render(write_still=True); OCC_HD.append(lire_image(po_))
        sh_.shadow_intensity = anc_sh[0]; scene.display.light_direction = anc_sh[1]
        sh_.light, sh_.color_type, sh_.show_shadows, sh_.show_cavity = anc
    if R.get("normales"):  # carte de normales (eclairage dynamique dans le moteur)
        sh_ = scene.display.shading; anc = (sh_.light, sh_.color_type, sh_.show_shadows, sh_.show_cavity)
        sh_.light = "MATCAP"; sh_.studio_light = "check_normal+y.exr"; sh_.color_type = "SINGLE"; sh_.single_color = (1, 1, 1)
        sh_.show_shadows = False; sh_.show_cavity = False
        pn = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}_normales.png"); scene.render.filepath = pn
        bpy.ops.render.render(write_still=True); NORM_HD.append(lire_image(pn))
        sh_.light, sh_.color_type, sh_.show_shadows, sh_.show_cavity = anc
    if EMISSIFS:  # masque de lumiere emise (yeux, lanternes...) : blanc = emet, noir = n'emet pas
        sh_ = scene.display.shading; anc = (sh_.light, sh_.color_type, sh_.show_shadows, sh_.show_cavity)
        sauv = {m.name: tuple(m.diffuse_color) for m in bpy.data.materials}
        for m in bpy.data.materials:
            m.diffuse_color = (1, 1, 1, 1) if m.get("usine_emission", 0) > 0 else (0, 0, 0, 1)
        sh_.light = "FLAT"; sh_.color_type = "MATERIAL"; sh_.show_shadows = False; sh_.show_cavity = False
        pe = os.path.join(SORTIE, "hd", f"{nt}_{i:02d}_emission.png"); scene.render.filepath = pe
        bpy.ops.render.render(write_still=True); EMI_HD.append(lire_image(pe))
        for m in bpy.data.materials:
            m.diffuse_color = sauv[m.name]
        sh_.light, sh_.color_type, sh_.show_shadows, sh_.show_cavity = anc

# --------------------------------------------------------------- palette
def lab(rgb):
    rgb = np.asarray(rgb, dtype=float)
    lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    Mx = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ Mx.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(np.maximum(xyz, 0)), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)

import colorsys
def rampe_auto(rgb, n=5):
    h, l, s = colorsys.rgb_to_hls(*rgb)
    out = []
    for i in range(n):
        t = i / (n - 1)
        hh = (h + (-0.06 + 0.10 * t)) % 1.0 if not (0.5 < h < 0.85) else (h + (0.05 - 0.08 * t)) % 1.0
        ll = 0.12 + 0.78 * t; ss = min(1, s * (0.8 + 0.5 * (1 - abs(t - 0.5) * 2)) + 0.05)
        out.append(colorsys.hls_to_rgb(hh, ll, ss))
    return out

def reduire(a):
    h, w = a.shape[0] // SUR, a.shape[1] // SUR
    b = a[:h * SUR, :w * SUR].reshape(h, SUR, w, SUR, 4)
    al = b[..., 3]; cov = al.mean((1, 3))
    rgb = (b[..., :3] * al[..., None]).sum((1, 3)) / np.maximum(al.sum((1, 3)), 1e-6)[..., None]
    return rgb, cov

REDUITS = [reduire(a) for a in HD]
TOUS = np.concatenate([rgb[cov >= 0.45] for rgb, cov in REDUITS])
if len(TOUS) < 8:  # sujet tres fin a cette taille (fourchette de profil, fil, epee de chant) : on garde les pixels partiels
    TOUS = np.concatenate([rgb[cov > 0.05] for rgb, cov in REDUITS])
    if len(TOUS):
        print("  ATTENTION : sujet tres fin a cette taille -> monte 'taille_px', 'taille_selon': 'max' ou 'seuil_alpha': 0.2")
if len(TOUS) == 0:
    _dim = HI0 - LO0; _plat = ""
    if _dim.max() > 0 and _dim.min() < 0.02 * _dim.max():
        _ax = int(np.argmin(_dim))
        _plat = (" Le modele est PLAT (une carte sans epaisseur" + (", couchee a plat" if _ax == 2 else ", debout") + ") : vu par la tranche,"
                 " il est invisible -> " + ("\"vue\": \"dessus\" ou \"rpg\"" if _ax == 2 else "\"vue\": \"face\" ou \"rotation_z\": 90") + ".")
    raise SystemExit("ERREUR : rien de visible a l'image (modele vide, tout cache par 'cacher', ou hors du cadre). "
                     "Verifie modeles/<id>/apercu.png et la cle 'cacher'." + _plat)

def charger_palette(spec):
    """-> dict nom_rampe -> liste de couleurs (sombre -> clair)"""
    if spec in (None, "auto"):
        # k-moyennes dans Lab sur les couleurs du modele, puis une rampe par couleur de base
        X = lab(TOUS); k = int(R.get("couleurs_base", 6)); rng = np.random.default_rng(0)
        C = X[rng.choice(len(X), min(k, len(X)), replace=False)]
        for _ in range(25):
            lab_ = ((X[:, None] - C[None]) ** 2).sum(-1).argmin(1)
            C = np.array([X[lab_ == j].mean(0) if (lab_ == j).any() else C[j] for j in range(len(C))])
        bases = [TOUS[lab_ == j].mean(0) for j in range(len(C)) if (lab_ == j).sum() > 0.02 * len(X)]
        return {f"auto{j}": rampe_auto(b) for j, b in enumerate(bases)}
    if spec.startswith("lospec:"):
        nom = spec.split(":", 1)[1].strip().lower()
        os.makedirs(os.path.expanduser("~/.cache/usine"), exist_ok=True)
        p = os.path.join(os.path.expanduser("~/.cache/usine"), f"lospec_{nom}.hex")
        if not os.path.exists(p):
            try:
                http(f"https://lospec.com/palette-list/{nom}.hex", sortie=p, timeout=20, essais=1)
            except Exception:
                raise SystemExit(f"ERREUR : palette lospec '{nom}' introuvable (ou pas d'Internet). Noms valides : endesga-32, "
                                 "sweetie-16, pico-8, resurrect-64, apollo... (le nom est celui de l'adresse lospec.com/palette-list/<nom>)")
        spec = p
    if spec.endswith(".hex") or spec.endswith(".txt"):
        if not os.path.exists(spec):
            raise SystemExit(f"ERREUR : palette introuvable : {spec}")
        cols = [hex_rgb(l.strip()) for l in open(spec) if re.fullmatch(r"#?[0-9a-fA-F]{6}", l.strip())]
        if len(cols) < 2:
            if "lospec_" in spec:
                os.remove(spec)
            raise SystemExit(f"ERREUR : palette {spec} vide ou illisible (une couleur #rrggbb par ligne attendue)")
        # palette plate : toutes les couleurs sont permises (une seule "rampe"), triees sombre -> clair
        return {"palette": sorted(cols, key=lambda c: colorsys.rgb_to_hls(*c)[1])}
    if not os.path.exists(spec):
        raise SystemExit(f"ERREUR : palette introuvable : {spec}. Cree-la d'abord (rampes de tons), ou mets \"palette\": \"auto\" dans la recette pour un essai.")
    d = json.load(open(spec))
    return {k: [hex_rgb(c) for c in v] for k, v in d["rampes"].items()}

def distance(X, P):
    """Distance de couleur 'pixel art' : la teinte compte plus que la luminosite
    (un reflet vert reste vert clair au lieu de devenir gris). X : (n,3) Lab, P : (k,3) Lab -> (n,k)"""
    dL = X[:, None, 0] - P[None, :, 0]
    da = X[:, None, 1] - P[None, :, 1]; db = X[:, None, 2] - P[None, :, 2]
    hx = np.arctan2(X[:, 2], X[:, 1]); hp = np.arctan2(P[:, 2], P[:, 1])
    dh = np.abs((hx[:, None] - hp[None] + np.pi) % (2 * np.pi) - np.pi)
    cx = np.hypot(X[:, 1], X[:, 2])[:, None]; cp = np.hypot(P[:, 1], P[:, 2])[None]
    perte_chroma = np.maximum(0, cx - cp - 8)       # un pixel colore ne doit pas devenir gris/blanc
    return dL ** 2 + da ** 2 + db ** 2 + (dh * np.minimum(cx, cp)) ** 2 + 5.0 * perte_chroma ** 2

RAMPES = charger_palette(R.get("palette", "auto"))
NOMS = list(RAMPES)
PAL = np.array([c for k in NOMS for c in RAMPES[k]]); RAMPE_DE = np.array([j for j, k in enumerate(NOMS) for _ in RAMPES[k]])
LAB_PAL = lab(PAL)

# ---------------------------------------------------------- pixelisation
def pixeliser(params):
    contraste = float(params.get("contraste", 1.0)); seuil = float(params.get("seuil_alpha", 0.45))
    rmax = int(params.get("rampes_max", 5)); contour = params.get("contour", "selectif")
    lum_w = np.array([0.299, 0.587, 0.114])
    l_all = TOUS @ lum_w; bas, haut_ = np.percentile(l_all, 2), np.percentile(l_all, 98)
    def regler(rgb):
        l = rgb @ lum_w
        etire = (l - bas) / max(haut_ - bas, 1e-3) * 0.78 + 0.13
        doux = float(params.get("auto_niveaux", 0.4)) if params.get("auto_niveaux", 0.4) is not False else 0.0
        l2 = l + (etire - l) * (1.0 if doux is True else doux)
        l2 = 0.5 + (l2 - 0.5) * contraste
        return np.clip(rgb * (np.clip(l2, 0.02, 1) / np.maximum(l, 1e-3))[..., None], 0, 1)
    tous = regler(TOUS)
    dd = distance(lab(tous), LAB_PAL)
    votes = np.bincount(RAMPE_DE[dd.argmin(1)], minlength=len(NOMS)) / max(len(tous), 1)
    if params.get("rampes") and any(k not in NOMS for k in params["rampes"]):
        raise SystemExit(f"ERREUR : rampes inconnues {[k for k in params['rampes'] if k not in NOMS]}. Rampes de cette palette : {NOMS}")
    gard = params.get("rampes") and [NOMS.index(k) for k in params["rampes"]] or \
        [j for j in np.argsort(-votes)[:rmax] if votes[j] >= float(params.get("part_min", 0.01))]
    choix = np.nonzero(np.isin(RAMPE_DE, gard))[0]; lab_c = LAB_PAL[choix]
    sortie = []
    for rgb, cov in REDUITS:
        m = cov >= seuil; h, w = m.shape; out = np.zeros((h, w, 4)); ram = np.full((h, w), -1)
        if m.any():
            k = choix[distance(lab(regler(rgb[m])), lab_c).argmin(1)]
            out[m, :3] = PAL[k]; out[m, 3] = 1; ram[m] = RAMPE_DE[k]
        # nettoyage : un pixel seul de sa couleur au milieu d'une couleur majoritaire prend cette couleur
        for _ in range(int(params.get("nettoyage", 1))):
            if not m.any():
                break
            idx = np.full((h, w), -1); idx[m] = ((out[m, :3] * 255).round().astype(int) @ np.array([65536, 256, 1]))
            for y, x in zip(*np.nonzero(m)):
                y0, y1, x0, x1 = max(0, y - 1), min(h, y + 2), max(0, x - 1), min(w, x + 2)
                v = idx[y0:y1, x0:x1].ravel(); v = v[v >= 0]
                if (v == idx[y, x]).sum() <= 1 and len(v) >= 6:
                    vals, cnt = np.unique(v[v != idx[y, x]], return_counts=True)
                    if len(cnt) and cnt.max() >= 5:
                        c = vals[cnt.argmax()]
                        out[y, x, :3] = [(c >> 16) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255]
        nb = sum(np.roll(np.roll(m, dy, 0), dx, 1).astype(int) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        iso = m & (nb == 0); out[iso] = 0; m = m & ~iso
        if contour:
            src = np.full(m.shape, -1); bord = np.zeros_like(m)
            # on ne cerne que les MASSES : un trait fin (tentacule, fil, antenne) reste sans contour
            nbv = sum(np.roll(np.roll(m, dy, 0), dx, 1).astype(int) for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            epais = m & (nbv >= 3)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                mm = np.roll(np.roll(epais, dy, 0), dx, 1); rr = np.roll(np.roll(ram, dy, 0), dx, 1)
                nv = mm & ~m & (src < 0); src[nv] = rr[nv]; bord |= nv
            # couleur du voisin opaque (pour le contour selectif)
            voisin = np.zeros((h, w, 3)); pris = np.zeros((h, w), bool)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                mm = np.roll(np.roll(m, dy, 0), dx, 1); cc = np.roll(np.roll(out[..., :3], dy, 0), dx, 1)
                nv = mm & ~pris; voisin[nv] = cc[nv]; pris |= nv
            for y, x in zip(*np.nonzero(bord)):
                if contour == "noir":
                    c = PAL[np.argmin(LAB_PAL[:, 0])]
                elif isinstance(contour, str) and contour.startswith("#"):
                    c = hex_rgb(contour)
                else:  # "selout" : la couleur de palette la plus proche du voisin assombri
                    L = lab(voisin[y, x]); cible = np.array([max(L[0] - float(params.get('contour_assombrir', 42)), 4), L[1] * 0.9, L[2] * 0.9])
                    c = PAL[choix[distance(cible[None], lab_c)[0].argmin()]]
                out[y, x, :3] = c; out[y, x, 3] = 1
        sortie.append(out)
    return sortie, [NOMS[j] for j in gard]

def agrandir(a, k): return a.repeat(k, 0).repeat(k, 1)
def sur_fond(a, f):
    return np.concatenate([np.ones(a.shape[:2] + (3,)) * np.array(hex_rgb(f)) * (1 - a[..., 3:4]) + a[..., :3] * a[..., 3:4],
                           np.ones(a.shape[:2] + (1,))], -1)

FONDS = R.get("fonds_planche", ["#3a8fb7", "#14182a", "#cfcfcf"])
PARAMS = {k: R[k] for k in ("contraste", "seuil_alpha", "rampes_max", "contour", "rampes", "auto_niveaux") if k in R}

if MODE == "variantes":
    grille_p = R.get("grille_variantes") or [
        {"contraste": c, "rampes_max": r, "seuil_alpha": s}
        for c in (0.9, 1.15, 1.4) for r, s in ((3, 0.5), (5, 0.4))] + [
        {"contraste": c, "rampes_max": 5, "seuil_alpha": 0.25} for c in (1.0, 1.3)]  # details fins (tentacules, fils)
    idx = [next(i for i, p in enumerate(PLAN) if p[0] == t) for t in ANIMS]  # 1re image de chaque animation
    vign = []
    for n, p in enumerate(grille_p, 1):
        pp = {**PARAMS, **p}; pix, _ = pixeliser(pp)
        rang = np.concatenate([sur_fond(agrandir(pix[i], 4), FONDS[j % len(FONDS)]) for i in idx for j in range(2)], 1)
        vign.append(numeroter(rang, n, k=3))
    W = max(v.shape[1] for v in vign)
    vign = [np.concatenate([v, np.ones((v.shape[0], W - v.shape[1], 4))], 1) for v in vign]
    sep = np.ones((6, W, 4))
    ecrire_image(os.path.join(SORTIE, f"{ID}_variantes.png"), np.concatenate(sum([[v, sep] for v in vign], [])[:-1], 0))
    json.dump(grille_p, open(os.path.join(SORTIE, "variantes.json"), "w"), indent=1)
    kit_iteration(ID, os.path.join(SORTIE, f"{ID}_variantes.png"),
                  f"variantes de pixelisation ({len(grille_p)} reglages numerotes) pour choisir le rendu le plus lisible")
    print(f"VARIANTES_OK REGARDE : {SORTIE}/{ID}_variantes.png  puis : usine choisir {os.path.relpath(RECETTE)} <numero>")
    sys.exit(0)

MES_CANON = None
if CANON:
    _R = _canon.Rampes(PAL, RAMPE_DE, distance, lab, float(CANON.get("exposition", 0.65)))
    PIX, MES_CANON = _canon.pixeliser(ALB_HD, NORC_HD, _R, SUR, CANON, MAT_HD, OCC_HD)
    _vus = {int(RAMPE_DE[np.argmin(((PAL - px[:3]) ** 2).sum(1))]) for p_ in PIX for px in p_[p_[..., 3] > 0][::7]}
    RAMPES_UTIL = [NOMS[j] for j in sorted(_vus)]
else:
    PIX, RAMPES_UTIL = pixeliser(PARAMS)
if not CANON and "seuil_alpha" not in PARAMS and min(int((p[..., 3] > 0).sum()) for p in PIX) < 4:
    # sujet trop fin pour le seuil par defaut : on garde aussi les pixels a moitie couverts (sinon sprite vide)
    PARAMS["seuil_alpha"] = 0.15; PIX, RAMPES_UTIL = pixeliser(PARAMS)
    print("  ATTENTION : sujet tres fin -> seuil_alpha 0.15 applique (mieux : monter 'taille_px')")
if RACCORD:   # on garde la case du centre
    _y0 = RAC_CASE[1] if "y" in _ax else 0
    PIX = [p[_y0:_y0 + RAC_CASE[1], RAC_CASE[0]:2 * RAC_CASE[0]].copy() for p in PIX]
    cw, ch = RAC_CASE
# traînée (animation "trainee": true) : sur un geste rapide, la forme s'etire entre deux images -- les pixels de
# l'image precedente qui touchent la silhouette actuelle restent, dans la couleur de l'image precedente
for k_ in range(1, len(PIX)):
    t0, t1 = PLAN[k_ - 1], PLAN[k_]
    sp_ = ANIMS.get(t1[0], {})
    if not sp_.get("trainee") or t0[0] != t1[0] or t0[-1] != t1[-1]:
        continue
    a0 = PIX[k_ - 1][..., 3] > 0; a1 = PIX[k_][..., 3] > 0
    if (a0 ^ a1).sum() < 0.08 * max(1, a1.sum()):   # geste lent : pas de traînée
        continue
    pres = a1.copy()
    for _ in range(int(sp_.get("trainee_px", 3))):   # pres de la silhouette actuelle (pas un fantome detache)
        pres = pres | np.roll(pres, 1, 0) | np.roll(pres, -1, 0) | np.roll(pres, 1, 1) | np.roll(pres, -1, 1)
    m_ = a0 & ~a1 & pres
    PIX[k_] = PIX[k_].copy(); PIX[k_][m_] = PIX[k_ - 1][m_]
noms = []
# retouches au pixel pres (choisies sur la grille : usine grille) : [{"image": "<tag>_<i>" | "*", "pixels": [[x, y, "#rrggbb" | "transparent"], ...]}]
RETOUCHE_ALERTES = []
for rt in R.get("retouches", []):
    for k_, (tag, i, *_r) in enumerate(PLAN):
        nt = TAGS_DIR[(tag, _r[-1])]
        if rt.get("image") not in ("*", f"{nt}_{i:02d}", f"{nt}_{i}"):
            continue
        p = PIX[k_]
        for x, y, c in rt["pixels"]:
            if 0 <= y < p.shape[0] and 0 <= x < p.shape[1]:
                p[y, x] = (0, 0, 0, 0) if c == "transparent" else (*hex_rgb(c), 1)
        part = len(rt["pixels"]) / max(1, int((p[..., 3] > 0).sum()))
        if part > 0.05:
            RETOUCHE_ALERTES.append(f"{nt}_{i:02d} : {part * 100:.0f} % des pixels retouches (au-dela de 5 % : corrige le modele ou la recette)")
for (tag, i, *_r), p in zip(PLAN, PIX):
    n = os.path.join(SORTIE, "pixel", f"{TAGS_DIR[(tag, _r[-1])]}_{i:02d}.png"); ecrire_image(n, p); noms.append(n)
# cartes de normales et d'emission, reduites exactement comme le sprite et masquees par lui
def reduire_carte(a, normale):
    rgb, cov = reduire(a)
    if normale:
        v = rgb * 2 - 1; v /= np.maximum(np.linalg.norm(v, axis=2, keepdims=True), 1e-6); rgb = (v + 1) / 2
    return rgb
for nom_c, liste, normale in (("normales", NORM_HD, True), ("emission", EMI_HD, False)):
    if not liste:
        continue
    os.makedirs(os.path.join(SORTIE, nom_c), exist_ok=True)
    bandes = []
    for (tag, i, *_r), a_, p in zip(PLAN, liste, PIX):
        rgb = reduire_carte(a_, normale); out = np.zeros_like(p)
        out[..., :3] = rgb[:p.shape[0], :p.shape[1]]
        if not normale:
            out[..., :3] = (out[..., :3].mean(2, keepdims=True) > 0.5).astype(float)
        out[..., 3] = p[..., 3]
        ecrire_image(os.path.join(SORTIE, nom_c, f"{TAGS_DIR[(tag, _r[-1])]}_{i:02d}.png"), out); bandes.append(out)
    os.makedirs(os.path.join("assets", "sprites", ID), exist_ok=True)
    ecrire_image(os.path.join("assets", "sprites", ID, f"{ID}_{nom_c}.png"), np.concatenate(bandes, 1))

# planche : rendu HD en haut, pixel x4 sur 3 fonds
K = 4
lignes = [np.concatenate(sum([[sur_fond(redimensionner(a, cw * K, ch * K), FONDS[0]), np.ones((ch * K, 4, 4))] for a in HD], [])[:-1], 1)]
for f in FONDS:
    lignes.append(np.concatenate(sum([[sur_fond(agrandir(p, K), f), np.ones((ch * K, 4, 4))] for p in PIX], [])[:-1], 1))
ecrire_image(os.path.join(SORTIE, f"{ID}_planche.png"), np.concatenate(sum([[l, np.ones((6, l.shape[1], 4))] for l in lignes], [])[:-1], 0))

# mesures automatiques (a comparer aux seuils de LISEZMOI.md)
hauts, rempl, sats, ncoul = [], [], [], set()
for p in PIX:
    m = p[..., 3] > 0; ys = np.nonzero(m.any(1))[0]
    hauts.append(int(ys.max() - ys.min() + 1) if len(ys) else 0); rempl.append(round(hauts[-1] / ch, 2))
    sats.append(saturation_moyenne(p)); ncoul |= {tuple((x * 255).round().astype(int)) for x in p[m][:, :3]}
diff = [float(np.abs(a - b).mean()) for a, b in zip(PIX, PIX[1:])]
mes = {"id": ID, "case": [cw, ch], "images": len(PIX), "rampes": RAMPES_UTIL, "hauteur_px": [min(hauts), max(hauts)],
       "remplissage": [min(rempl), max(rempl)], "saturation": round(float(np.mean(sats)), 3), "couleurs": len(ncoul),
       "images_identiques": sum(1 for d in diff if d == 0)}
alertes = []
if MES_CANON:
    mes["canon"] = {k: max(m[k] for m in MES_CANON) if k != "contraste_min" else min(m[k] for m in MES_CANON)
                    for k in ("isoles_pct", "traits_1px_pct", "contraste_min")}
    alertes += _canon.alertes(MES_CANON)
if mes["couleurs"] < 6 and not CANON: alertes.append("moins de 6 couleurs : sprite plat -> monte 'contraste' ou 'rampes_max'")
if mes["saturation"] < 0.12:
    alertes.append("sprite gris -> donne une \"couleur\" aux pieces construites ou utilise \"peindre\" (modelage)" if R.get("modelage")
                   else "sprite gris -> textures absentes ? donne 'couleurs' ou change de modele")
if mes["remplissage"][1] < 0.55: alertes.append("le sujet ne remplit pas sa case -> verifie 'vue' et 'taille_selon'")
# animation : assez de mouvement ? pas d'a-coup quand la boucle repart ?
_grp = {}
for k_, (tag, i, quoi, t_, ang) in enumerate(PLAN):
    _grp.setdefault((tag, ang), []).append(k_)
for (tag, ang), ks in _grp.items():
    if len(ks) < 3 or ks[-1] >= len(PIX):
        continue
    al = [PIX[k][..., 3] for k in ks]; aire = max(float(al[0].mean()), 1e-6)
    pas = [float(np.abs(PIX[a_] - PIX[b_]).mean()) for a_, b_ in zip(ks, ks[1:])]
    mvt = max(float(np.abs(x - al[0]).mean()) for x in al) / aire
    saut = float(np.abs(PIX[ks[-1]] - PIX[ks[0]]).mean()) / max(float(np.median(pas)), 1e-6)
    sp = ANIMS.get(tag, {}); boucle = sp.get("boucle", True)
    mes.setdefault("animation", {})[tag] = {"mouvement": round(mvt, 3), "saut_boucle": round(saut, 2) if boucle else None}
    if mvt < 0.03 and not sp.get("procedural") in ("respiration",):
        alertes.append(f"animation '{tag}' : presque aucun mouvement de silhouette ({mvt:.0%}) -> geste plus ample")
    if boucle and saut > 2.5:
        alertes.append(f"animation '{tag}' : a-coup quand la boucle repart (saut {saut:.1f} x un pas normal) -> "
                       "derniere image trop loin de la premiere : plage de l'action, ou \"boucle\": false si elle ne boucle pas")
if RACCORD:   # la jointure (dernier -> premier pixel) doit ressembler a l'interieur de l'image
    def _saut(p, ax):
        q = p[..., :3] * p[..., 3:4]
        dedans = float(np.abs(np.diff(q, axis=ax)).mean())
        bord = float(np.abs(q.take([-1], axis=ax) - q.take([0], axis=ax)).mean())
        return round(bord / max(dedans, 1e-6), 2)
    _axr = RACCORD.get("axes", "xy") if isinstance(RACCORD, dict) else str(RACCORD)
    mes["raccord"] = {a_: max(_saut(p, 1 if a_ == "x" else 0) for p in PIX) for a_ in _axr if a_ in "xy"}
    for a_, v in mes["raccord"].items():
        if v > 1.6:
            alertes.append(f"raccord {a_} visible (saut {v} x l'interieur) -> verifie la plaque '{_bn}' (elle fixe la case)")
    _p0 = PIX[0]; _r = (3, 3) if "y" in _axr else (1, 3)
    ecrire_image(os.path.join(SORTIE, f"{ID}_raccord.png"), agrandir(np.tile(_p0, _r + (1,)), 3))
if len(PIX) > 1 and mes["images_identiques"] > len(PIX) // 2: alertes.append("animation figee -> mauvaise 'action' ou 'procedural'")
mes["alertes"] = alertes
json.dump(mes, open(os.path.join(SORTIE, f"{ID}_mesures.json"), "w"), indent=1)
ORDRE_TAGS = []
for tag, i, quoi, t, ang in PLAN:
    if TAGS_DIR[(tag, ang)] not in ORDRE_TAGS:
        ORDRE_TAGS.append(TAGS_DIR[(tag, ang)])
TAG_DE = [TAGS_DIR[(tag, ang)] for tag, i, quoi, t, ang in PLAN]
BASE_DE = {TAGS_DIR[(tag, ang)]: tag for tag, i, quoi, t, ang in PLAN}
json.dump({"id": ID, "tags": {t: [n for tt, n in zip(TAG_DE, noms) if tt == t] for t in ORDRE_TAGS},
           "durees_ms": {t: int(ANIMS[BASE_DE[t]].get("duree_ms", 100)) for t in ORDRE_TAGS}},
          open(os.path.join(SORTIE, "images.json"), "w"), indent=1)
# donnees du sprite pour le moteur : origine, boite visible, points suivis, boites demandees, evenements, durees
for k_, p in enumerate(PIX):
    m_ = p[..., 3] > 0; ys, xs = np.nonzero(m_)
    DONNEES_IMG[k_]["visible"] = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)] if len(xs) else None
EVTS = {}
for nom_e, spec in R.get("evenements", {}).items():
    for tg in ORDRE_TAGS:
        idx = [k for k, d in enumerate(DONNEES_IMG) if d["tag"] == tg]
        if "images" in spec:
            EVTS.setdefault(tg, {})[nom_e] = [int(x) for x in spec["images"]]
        elif "contact" in spec:  # le point touche le sol : il est au plus bas (a 2 % pres) alors qu'il etait plus haut avant
            zs = [DONNEES_IMG[k].get("_z", {}).get(SUIVI_DE.get(spec["contact"], spec["contact"])) for k in idx]
            if None in zs or not zs:
                print(f"  ATTENTION : evenement '{nom_e}' : point '{spec['contact']}' inconnu ou introuvable "
                      f"(points suivis : {sorted(SUIVIS)}) -> mets-le dans \"points\" ou utilise un de ceux-la")
                continue
            zmin = min(zs); tol = 0.02 * TAILLE0
            EVTS.setdefault(tg, {})[nom_e] = [j for j in range(len(zs)) if zs[j] <= zmin + tol and zs[j - 1] > zmin + tol]
for d in DONNEES_IMG:
    d.pop("_z", None)
DONNEES = {"id": ID, "case": [cw, ch], "unite": "pixels du sprite, origine en haut a gauche de chaque image",
           "durees_ms": {t: int(ANIMS[BASE_DE[t]].get("duree_ms", 100)) for t in ORDRE_TAGS},
           "evenements": EVTS, "images": DONNEES_IMG,
           "cartes": [c for c, l in (("normales", NORM_HD), ("emission", EMI_HD)) if l]}
os.makedirs(os.path.join("assets", "sprites", ID), exist_ok=True)
json.dump(DONNEES, open(os.path.join("assets", "sprites", ID, f"{ID}_donnees.json"), "w"), indent=1, ensure_ascii=False)
json.dump(DONNEES, open(os.path.join(SORTIE, f"{ID}_donnees.json"), "w"), indent=1, ensure_ascii=False)
mes["alertes"] += RETOUCHE_ALERTES
# ------------------------------------------------- sorties du kit de jeu
if mode_kit():
    os.makedirs("boards", exist_ok=True)
    planche = os.path.join(SORTIE, f"{ID}_planche.png")
    shutil.copyfile(planche, f"boards/{ID}_modifie.png")
    reglage = {k: v for k, v in PARAMS.items()}
    kit_iteration(ID, planche, f"fabrication : vue {R.get('vue', 'cote')}, {taille_px} px, reglage {reglage or 'par defaut'}, "
                               f"animations {', '.join(ANIMS)}, accessoires {len(R.get('accessoires', []))}")
    sources = []; construit = False
    for chemin_m in [R["modele"]] + ([R["animations_depuis"]] if R.get("animations_depuis") else []) + \
            [a["modele"] for a in R.get("accessoires", [])]:
        dm = dossier_modele(chemin_m)
        if not dm:
            print(f"  ATTENTION : pas de provenance.json pour {chemin_m} (passe par usine obtenir ou usine gabarit)")
            continue
        pv = json.load(open(os.path.join(dm, "provenance.json")))
        if chemin_m == R["modele"] and pv.get("genere") and not pv.get("sources_modelage"):
            construit = True   # construit de zero par l'usine : pas de modele telecharge a declarer
        else:
            entree = {k: pv.get(k) for k in ("id", "type", "url", "licence", "auteur", "fichier", "sha256", "page_licence")}
            kit_upsert("PROVENANCE.json", "sources", entree); sources.append(entree["id"])
        if chemin_m == R["modele"]:
            if os.path.exists(os.path.join(dm, "apercu.png")):
                shutil.copyfile(os.path.join(dm, "apercu.png"), f"boards/{ID}_base.png")
            vig = sorted(glob.glob(os.path.join(dm, "vignette_officielle.*")))
            if not vig and os.path.exists(os.path.join(dm, "apercu.png")):  # modele construit : pas de vignette officielle
                shutil.copyfile(os.path.join(dm, "apercu.png"), f"boards/{ID}_reference.png")
            if vig and os.path.exists(os.path.join(dm, "apercu.png")):
                b = lire_image(os.path.join(dm, "apercu.png")); H = 320
                b = ajuster(b, max(1, int(b.shape[1] * H / max(b.shape[0], 1))), H)
                try:
                    a = lire_image(vig[0])
                    if a.ndim < 3 or min(a.shape[:2]) < 2:
                        raise ValueError("image vide")
                    a = ajuster(a, max(1, int(a.shape[1] * H / a.shape[0])), H)
                    ecrire_image(f"boards/{ID}_reference.png", np.concatenate([a, np.ones((H, 10, 4)), b], 1))
                except Exception as e:  # vignette du site illisible (format exotique) : la reference = l'apercu seul
                    print(f"  (vignette officielle illisible ({e}) : boards/{ID}_reference.png = apercu seul)")
                    ecrire_image(f"boards/{ID}_reference.png", b)
    typ = R.get("type") or ("vivant" if any(sp.get("action") or sp.get("procedural") in ("onde", "pulsation", "rebond", "respiration")
                                            for sp in ANIMS.values()) else "prop")
    kit_upsert("art/manifest.json", "sprites", {
        "id": ID, "data_id": R.get("data_id", ID), "type": typ, "filiere": "construit" if construit else "3d", "biome": R.get("biome"),
        "recette": os.path.relpath(RECETTE).replace("\\", "/") if construit else None, "mesures_canon": mes.get("canon"),
        "provisoire": bool(R.get("provisoire", False)), "sources": sources,
        "blend": f"art/source/blender/{ID}.blend", "aseprite": f"art/source/aseprite/{ID}.aseprite",
        "sheet": f"assets/sprites/{ID}/{ID}.png", "data": f"assets/sprites/{ID}/{ID}.json",
        "planches": {"base": f"boards/{ID}_base.png", "modifie": f"boards/{ID}_modifie.png",
                     "iterations": sorted([x.replace("\\", "/") for x in glob.glob(f"boards/iterations/{ID}_it*.png")],
                                          key=lambda x: int(re.search(r"_it(\d+)", x).group(1)))}})
    print(f"  KIT : manifeste, provenance, .blend et planches a jour (type {typ}).")
print("FABRIQUE_OK", json.dumps(mes, ensure_ascii=False))
