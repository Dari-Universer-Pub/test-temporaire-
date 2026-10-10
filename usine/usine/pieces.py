"""pieces : les formes de base du constructeur. Toute forme = un assemblage de ces pieces
(+ union lissee, soustraction, intersection, deformation). Chaque piece est creee dans SON repere :
X = droite, Y = avant, Z = haut, en metres (la recette donne des fractions de H, converties avant).
"""
import math
import numpy as np
import bpy, bmesh
from mathutils import Vector, Matrix

SEG = 32


def _objet(nom, bm):
    me = bpy.data.meshes.new(nom); bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(nom, me)
    bpy.context.scene.collection.objects.link(o)
    o["usine_piece"] = True
    return o


def _lisser(o, niveaux=1):
    if niveaux > 0:
        m = o.modifiers.new("lisse", "SUBSURF"); m.levels = niveaux; m.render_levels = niveaux
        appliquer(o)


def appliquer(o):
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):
        with bpy.context.temp_override(object=o, active_object=o):
            bpy.ops.object.modifier_apply(modifier=m.name)


def _interp(profil, n):
    """Profil [[t, valeur], ...] (t de 0 a 1) -> n valeurs lissees (Catmull-Rom monotone simple)."""
    profil = sorted(profil)
    ts = np.array([p[0] for p in profil], float); vs = np.array([p[1] for p in profil], float)
    t = np.linspace(ts[0], ts[-1], n)
    return t, np.interp(t, ts, vs)


def tour(nom, hauteur, rayon, profil=None, segments=SEG, lisse=1):
    """Forme tournee autour de Z (bouteille, tonneau, vase, casque, tronc...).
    profil : [[t, r], ...] t = 0 (bas) -> 1 (haut), r = fraction du rayon. Defaut : cylindre arrondi."""
    profil = profil or [[0, 0.0], [0.02, 0.85], [0.06, 1], [0.94, 1], [0.98, 0.85], [1, 0.0]]
    t, r = _interp(profil, 48)
    bm = bmesh.new(); anneaux = []
    for ti, ri in zip(t, r):
        z = ti * hauteur
        if ri * rayon < 1e-5:
            anneaux.append([bm.verts.new((0, 0, z))])
        else:
            anneaux.append([bm.verts.new((math.cos(a) * ri * rayon, math.sin(a) * ri * rayon, z))
                            for a in np.linspace(0, 2 * math.pi, segments, endpoint=False)])
    for a, b in zip(anneaux, anneaux[1:]):
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            for i in range(len(b)):
                bm.faces.new((a[0], b[(i + 1) % len(b)], b[i]))
        elif len(b) == 1:
            for i in range(len(a)):
                bm.faces.new((a[i], a[(i + 1) % len(a)], b[0]))
        else:
            for i in range(len(a)):
                bm.faces.new((a[i], a[(i + 1) % len(a)], b[(i + 1) % len(b)], b[i]))
    for anneau in (anneaux[0], anneaux[-1]):  # bouchons si le profil ne se ferme pas
        if len(anneau) > 2:
            try:
                bm.faces.new(anneau if anneau is anneaux[-1] else list(reversed(anneau)))
            except ValueError:
                pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = _objet(nom, bm); _lisser(o, lisse)
    return o


