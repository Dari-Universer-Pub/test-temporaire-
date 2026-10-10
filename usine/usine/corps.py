"""Construction de corps de zero : des LIGNES de points avec une EPAISSEUR a chaque point -> une seule peau continue,
plus le squelette qui l'anime. Sert a tout ce qui est organique : humains, betes, monstres, queues, tentacules,
branches d'arbres, coraux, bois de cerf...

Methode (validee au test de faisabilite) : une famille de volumes (metaballes) par ligne -> les volumes d'une meme
ligne fusionnent comme de l'argile, mais deux lignes voisines (les deux jambes) ne se collent pas ; les familles sont
ensuite soudees en une surface unique (remaillage en volume) puis lissees.
"""
import math, random
import bpy
import numpy as np
from mathutils import Vector


def peau(lignes, finesse=0.02, k_rayon=1.5, lissage=3, nom="corps"):
    """lignes : [{"famille": str, "points": [Vector], "rayons": [float]}] -> objet maillage (une surface)."""
    morceaux = []
    familles = {}
    for l in lignes:
        familles.setdefault(l.get("famille", "f%d" % len(familles)), []).append(l)
    for fam, ls in familles.items():
        mb = bpy.data.metaballs.new("argile_" + fam); mb.resolution = mb.render_resolution = finesse; mb.threshold = 0.6
        for l in ls:
            pts, ray = l["points"], l["rayons"]
            for (pa, ra), (pb, rb) in zip(zip(pts, ray), zip(pts[1:], ray[1:])):
                ra *= k_rayon; rb *= k_rayon
                n = max(2, int((pb - pa).length / max(min(ra, rb) * 0.45, 1e-4)) + 1)
                for k in range(n + 1):
                    t = k / n; e = mb.elements.new(); e.type = "BALL"; e.stiffness = 2.0
                    e.co = pa.lerp(pb, t); e.radius = ra + (rb - ra) * t
            if len(pts) == 1:
                e = mb.elements.new(); e.type = "BALL"; e.co = pts[0]; e.radius = ray[0] * k_rayon; e.stiffness = 2.0
        o = bpy.data.objects.new(fam + ".argile", mb); bpy.context.scene.collection.objects.link(o)
        bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg)); bpy.data.objects.remove(o, do_unlink=True)
        if len(me.vertices):
            ob = bpy.data.objects.new("m_" + fam, me); bpy.context.scene.collection.objects.link(ob); morceaux.append(ob)
    if not morceaux:
        raise SystemExit("corps : aucune forme (rayons trop petits ?)")
    bpy.ops.object.select_all(action="DESELECT")
    for o in morceaux:
        o.select_set(True)
    bpy.context.view_layer.objects.active = morceaux[0]
    if len(morceaux) > 1:
        bpy.ops.object.join()
    corps = morceaux[0]; corps.name = nom
    rm = corps.modifiers.new("soudure", "REMESH"); rm.mode = "VOXEL"; rm.voxel_size = finesse * 0.65
    bpy.ops.object.modifier_apply(modifier="soudure")
    if lissage:
        ls_ = corps.modifiers.new("doux", "CORRECTIVE_SMOOTH"); ls_.iterations = int(lissage); ls_.use_only_smooth = False
        bpy.ops.object.modifier_apply(modifier="doux")
    for f in corps.data.polygons:
        f.use_smooth = True
    return corps


def squelette_lignes(lignes, nom="squelette"):
    """Un os par segment de ligne ; chaque ligne se rattache a l'os de la ligne parente le plus proche de son debut."""
    a = bpy.data.armatures.new(nom); arm = bpy.data.objects.new(nom, a); bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    for o in bpy.context.view_layer.objects:
        o.select_set(o == arm)
    bpy.ops.object.mode_set(mode="EDIT")
    segs = []   # (nom_os, tete, queue)
    for li, l in enumerate(lignes):
        pts = l["points"]; base = l.get("nom", l.get("famille", "l%d" % li))
        parent = None
        if l.get("parent"):  # parent impose : premier os de cette famille dont un bout est le plus proche
            cand = [s for s in segs if s[0].startswith(l["parent"] + "_")]
            if not cand:
                raise SystemExit(f"corps : parent '{l['parent']}' inconnu (il doit etre une ligne PRECEDENTE)")
            parent = min(cand, key=lambda s: _dist_seg(pts[0], s[1], s[2]))[0]
        elif segs:  # os existant le plus proche du debut de cette ligne (a egalite : la ligne la plus ancienne)
            parent = min(enumerate(segs), key=lambda e: (round(_dist_seg(pts[0], e[1][1], e[1][2]), 4), e[0]))[1][0]
        for k, (pa, pb) in enumerate(zip(pts, pts[1:])):
            if (pb - pa).length < 1e-5:
                continue
            nm = f"{base}_{k}"
            b = a.edit_bones.new(nm); b.head = pa; b.tail = pb
            if parent:
                b.parent = a.edit_bones[parent]; b.use_connect = k > 0
            segs.append((nm, pa.copy(), pb.copy())); parent = nm
    bpy.ops.object.mode_set(mode="OBJECT")
    return arm


