"""geometrie : le coeur mathematique du modelage (utilise dans Blender par modeler.py).

Principe : l'IA ne donne JAMAIS de coordonnees. Elle nomme des zones et des contraintes
("sur le dos, en contact, axe vers le haut, symetrique") ; ce module calcule les nombres exacts
sur la VRAIE surface du modele et MESURE le resultat (enfoncement, flottement, symetrie).

Unites : toutes les longueurs de la recette sont des fractions de H = hauteur du sujet
(0.3 = 30 % de la hauteur). Les angles sont en degres.
"""
import os, math
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

# ------------------------------------------------------------------ import

FORMATS_3D = (".glb", ".gltf", ".blend", ".fbx", ".obj", ".dae", ".stl", ".ply", ".usd", ".usdz", ".usdc", ".usda", ".x3d", ".wrl", ".abc")


def importer(f):
    """Importe un fichier 3D (tous formats courants) et renvoie les nouveaux objets. Seul importeur de l'usine."""
    from commun import reparer_textures, synchroniser_couleurs, montrer_si_tout_cache
    if not os.path.isfile(f):
        raise SystemExit(f"ERREUR : fichier 3D introuvable : {f} (verifie le chemin : il part de la racine du projet)")
    avant = set(bpy.data.objects)
    ext = os.path.splitext(f)[1].lower()
    try:
        if ext in (".gltf", ".glb"):
            bpy.ops.import_scene.gltf(filepath=f)
        elif ext == ".fbx":
            bpy.ops.import_scene.fbx(filepath=f)
        elif ext == ".obj":
            bpy.ops.wm.obj_import(filepath=f)
        elif ext == ".dae":
            bpy.ops.wm.collada_import(filepath=f)
        elif ext == ".stl":
            bpy.ops.wm.stl_import(filepath=f)
        elif ext == ".ply":
            bpy.ops.wm.ply_import(filepath=f)
        elif ext in (".usd", ".usdz", ".usdc", ".usda"):
            bpy.ops.wm.usd_import(filepath=f)
        elif ext in (".x3d", ".wrl"):
            bpy.ops.import_scene.x3d(filepath=f)
        elif ext == ".abc":
            bpy.ops.wm.alembic_import(filepath=f)
        elif ext == ".blend":
            with bpy.data.libraries.load(f, link=False) as (src, dst):
                dst.objects = list(src.objects); dst.actions = list(src.actions)
            for o in dst.objects:
                if o is not None and o.type in ("MESH", "ARMATURE", "EMPTY", "CURVE", "FONT", "SURFACE", "META", "CURVES"):
                    bpy.context.scene.collection.objects.link(o)
        else:
            raise SystemExit(f"ERREUR : format non gere : {ext} (formats : {' '.join(FORMATS_3D)}). "
                             "Prends un autre numero de 'chercher' ou un autre fichier du meme modele.")
    except (RuntimeError, AttributeError) as e:
        if ext == ".dae":
            e = "le format Collada (.dae) n'est plus lu par cette version de Blender"
        raise SystemExit(f"ERREUR : le fichier {os.path.basename(f)} ne s'ouvre pas ({str(e).strip()[:200]}). "
                         "Prends un autre fichier du meme modele (autre format) ou un autre numero de 'chercher'.")
    nouveaux = [o for o in bpy.data.objects if o not in avant]
    # courbes, textes, surfaces, metaballs : convertis en maillages (le reste de l'usine travaille sur des maillages)
    for o in [o for o in nouveaux if o.type in ("CURVE", "FONT", "SURFACE", "META")]:
        try:
            dg = bpy.context.evaluated_depsgraph_get()
            me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
            if me is None or not len(me.polygons):
                continue
            nv = bpy.data.objects.new(o.name + "_maillage", me)
            for c in o.users_collection:
                c.objects.link(nv)
            nv.matrix_world = o.matrix_world.copy(); nv.parent = o.parent
            if o.parent:
                nv.parent_type = o.parent_type; nv.parent_bone = o.parent_bone; nv.matrix_world = o.matrix_world.copy()
            nv.hide_render = o.hide_render
            for m in getattr(o.data, "materials", []):
                if m and m.name not in [x.name for x in me.materials if x]:
                    me.materials.append(m)
            o.hide_render = True
            nouveaux.append(nv)
        except Exception as e:
            print(f"  ({o.name} non converti en maillage : {e})")
    if not any(o.type == "MESH" and len(o.data.polygons) for o in nouveaux):
        raise SystemExit(f"ERREUR : {os.path.basename(f)} ne contient aucune surface 3D (que des points, os ou lignes). "
                         "Prends un autre numero de 'chercher' ou un autre fichier du meme modele.")
    reparer_textures(os.path.dirname(os.path.abspath(f)))
    reparer_textures(os.path.dirname(os.path.dirname(os.path.abspath(f))))
    montrer_si_tout_cache(nouveaux)
    cacher_geants(nouveaux)
    synchroniser_couleurs()
    return nouveaux