def tube(nom, points, rayons, segments=16, bouts_ronds=True, lisse=0):
    """Tube le long d'une courbe lisse (corps, membre, queue, tentacule, corne, cou, branche, langue...).
    points : [[x, y, z], ...] ; rayons : un rayon par point (ou un seul nombre)."""
    if not isinstance(rayons, (list, tuple)):
        rayons = [rayons] * len(points)
    cu = bpy.data.curves.new(nom, "CURVE"); cu.dimensions = "3D"
    sp = cu.splines.new("NURBS" if len(points) > 2 else "POLY")
    sp.points.add(len(points) - 1)
    for p, (x, y, z), rr in zip(sp.points, points, rayons):
        p.co = (x, y, z, 1); p.radius = max(rr, 1e-4)
    if len(points) > 2:
        sp.use_endpoint_u = True; sp.order_u = min(4, len(points))
    cu.bevel_depth = 1.0; cu.bevel_resolution = max(2, segments // 4); cu.resolution_u = 12
    cu.use_fill_caps = True
    oc = bpy.data.objects.new(nom + "_courbe", cu); bpy.context.scene.collection.objects.link(oc)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(oc.evaluated_get(dg))
    bpy.data.objects.remove(oc, do_unlink=True)
    bm = bmesh.new(); bm.from_mesh(me); bpy.data.meshes.remove(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    if bouts_ronds:  # bouts arrondis : une demi-sphere a chaque extremite
        o = _objet(nom, bm)
        for i in (0, -1):
            r = rayons[i]
            if r > 1e-4:
                s = bmesh.new(); bmesh.ops.create_uvsphere(s, u_segments=segments, v_segments=segments // 2, radius=r)
                bmesh.ops.translate(s, verts=s.verts, vec=Vector(points[i]))
                me2 = bpy.data.meshes.new("bout"); s.to_mesh(me2); s.free()
                b2 = bpy.data.objects.new("bout", me2); bpy.context.scene.collection.objects.link(b2)
                o = joindre([o, b2], nom)
        _lisser(o, lisse)
        return o
    o = _objet(nom, bm); _lisser(o, lisse)
    return o


def masse(nom, dimensions, bosses=0.0, graine=0, lisse=1):
    """Masse molle ovale (tete, ventre, slime, rocher, nuage). dimensions = [largeur, profondeur, hauteur].
    bosses : 0 = lisse, 0.1 = bosselee (bruit), 0.3 = tres irreguliere."""
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=16, radius=0.5)
    rng = np.random.default_rng(graine)
    ph = rng.uniform(0, 6.28, 6)
    for v in bm.verts:
        n = v.co.normalized()
        b = 1 + bosses * (math.sin(3 * n.x + ph[0]) * math.sin(3 * n.y + ph[1]) * math.sin(3 * n.z + ph[2])
                          + 0.5 * math.sin(7 * n.x + ph[3]) * math.sin(7 * n.z + ph[4]))
        v.co = Vector((n.x * dimensions[0], n.y * dimensions[1], n.z * dimensions[2])) * 0.5 * b
    o = _objet(nom, bm); _lisser(o, lisse)
    return o


def bloc(nom, dimensions, arrondi=0.1):
    """Bloc (caisse, machine, mur, coffre, batiment). arrondi = fraction de la plus petite dimension."""
    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * dimensions[0], v.co.y * dimensions[1], v.co.z * dimensions[2]))
    o = _objet(nom, bm)
    if arrondi > 0:
        m = o.modifiers.new("arrondi", "BEVEL"); m.width = arrondi * min(dimensions); m.segments = 3
        m.limit_method = "NONE"; appliquer(o)
    for p in o.data.polygons:
        p.use_smooth = False
    return o


def lame(nom, contour, epaisseur, lisse=1):
    """Plaque plate (aile, nageoire, feuille, voile, cape, lame d'epee, oreille...).
    contour : [[x, z], ...] dans le plan X-Z (vue de face), epaisseur en metres (selon Y)."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, 0, z)) for x, z in contour]
    bm.faces.new(vs)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    o = _objet(nom, bm)
    if epaisseur > 0:  # epaisseur 0 = une seule couche (tissu, cape, voile)
        m = o.modifiers.new("epaisseur", "SOLIDIFY"); m.thickness = epaisseur; m.offset = 0
        appliquer(o)
    if lisse:
        m = o.modifiers.new("lisse", "SUBSURF"); m.levels = lisse; appliquer(o)
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def joindre(objs, nom):
    objs = [o for o in objs if o.type == "MESH"]
    if len(objs) == 1:
        objs[0].name = nom
        return objs[0]
    with bpy.context.temp_override(active_object=objs[0], selected_editable_objects=objs, selected_objects=objs):
        bpy.ops.object.join()
    objs[0].name = nom
    return objs[0]


def union_lisse(objs, nom, finesse=0.01, lissage=2):
    """Fusionne des pieces en UNE surface organique continue (pas de jointure visible).
    finesse : taille des details gardes (metres)."""
    mats = [m for o in objs for m in o.data.materials if m]
    o = joindre(objs, nom)
    taille = max(o.dimensions) if max(o.dimensions) > 0 else 1.0
    # garde-fou : trop fin = des millions de faces (minutes de calcul, memoire) ; trop gros = forme perdue
    finesse = min(max(finesse, taille / 350), taille / 20)
    m = o.modifiers.new("fusion", "REMESH"); m.mode = "VOXEL"; m.voxel_size = finesse; m.adaptivity = 0
    appliquer(o)
    if lissage:
        m = o.modifiers.new("lissage", "CORRECTIVE_SMOOTH"); m.iterations = 3 * lissage; m.factor = 0.5
        appliquer(o)
    for p in o.data.polygons:
        p.use_smooth = True
    if mats and not o.data.materials:
        o.data.materials.append(mats[0])
    return o


def appliquer_un(o, m):
    """Applique UN modificateur (place en premier), en laissant les autres (squelette...) en place."""
    with bpy.context.temp_override(object=o, active_object=o):
        bpy.ops.object.modifier_move_to_index(modifier=m.name, index=0)
        bpy.ops.object.modifier_apply(modifier=m.name)


def booleen(o, outil, operation, garder_outil=False):
    """operation : DIFFERENCE (soustraire), INTERSECT (garder le commun), UNION."""
    m = o.modifiers.new("bool", "BOOLEAN"); m.operation = operation; m.object = outil; m.solver = "EXACT"
    if o.data.shape_keys:
        o.shape_key_clear()
    appliquer_un(o, m)
    if not garder_outil:
        bpy.data.objects.remove(outil, do_unlink=True)
    return o