def _dist_seg(p, a, b):
    ab = b - a; t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length


def lier_peau(corps, arm, douceur=0.035, exclure=()):
    """Poids de peau : chaque sommet suit les os les plus proches, RELATIVEMENT au plus proche (marche quelle que
    soit l'epaisseur des membres)."""
    M = arm.matrix_world; B = [b for b in arm.data.bones if b.use_deform and not any(x in b.name for x in exclure)]
    if not B:
        return
    seg = [(np.array(M @ b.head_local), np.array(M @ b.tail_local)) for b in B]
    Mw = corps.matrix_world
    V = np.array([Mw @ v.co for v in corps.data.vertices])
    D = np.zeros((len(V), len(B)))
    for j, (p, q) in enumerate(seg):
        pq = q - p; t = np.clip(((V - p) @ pq) / max(pq @ pq, 1e-12), 0, 1)
        D[:, j] = np.linalg.norm(V - (p + t[:, None] * pq), axis=1)
    W = np.exp(-((D - D.min(1, keepdims=True)) / douceur) ** 2); W /= W.sum(1, keepdims=True) + 1e-12
    for g in list(corps.vertex_groups):
        corps.vertex_groups.remove(g)
    for j, b in enumerate(B):
        idx = np.nonzero(W[:, j] > 0.02)[0]
        if len(idx):
            g = corps.vertex_groups.new(name=b.name)
            for i in idx:
                g.add([int(i)], float(W[i, j]), "REPLACE")
    mw = corps.matrix_world.copy(); corps.parent = arm; corps.matrix_world = mw
    md = corps.modifiers.new("squelette", "ARMATURE"); md.object = arm


def ramifier(base, haut, longueur, rayon, niveaux=3, branches=3, angle=35, raccourci=0.68, affinage=0.62,
             torsion=137.5, graine=1, courbure=0.15, nom="branche"):
    """Arbre, corail, bois de cerf, racines : -> lignes (le tronc puis les branches, recursivement)."""
    rnd = random.Random(graine); lignes = []
    def axe_perp(d):
        a = Vector((1, 0, 0)) if abs(d.x) < 0.9 else Vector((0, 1, 0))
        return d.cross(a).normalized()
    def pousse(p0, d, L, r, niv, nom_):
        n = 4; pts = [p0.copy()]; ray = [r]; dd = d.normalized()
        for k in range(1, n + 1):
            dd = (dd + Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.3, 0.6))) * courbure).normalized()
            pts.append(pts[-1] + dd * (L / n)); ray.append(r * (1 - (1 - affinage) * k / n))
        lignes.append({"famille": nom_, "nom": nom_, "points": pts, "rayons": ray})
        if niv >= niveaux:
            return
        tour = rnd.uniform(0, 360)
        for b in range(branches):
            t = 0.45 + 0.5 * (b + 1) / (branches + 1)
            k = max(1, min(n, int(round(t * n)))); p = pts[k]; r_ = ray[k] * affinage
            tour += torsion; perp = axe_perp(dd)
            q = perp.copy(); q.rotate(_rot(dd, math.radians(tour)))
            nd = (dd * math.cos(math.radians(angle)) + q * math.sin(math.radians(angle))).normalized()
            pousse(p, nd, L * raccourci * rnd.uniform(0.85, 1.1), r_, niv + 1, f"{nom_}{b}")
    pousse(Vector(base), Vector(haut), longueur, rayon, 0, nom)
    return lignes


def _rot(axe, ang):
    from mathutils import Quaternion
    return Quaternion(axe, ang)


def vetir(corps, tenue, materiau):
    """Tenue par zones du squelette : [{"os": ["hand", "foot"], "couleur": "#..", "sauf": [..]}, ...] ; chaque face prend
    la couleur de la DERNIERE regle dont un mot est contenu dans le nom de son os dominant (gants, bottes, ceinture...)."""
    noms = {g.index: g.name for g in corps.vertex_groups}
    dom = []
    for v in corps.data.vertices:
        best = max(v.groups, key=lambda g: g.weight, default=None)
        dom.append(noms.get(best.group, "") if best is not None else "")
    regles = []
    for k, r in enumerate(tenue):
        if not isinstance(r, dict) or "os" not in r or "couleur" not in r:
            raise SystemExit("tenue : chaque regle = {\"os\": [mots], \"couleur\": \"#rrggbb\"}")
        mots = r["os"] if isinstance(r["os"], list) else [r["os"]]
        corps.data.materials.append(materiau(r["couleur"], k))
        regles.append(([m.lower() for m in mots], [m.lower() for m in r.get("sauf", [])], len(corps.data.materials) - 1))
    for f in corps.data.polygons:
        vote = {}
        for vi in f.vertices:
            vote[dom[vi]] = vote.get(dom[vi], 0) + 1
        nom_os = max(vote, key=vote.get).lower()
        for mots, sauf, idx in regles:
            if any(m in nom_os for m in mots) and not any(m in nom_os for m in sauf):
                f.material_index = idx