def cacher_geants(objs):
    """Sol immense, ciel, copie oubliee a l'echelle x100 : un objet 12 fois plus grand que TOUT le reste reuni
    ecrase le cadrage (le sujet devient un point). On le cache et on le dit."""
    ms = [o for o in objs if o.type == "MESH" and visible(o) and len(o.data.vertices)]
    if len(ms) < 2:
        return
    bpy.context.view_layer.update()
    def boite(lst):
        p = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in lst])
        return float((p.max(0) - p.min(0)).max())
    ms.sort(key=lambda o: -boite([o]))
    tailles = [boite([o]) for o in ms]
    # objets degeneres (tous les sommets au meme endroit) : ils ne comptent pas comme "le reste"
    garde = [i for i, t in enumerate(tailles) if t > 1e-4 * max(tailles)]
    ms = [ms[i] for i in garde]; tailles = [tailles[i] for i in garde]
    if len(ms) < 2:
        return
    caches = []
    nv = [len(o.data.vertices) for o in ms]
    for k in range(1, len(ms)):  # les k plus grands sont-ils TOUS 12 fois plus grands que le reste reuni ?
        # ... et legers (sol, ciel, copie) : un CORPS avec ses petits yeux porte la plupart des sommets, il reste
        if tailles[k - 1] > 12 * max(boite(ms[k:]), 1e-9) and sum(nv[:k]) < 0.5 * sum(nv):
            for o in ms[:k]:
                o.hide_render = True; caches.append(o.name)
            break
    if caches:
        print(f"  ATTENTION : objet(s) geant(s) cache(s) (sol, ciel ou copie a la mauvaise echelle) : {caches}")


def visible(o):
    """Faux pour les objets techniques : formes d'affichage des os, collections non rendues, objets caches."""
    if o.hide_render:
        return False
    if any(c.hide_render or c.name == "glTF_not_exported" for c in o.users_collection):
        return False
    for a in bpy.data.objects:
        if a.type == "ARMATURE" and a.pose and any(pb.custom_shape == o for pb in a.pose.bones):
            return False
    return True


def maillages(objs):
    return [o for o in objs if o.type == "MESH" and visible(o)]


def points_monde(objs, max_points=None):
    """Sommets en coordonnees monde, APRES deformation (squelette, modificateurs)."""
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in maillages(objs):
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        a = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", a)
        a = a.reshape(-1, 3)
        M = np.array(o.matrix_world)
        a = a @ M[:3, :3].T + M[:3, 3]
        ev.to_mesh_clear()
        pts.append(a)
    p = np.concatenate(pts) if pts else np.zeros((0, 3))
    if max_points and len(p) > max_points:
        p = p[np.linspace(0, len(p) - 1, max_points).astype(int)]
    return p


def points_surface_uniformes(objs, n=20000, graine=0):
    """Points tires uniformement sur la SURFACE (au prorata de l'aire des triangles), coordonnees monde."""
    dg = bpy.context.evaluated_depsgraph_get()
    tris = []
    for o in maillages(objs):
        ev = o.evaluated_get(dg); me = ev.to_mesh(); me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
        M = np.array(o.matrix_world); co = co @ M[:3, :3].T + M[:3, 3]
        t = np.empty(len(me.loop_triangles) * 3, dtype=np.int64); me.loop_triangles.foreach_get("vertices", t)
        tris.append(co[t.reshape(-1, 3)])
        ev.to_mesh_clear()
    if not tris:
        return np.zeros((0, 3))
    T = np.concatenate(tris)
    aire = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    if aire.sum() <= 0:
        return T.reshape(-1, 3)
    rng = np.random.default_rng(graine)
    k = rng.choice(len(T), n, p=aire / aire.sum())
    u, v = rng.random(n), rng.random(n); dehors = u + v > 1; u[dehors], v[dehors] = 1 - u[dehors], 1 - v[dehors]
    return T[k, 0] + (T[k, 1] - T[k, 0]) * u[:, None] + (T[k, 2] - T[k, 0]) * v[:, None]


def bvh_monde(objs):
    """Un seul arbre de recherche sur toute la surface (coordonnees monde, pose actuelle)."""
    dg = bpy.context.evaluated_depsgraph_get()
    verts, polys, base = [], [], 0
    for o in maillages(objs):
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        M = o.matrix_world
        verts += [M @ v.co for v in me.vertices]
        polys += [[i + base for i in p.vertices] for p in me.polygons]
        base += len(me.vertices)
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys) if polys else None


# ------------------------------------------------------------------ repere

def _pca(p):
    c = p.mean(0)
    w, v = np.linalg.eigh(np.cov((p - c).T))
    return c, w[::-1], v[:, ::-1].T  # axes du plus long au plus court


def score_symetrie(p, centre, n, kd=None, echelle=1.0):
    """Ecart moyen (fraction de la taille) entre le modele et son reflet par le plan (centre, normale n)."""
    if kd is None:
        kd = KDTree(len(p))
        for i, x in enumerate(p):
            kd.insert(x, i)
        kd.balance()
    n = np.array(n) / np.linalg.norm(n)
    q = p - 2 * np.outer((p - centre) @ n, n)
    d = [kd.find(Vector(x))[2] for x in q[:: max(1, len(q) // 1500)]]
    return float(np.mean(d)) / echelle


def repere(objs, armature=None):
    """Haut (u), avant (f), droite (r) du SUJET, son centre et sa hauteur H.
    Haut : le squelette (bas -> tete) s'il existe, sinon l'axe Z (convention de tous les imports).
    Cote : plan de symetrie du modele (calcule), avant : pieds/orteils, sinon convention glTF (-Y)."""
    p = points_monde(objs, 20000)
    lo, hi = p.min(0), p.max(0)
    u = np.array([0.0, 0.0, 1.0]); source_haut = "axe Z"
    os_ = {}
    if armature:
        os_ = {b.name.lower(): b for b in armature.data.bones}
        M = armature.matrix_world
        tete = next((b for n, b in os_.items() if "head" in n and "end" not in n), None)
        bas = next((b for n, b in os_.items() if any(k in n for k in ("hips", "pelvis", "root"))), None)
        if tete and bas:
            v = np.array(M @ tete.head_local) - np.array(M @ bas.head_local)
            if np.linalg.norm(v) > 1e-6 and abs(v @ u) / np.linalg.norm(v) > 0.6:
                u = v / np.linalg.norm(v); source_haut = "squelette"
    # plan de symetrie : on teste les directions horizontales (pas de 3 degres)
    centre = (lo + hi) / 2
    taille = float(np.linalg.norm(hi - lo))
    kd = KDTree(len(p))
    for i, x in enumerate(p):
        kd.insert(x, i)
    kd.balance()
    a0 = np.cross(u, [1, 0, 0]) if abs(u[0]) < 0.9 else np.cross(u, [0, 1, 0]); a0 /= np.linalg.norm(a0)
    b0 = np.cross(u, a0)
    meilleurs = []
    for k in range(60):
        t = math.pi * k / 60
        n = math.cos(t) * a0 + math.sin(t) * b0
        c = centre.copy(); c -= ((c - p.mean(0)) @ n) * n
        meilleurs.append((score_symetrie(p, c, n, kd, taille), k, n))
    sc, k, lat = min(meilleurs, key=lambda x: x[0])
    symetrique = sc < 0.02
    # sans symetrie nette : on garde les axes du monde (convention : avant -Y, droite du sujet -X)
    if not symetrique:
        lat = np.array([1.0, 0, 0]) - u * u[0]; lat /= np.linalg.norm(lat)
    f = np.cross(u, lat); f /= np.linalg.norm(f)
    source_avant = "convention glTF (-Y)"
    if armature:
        pieds = [b for n, b in os_.items() if any(k in n for k in ("toe", "foot", "ball")) and "end" not in n]
        v = np.zeros(3)
        for b in pieds:
            d = np.array(armature.matrix_world @ b.tail_local) - np.array(armature.matrix_world @ b.head_local)
            v += d - (d @ u) * u
        if np.linalg.norm(v) > 1e-6:
            if v @ f < 0:
                f = -f
            source_avant = "pieds du squelette"
        elif f @ np.array([0, -1, 0]) < 0:
            f = -f
    elif f @ np.array([0, -1, 0]) < 0:
        f = -f
    r = np.cross(f, u); r /= np.linalg.norm(r)  # droite DU SUJET (comme sa main droite)
    # dimensions dans le repere du sujet
    q = p - centre
    H = float((q @ u).max() - (q @ u).min())
    bas_ = centre + u * float((q @ u).min())
    centre_sym = centre - ((centre - p.mean(0)) @ r) * r if symetrique else centre
    return {"u": Vector(u), "f": Vector(f), "r": Vector(r), "centre": Vector(centre_sym), "bas": Vector(bas_),
            "H": H, "largeur": float(np.ptp(q @ r)), "profondeur": float(np.ptp(q @ f)),
            "symetrique": symetrique, "ecart_symetrie": round(sc, 4),
            "source_haut": source_haut, "source_avant": source_avant}


def retourner(rep):
    """L'IA a vu que l'avant est a l'arriere : on inverse avant et droite."""
    rep = dict(rep); rep["f"] = -rep["f"]; rep["r"] = -rep["r"]; rep["source_avant"] = "corrige par l'IA"
    return rep


DIRECTIONS = {"haut": ("u", 1), "dessus": ("u", 1), "bas": ("u", -1), "dessous": ("u", -1),
              "avant": ("f", 1), "devant": ("f", 1), "arriere": ("f", -1), "derriere": ("f", -1), "dos": ("f", -1),
              "droite": ("r", 1), "gauche": ("r", -1)}


def direction(nom, rep):
    """'haut', 'avant', 'arriere-gauche', 'haut+avant', ou [x, y, z] dans le repere (droite, avant, haut)."""
    if isinstance(nom, (list, tuple)):
        if len(nom) != 3:
            raise SystemExit(f"direction [droite, avant, haut] attendue (3 nombres), recu : {nom}")
        v = rep["r"] * float(nom[0]) + rep["f"] * float(nom[1]) + rep["u"] * float(nom[2])
        if v.length < 1e-9:
            raise SystemExit("direction nulle : [0, 0, 0]")
        return v.normalized()
    if not isinstance(nom, str):
        raise SystemExit(f"direction attendue (mot comme 'haut' ou [droite, avant, haut]), recu : {nom}")
    v = Vector((0, 0, 0))
    for mot in nom.replace("+", "-").replace(" ", "-").split("-"):
        if not mot:
            continue
        if mot not in DIRECTIONS:
            raise SystemExit(f"direction inconnue : '{mot}'. Directions : {sorted(DIRECTIONS)}")
        ax, s = DIRECTIONS[mot]
        v += rep[ax] * s
    if v.length < 1e-9:
        raise SystemExit(f"direction nulle : '{nom}' (deux directions opposees ?)")
    return v.normalized()


def vers_repere(p, rep):
    """Point monde -> (droite, avant, haut) en fractions de H depuis le centre."""
    d = Vector(p) - rep["centre"]
    return [round(d.dot(rep["r"]) / rep["H"], 3), round(d.dot(rep["f"]) / rep["H"], 3), round(d.dot(rep["u"]) / rep["H"], 3)]


def depuis_repere(c, rep):
    return rep["centre"] + (rep["r"] * c[0] + rep["f"] * c[1] + rep["u"] * c[2]) * rep["H"]


# ------------------------------------------------------------------ zones

# zone -> (mots du nom de l'os, cote par defaut). Le cote gauche/droite est CALCULE (position de l'os), pas lu dans le nom.
OS_ZONES = {
    "tete": (("head",), "dessus"), "cou": (("neck",), "avant"),
    "torse": (("chest", "torso", "spine2", "spine_03", "spine02", "upperchest", "spine1", "spine_02", "upperbody", "spine"), "avant"),
    "dos": (("chest", "torso", "spine2", "spine_03", "spine02", "upperchest", "spine1", "spine_02", "upperbody", "spine"), "arriere"),
    "ventre": (("spine", "spine1", "spine_01", "spine01", "abdomen"), "avant"),
    "hanches": (("hips", "pelvis"), "avant"), "ceinture": (("hips", "pelvis"), "avant"),
    "epaule": (("shoulder", "clavicle"), "dessus"), "bras": (("upperarm", "arm"), "dehors"),
    "avant_bras": (("forearm", "lowerarm"), "dehors"), "main": (("hand", "palm", "wrist"), "dehors"),
    "cuisse": (("thigh", "upperleg", "upleg"), "avant"), "jambe": (("calf", "shin", "lowerleg", "leg"), "avant"),
    "pied": (("foot",), "avant"), "queue": (("tail",), "arriere"),
}
PAIRES = {"epaule", "bras", "avant_bras", "main", "cuisse", "jambe", "pied"}


def _os_zone(armature, mots, rep, cote_sujet=None):
    """Meilleur os pour une zone ; cote_sujet = 'gauche'/'droite' pour les paires (calcule par la position)."""
    if armature is None:
        return None
    M = armature.matrix_world
    for m in mots:
        cand = []
        for b in armature.data.bones:
            n = b.name.lower().replace(" ", "")
            if m in n and not n.endswith(("end", "_end", "nub", "top")) and "twist" not in n and "finger" not in n \
                    and "thumb" not in n and "index" not in n and "toe" not in n:
                mid = M @ ((b.head_local + b.tail_local) / 2)
                x = (mid - rep["centre"]).dot(rep["r"])
                if cote_sujet == "droite" and x <= 0.01 * rep["H"]:
                    continue
                if cote_sujet == "gauche" and x >= -0.01 * rep["H"]:
                    continue
                # pour une zone du tronc, l'os le plus centre ; on prefere le nom exact
                # 1er critere : un os qui DEFORME la peau (Rigify : DEF-forearm, pas la commande forearm_fk)
                cand.append((0 if b.use_deform else 1, 0 if n.split(":")[-1].strip("_.") == m else 1,
                             abs(x) if not cote_sujet else 0, len(n), b))
        if cand:
            return min(cand, key=lambda c: c[:4])[4]
    return None


def zones(objs, armature, rep):
    """Toutes les zones nommees du sujet : {nom: {"point", "cote", "os"}}.
    Toujours disponibles : centre, haut, bas, avant, arriere, gauche, droite (+ leurs combinaisons).
    Avec un squelette : tete, cou, torse, dos, ventre, hanches, epaule_g/d, bras_g/d, main_g/d, pied_g/d..."""
    z = {}
    c, H = rep["centre"], rep["H"]
    p = points_monde(objs, 20000)
    q = p - np.array(c)
    z["centre"] = {"point": c.copy(), "cote": "avant", "os": None}
    for nom in ("haut", "bas", "avant", "arriere", "droite", "gauche"):
        # ancre au centre du sujet : la surface est trouvee en partant dans cette direction
        z[nom] = {"point": c.copy(), "cote": {"haut": "dessus", "bas": "dessous"}.get(nom, nom), "os": None}
    if armature:
        M = armature.matrix_world
        noms_os = [b.name.lower() for b in armature.data.bones]
        humanoide = any("head" in n for n in noms_os) and any(k in n for n in noms_os for k in ("hips", "pelvis", "spine")) \
            and any(k in n for n in noms_os for k in ("arm", "hand", "leg", "thigh", "foot"))
        # chaque os est une zone "os:<nom>" (queue, aile, machoire, couvercle... de n'importe quel squelette)
        for b in armature.data.bones:
            if b.use_deform or not b.children:
                pt = M @ ((b.head_local + b.tail_local) / 2)
                z["os:" + b.name] = {"point": pt, "cote": "dehors", "os": b.name,
                                     "axe_os": (M @ b.tail_local - M @ b.head_local).normalized()}
    if armature and humanoide:
        for nom, (mots, cote) in OS_ZONES.items():
            for suffixe, cs in ([("_d", "droite"), ("_g", "gauche")] if nom in PAIRES else [("", None)]):
                b = _os_zone(armature, mots, rep, cs)
                if b is None:
                    continue
                pt = M @ ((b.head_local + b.tail_local) / 2)
                if nom == "tete":
                    pt = M @ b.head_local + rep["u"] * 0.06 * H  # milieu du crane, pas la base du cou
                cote_reel = cote
                if cote == "dehors":
                    cote_reel = cs or "droite"
                axe = (M @ b.tail_local - M @ b.head_local).normalized()
                z[nom + suffixe] = {"point": pt, "cote": "dehors" if cote == "dehors" else cote_reel, "os": b.name, "axe_os": axe}
    elif armature:
        # squelette non humain (animal, monstre...) : les noms SANS ambiguite seulement (Head = tete, Tail = queue...)
        M = armature.matrix_world
        def prof(b):
            k = 0
            while b.parent:
                b = b.parent; k += 1
            return k
        for nom, mots, cote in (("tete", ("head", "skull", "tete"), "dessus"), ("cou", ("neck",), "dehors"),
                                ("queue", ("tail", "queue"), "dehors"), ("machoire", ("jaw", "machoire"), "dessous")):
            bs = [b for b in armature.data.bones if any(m in b.name.lower() for m in mots) and not b.name.lower().endswith("_end")]
            if not bs or nom in z:
                continue
            b = min(bs, key=lambda b: (prof(b), b.name))
            z[nom] = {"point": M @ ((b.head_local + b.tail_local) / 2), "cote": cote, "os": b.name,
                      "axe_os": (M @ b.tail_local - M @ b.head_local).normalized()}
    return z


def direction_zone(zone, cote, rep):
    """Direction de pose : un nom de direction, ou 'dehors' = perpendiculaire a l'os, vers l'exterieur du corps."""
    if cote != "dehors":
        return direction(cote, rep)
    axe = zone.get("axe_os")
    v = Vector(zone["point"]) - rep["centre"]
    if axe is not None:
        v = v - axe * v.dot(axe)
        if v.length < 1e-6 or abs(axe.dot(rep["r"])) > 0.8:  # bras tendu a l'horizontale : dehors = vers l'avant
            v = rep["f"].copy()
    return v.normalized()


# ------------------------------------------------------------------ surface

def point_surface(bvh, depart, d, H):
    """Point de la surface atteint en partant de 'depart' dans la direction d (depuis l'interieur ou l'exterieur)."""
    d = d.normalized()
    P = 60 * H  # portee large : un sujet plat et long (H petit) depasse souvent 3 H en largeur
    hit = bvh.ray_cast(depart, d, P)
    if hit[0] is not None:
        return hit[0], hit[1]
    loin = depart + d * P
    hit = bvh.ray_cast(loin, -d, 2 * P)
    if hit[0] is not None:
        return hit[0], hit[1]
    # la droite ne touche pas le sujet (anneau, objet creux, pieces separees) : surface la plus proche de cette droite
    meilleur = None
    for k in range(1, 41):
        q = depart + d * (k / 40) * 3 * H
        loc, nor, _, dist = bvh.find_nearest(q)
        if loc is not None and (meilleur is None or (loc - depart).dot(d) > (meilleur[0] - depart).dot(d)):
            meilleur = (loc, nor)
    return meilleur if meilleur else (None, None)


_RAYONS = [Vector(v) for v in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]


def _dedans_par_rayons(bvh, x, limite):
    """Vote de 6 rayons : le point est dedans si le 1er impact est l'ENVERS d'une face (on sort de la matiere).
    Fiable meme pour des modeles faits de pieces qui se chevauchent (articulations, faces internes)."""
    oui = non = 0
    for d in _RAYONS:
        hit = bvh.ray_cast(x + d * 1e-6, d, 4 * limite)
        if hit[0] is None:
            non += 1
        elif hit[1].dot(d) > 0:
            oui += 1
        else:
            non += 1
    return oui >= 4 if oui != 3 else None


_RAYONS14 = _RAYONS + [Vector((x, y, z)).normalized() for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]


def part_englobee(pts, bvh, portee):
    """Part des points ENTOURES par la piece (casque, cloche, coque ouverte) : un point compte s'il voit la piece
    dans au moins 45 % de 14 directions (une ouverture en bas ou pour le visage reste permise)."""
    if not len(pts):
        return 0.0
    ok = 0
    for x in pts:
        xv = Vector(x)
        n = sum(1 for d in _RAYONS14 if bvh.ray_cast(xv, d, portee)[0] is not None)
        ok += n >= 0.45 * len(_RAYONS14)
    return ok / len(pts)


def profondeur_dedans(pts, bvh, limite):
    """Pour chaque point : >0 = enfonce dans la surface (distance), <0 = dehors (distance a la surface)."""
    out = np.empty(len(pts))
    for i, x in enumerate(pts):
        xv = Vector(x)
        loc, nor, _, dist = bvh.find_nearest(xv, limite)
        if loc is None:
            out[i] = -limite
            continue
        dedans = (xv - loc).dot(nor) < 0
        if dedans:  # le test de la normale la plus proche se trompe pres des faces internes : on confirme par rayons
            v = _dedans_par_rayons(bvh, xv, limite)
            if v is not None:
                dedans = v
        out[i] = dist if dedans else -dist
    return out


def mesurer_contact(piece_objs, bvh, H):
    pts = points_monde(piece_objs, 3000)
    if not len(pts) or bvh is None:
        return {"enfoncement": 0.0, "ecart": 1.0}
    d = profondeur_dedans(pts, bvh, H)
    return {"enfoncement": round(float(max(0.0, d.max())) / H, 4), "ecart": round(float(max(0.0, -d.max())) / H, 4),
            "part_dedans": round(float((d > 0.002 * H).mean()), 3)}


def deplacer(objs, v):
    for o in objs:
        if o.parent is None or o.parent not in objs:
            o.matrix_world = Matrix.Translation(v) @ o.matrix_world
    bpy.context.view_layer.update()


def resoudre_contact(piece_objs, bvh, d, H, tolerance=0.004):
    """Glisse la piece le long de d jusqu'a TOUCHER la surface sans y entrer (dichotomie sur la distance).
    Hypothese de depart : la piece est centree sur le point de surface."""
    pts0 = points_monde(piece_objs, 2500)
    ext = float(np.ptp((pts0 - pts0.mean(0)) @ np.array(d))) if len(pts0) else 0.1 * H

    def enf(t):
        p = pts0 + np.array(d) * t
        return float(max(0.0, profondeur_dedans(p, bvh, H).max()))

    lo, hi = 0.0, ext * 1.5 + 0.05 * H
    if enf(lo) <= tolerance * H:
        hi = lo  # deja en contact sans enfoncement : on cherche a rapprocher (vers l'interieur)
        lo = -ext
        for _ in range(22):
            m = (lo + hi) / 2
            if enf(m) <= tolerance * H:
                hi = m
            else:
                lo = m
        t = hi
    else:
        while enf(hi) > tolerance * H and hi < 6 * H:
            hi *= 1.6
        for _ in range(22):
            m = (lo + hi) / 2
            if enf(m) <= tolerance * H:
                hi = m
            else:
                lo = m
        t = hi
    deplacer(piece_objs, Vector(d) * t)
    return t


# ------------------------------------------------------------------ orientation

def axe_principal(objs):
    p = points_monde(objs, 4000)
    _, _, ax = _pca(p)
    return Vector(ax[0]), Vector(ax[1]), Vector(ax[2])


def orienter(objs, axe_piece, cible, autour=0.0, centre=None):
    """Tourne les objets pour que leur axe 'axe_piece' pointe vers 'cible', puis tourne de 'autour' degres autour de cible."""
    q = axe_piece.normalized().rotation_difference(cible.normalized())
    R = q.to_matrix().to_4x4()
    if autour:
        R = Matrix.Rotation(math.radians(autour), 4, cible.normalized()) @ R
    if centre is None:
        p = points_monde(objs, 3000); centre = Vector(p.mean(0))
    T = Matrix.Translation(centre) @ R @ Matrix.Translation(-centre)
    for o in objs:
        if o.parent is None or o.parent not in objs:
            o.matrix_world = T @ o.matrix_world
    bpy.context.view_layer.update()


def mettre_a_taille(objs, taille_m, mesure="max", axe=None):
    p = points_monde(objs, 4000)
    if axe is not None:
        t = float(np.ptp(p @ np.array(axe)))
    else:
        t = float(np.ptp(p, 0).max())
    k = taille_m / max(t, 1e-9)
    c = Vector(p.mean(0))
    S = Matrix.Translation(c) @ Matrix.Scale(k, 4) @ Matrix.Translation(-c)
    for o in objs:
        if o.parent is None or o.parent not in objs:
            o.matrix_world = S @ o.matrix_world
    bpy.context.view_layer.update()


def centrer_sur(objs, point):
    p = points_monde(objs, 4000)
    deplacer(objs, Vector(point) - Vector((p.min(0) + p.max(0)) / 2))


def miroir(objs, rep, nom_suffixe="_sym"):
    """Copie symetrique par le plan median du sujet (plan (centre, droite))."""
    n = rep["r"]; c = rep["centre"]
    S = Matrix.Identity(4) - 2 * Matrix(((n.x * n.x, n.x * n.y, n.x * n.z, 0), (n.y * n.x, n.y * n.y, n.y * n.z, 0),
                                          (n.z * n.x, n.z * n.y, n.z * n.z, 0), (0, 0, 0, 0)))
    S[3][3] = 1
    T = Matrix.Translation(c) @ S @ Matrix.Translation(-c)
    copies = []
    for o in objs:
        k = o.copy(); k.data = o.data.copy(); k.name = o.name + nom_suffixe
        bpy.context.scene.collection.objects.link(k)
        k.matrix_world = T @ o.matrix_world
        # un miroir inverse les faces : on retourne les normales
        bm = bmesh.new(); bm.from_mesh(k.data); bmesh.ops.reverse_faces(bm, faces=bm.faces); bm.to_mesh(k.data); bm.free()
        copies.append(k)
    bpy.context.view_layer.update()
    return copies


def lier_os(objs, armature, nom_os):
    """La piece suit RIGIDEMENT cet os (une ancienne peau de squelette est retiree, sinon double mouvement)."""
    for o in objs:
        for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
            o.modifiers.remove(m)
        mw = o.matrix_world.copy()
        o.parent = armature; o.parent_type = "BONE"; o.parent_bone = nom_os
        bpy.context.view_layer.update(); o.matrix_world = mw
    bpy.context.view_layer.update()


def os_le_plus_proche_tous(armature, point):
    """Comme os_le_plus_proche, mais tous les os (deformants ou non)."""
    if armature is None or not len(armature.data.bones):
        return None
    M = armature.matrix_world; best = None
    for b in armature.data.bones:
        a, c = M @ b.head_local, M @ b.tail_local
        ab = c - a; t = max(0.0, min(1.0, (point - a).dot(ab) / max(ab.length_squared, 1e-9)))
        d = (a + ab * t - point).length
        if best is None or d < best[0]:
            best = (d, b.name)
    return best[1]


def os_le_plus_proche(armature, point):
    if armature is None:
        return None
    M = armature.matrix_world; best = None
    for b in armature.data.bones:
        if not b.use_deform:
            continue
        a, c = M @ b.head_local, M @ b.tail_local
        ab = c - a; t = max(0.0, min(1.0, (point - a).dot(ab) / max(ab.length_squared, 1e-9)))
        d = (a + ab * t - point).length
        if best is None or d < best[0]:
            best = (d, b.name)
    return best[1] if best else None


# ------------------------------------------------------------------ materiaux

def srgb_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


from commun import hex_rgb


def materiau(nom, couleur, emission=0.0, alpha=1.0, matiere=None):
    """Materiau uni compatible avec le rendu de l'usine (couleur visible en mode TEXTURE et MATERIAL)."""
    r, g, b = (srgb_lin(c) for c in hex_rgb(couleur))
    m = bpy.data.materials.new(nom); m.use_nodes = True
    m.diffuse_color = (r, g, b, alpha)
    nt = m.node_tree
    img = bpy.data.images.new(f"uni_{nom}", 4, 4); img.pixels.foreach_set([*hex_rgb(couleur), alpha] * 16)
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img; nt.nodes.active = tex
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (r, g, b, 1)
        if alpha < 1:
            bsdf.inputs["Alpha"].default_value = alpha
        if emission > 0:
            bsdf.inputs["Emission Color"].default_value = (r, g, b, 1)
            bsdf.inputs["Emission Strength"].default_value = emission
    m["usine_emission"] = emission; m["usine_alpha"] = alpha
    if matiere:
        m["usine_matiere"] = matiere
    return m


def colorer(objs, couleur, emission=0.0, alpha=1.0, nom=None, matiere=None):
    m = materiau(nom or f"mat_{objs[0].name}", couleur, emission, alpha, matiere)
    for o in maillages(objs):
        o.data.materials.clear(); o.data.materials.append(m)
    return m


def squelette_principal(objs):
    """Le squelette qui DEFORME vraiment le corps (modificateur Armature ou parent de type os), pas le premier venu :
    un fichier Rigify contient 'metarig' (preparation, ne bouge rien) et 'rig' (le vrai)."""
    arms = [o for o in objs if o.type == "ARMATURE"]
    if len(arms) <= 1:
        return arms[0] if arms else None
    poids = {a.name: 0 for a in arms}
    for o in objs:
        if o.type != "MESH" or not len(o.data.vertices):
            continue
        cibles = {m.object.name for m in o.modifiers if m.type == "ARMATURE" and m.object}
        if o.parent and o.parent.type == "ARMATURE" and o.parent_type in ("ARMATURE", "BONE", "OBJECT"):
            cibles.add(o.parent.name)
        for c in cibles & set(poids):
            poids[c] += len(o.data.vertices)
    meilleur = max(arms, key=lambda a: (poids[a.name], len(a.data.bones)))
    return meilleur
