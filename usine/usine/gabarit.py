"""gabarit : DERNIER RECOURS quand `usine chercher` ne trouve rien (meme avec Sketchfab).
Construit un vrai modele 3D organique soigne (pas un cube, pas une sphere brute), avec des variantes numerotees.

    usine gabarit <type> <id>            -> planche de 6 variantes numerotees
    usine gabarit <type> <id> <numero>   -> cree modeles/<id>/source/<id>.glb (+ apercu.png, infos.json)
Types : meduse, algue, corail, cristal, rocher
Ensuite : recette normale avec "modele": "modeles/<id>/source/<id>.glb" et une animation "procedural"
(meduse -> pulsation ; algue, corail -> balancement ; cristal, rocher -> fixe ou flottement).
Couleurs : "couleurs" dans la recette, avec les noms de materiaux listes dans infos.json.
"""
import os, sys, json, math, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *
import bpy, bmesh
from mathutils import Vector, Matrix, noise

ARGS = sys.argv[sys.argv.index("--") + 1:]
TYPE, IDENT = ARGS[0], ARGS[1]
CHOIX = int(ARGS[2]) if len(ARGS) > 2 else None
DOSSIER = os.path.join("modeles", IDENT)
os.makedirs(os.path.join(DOSSIER, "source"), exist_ok=True)


def materiau(nom, hexa):
    m = bpy.data.materials.get(nom) or bpy.data.materials.new(nom)
    rgb = list(hex_rgb(hexa))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF") or m.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = (*lin, 1); m.diffuse_color = (*lin, 1)
    return m


def objet(nom, verts, faces, mat, lisse=True):
    me = bpy.data.meshes.new(nom); me.from_pydata([tuple(v) for v in verts], [], faces); me.update()
    if lisse:
        for p in me.polygons: p.use_smooth = True
    o = bpy.data.objects.new(nom, me); bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(mat)
    return o


def revolution(profil, n, rayon_mod=None, z_mod=None):
    """profil : liste (r, z) du haut vers le bas ; n : segments autour de l'axe Z."""
    verts, faces = [], []
    for j, (r, z) in enumerate(profil):
        v = j / max(1, len(profil) - 1)
        for i in range(n):
            t = 2 * math.pi * i / n
            rr = r * (rayon_mod(t, v) if rayon_mod else 1); zz = z + (z_mod(t, v) if z_mod else 0)
            verts.append((rr * math.cos(t), rr * math.sin(t), zz))
    for j in range(len(profil) - 1):
        for i in range(n):
            a, b = j * n + i, j * n + (i + 1) % n
            faces.append((a, b, b + n, a + n))
    return verts, faces


def tube(points, rayons, cotes=6):
    pts = [Vector(p) for p in points]; verts, faces = [], []
    for k, (p, r) in enumerate(zip(pts, rayons)):
        d = (pts[min(k + 1, len(pts) - 1)] - pts[max(k - 1, 0)]).normalized()
        a = d.orthogonal().normalized(); b = d.cross(a)
        for i in range(cotes):
            t = 2 * math.pi * i / cotes
            verts.append(tuple(p + (a * math.cos(t) + b * math.sin(t)) * r))
    for k in range(len(pts) - 1):
        for i in range(cotes):
            a_, b_ = k * cotes + i, k * cotes + (i + 1) % cotes
            faces.append((a_, b_, b_ + cotes, a_ + cotes))
    verts.append(tuple(pts[-1] + (pts[-1] - pts[-2]).normalized() * rayons[-1])); fin = len(verts) - 1
    for i in range(cotes):
        faces.append(((len(pts) - 1) * cotes + i, (len(pts) - 1) * cotes + (i + 1) % cotes, fin))
    return verts, faces


def solidifier(o, ep):
    m = o.modifiers.new("ep", "SOLIDIFY"); m.thickness = ep; m.offset = 1
    bpy.context.view_layer.objects.active = o; o.select_set(True)
    bpy.ops.object.modifier_apply(modifier=m.name); o.select_set(False)


# ------------------------------------------------------------- gabarits
def meduse(p, rnd):
    R, H = 1.0, p["hauteur"]
    n = p["festons"]
    prof = [(R * math.sin(min(1.0, v) * math.pi / 2 * 1.08) ** 0.85, H * math.cos(min(1.0, v) * math.pi / 2 * 1.08))
            for v in [i / 18 for i in range(19)]]
    vs, fs = revolution(prof, 48, rayon_mod=lambda t, v: 1 + 0.07 * math.sin(n * t) * v ** 3,
                        z_mod=lambda t, v: -0.10 * H * abs(math.sin(n * t / 2)) * v ** 5)
    cloche = objet("cloche", vs, fs, materiau("cloche", p["c_cloche"])); solidifier(cloche, 0.05)
    # sous-ombrelle : un disque sombre en retrait sous la cloche (donne la profondeur)
    vs, fs = revolution([(0.05, 0.12 * H), (0.88 * R, 0.02 * H)], 32)
    objet("dessous", vs, fs, materiau("dessous", p["c_dessous"]))
    L = p["longueur"] * R
    for k in range(p["bras"]):  # bras buccaux : rubans ondules et frises
        a0 = 2 * math.pi * k / max(1, p["bras"]) + rnd.uniform(-0.2, 0.2)
        pts = []; rs = []
        for i in range(22):
            u = i / 21
            pts.append((0.12 * math.cos(a0) + 0.18 * u * math.cos(a0) + 0.08 * math.sin(6 * u + k),
                        0.12 * math.sin(a0) + 0.18 * u * math.sin(a0) + 0.08 * math.cos(5 * u + k), 0.1 * H - u * L * 0.75))
            rs.append(0.10 * (1 - 0.6 * u) * (1 + 0.35 * math.sin(14 * u + k)))
        vs, fs = tube(pts, rs, 7); objet(f"bras_{k}", vs, fs, materiau("bras", p["c_bras"]))
    for k in range(p["tentacules"]):  # tentacules fins depuis le bord
        a0 = 2 * math.pi * (k + 0.5) / p["tentacules"]
        pts = []; rs = []
        for i in range(26):
            u = i / 25
            ond = 0.10 * math.sin(4 * u * math.pi + k * 1.7) * u
            pts.append(((0.93 * R - 0.15 * u) * math.cos(a0) + ond * math.sin(a0), (0.93 * R - 0.15 * u) * math.sin(a0) - ond * math.cos(a0),
                        -0.02 * H - u * L * rnd.uniform(0.85, 1.1)))
            rs.append(0.035 * (1 - 0.8 * u))
        vs, fs = tube(pts, rs, 5); objet(f"tentacule_{k}", vs, fs, materiau("tentacules", p["c_tentacules"]))


def algue(p, rnd):
    for b in range(p["tiges"]):
        x0, y0 = rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3); Ht = p["hauteur"] * rnd.uniform(0.75, 1.0)
        pts = [(x0 + 0.15 * math.sin(3 * u + b) * u, y0 + 0.05 * math.cos(2 * u + b), u * Ht) for u in [i / 20 for i in range(21)]]
        vs, fs = tube(pts, [0.04 * (1 - 0.5 * i / 20) for i in range(21)], 5); objet(f"tige_{b}", vs, fs, materiau("tige", p["c_tige"]))
        for f in range(p["feuilles"]):
            u = 0.15 + 0.8 * f / p["feuilles"]; base = Vector(pts[int(u * 20)]); cote = 1 if f % 2 else -1
            longu = p["largeur"] * (1.2 - 0.5 * u); verts = []; faces = []
            for i in range(9):
                s = i / 8; w = math.sin(s * math.pi) * longu * 0.35
                c = base + Vector((cote * s * longu, 0, s * longu * 0.6 + 0.05 * math.sin(s * 9)))
                verts += [tuple(c + Vector((0, -w, 0))), tuple(c + Vector((0, w, 0)))]
                if i:
                    faces.append((2 * i - 2, 2 * i - 1, 2 * i + 1, 2 * i))
            o = objet(f"feuille_{b}_{f}", verts, faces, materiau("feuilles", p["c_feuilles"])); solidifier(o, 0.015)


def corail(p, rnd):
    mat = materiau("corail", p["c_corail"]); mat_b = materiau("bouts", p["c_bouts"])
    def branche(origine, direction, longueur, rayon, niveau, idx):
        pts, rs = [], []
        d = direction.normalized()
        for i in range(10):
            u = i / 9
            d = (d + Vector((rnd.uniform(-0.12, 0.12), rnd.uniform(-0.12, 0.12), 0.04))).normalized()
            pts.append(tuple(origine + d * longueur * u)); rs.append(rayon * (1 - 0.45 * u))
        vs, fs = tube(pts, rs, 6); objet(f"branche_{idx}_{niveau}", vs, fs, mat)
        fin = Vector(pts[-1])
        if niveau >= p["niveaux"]:
            vs, fs = revolution([(0.0001, rayon * 0.9), (rayon * 0.8, 0), (0.0001, -rayon * 0.5)], 8)
            o = objet(f"bout_{idx}_{niveau}", [tuple(Vector(v) + fin) for v in vs], fs, mat_b); return
        for k in range(rnd.choice([2, 2, 3])):
            ang = rnd.uniform(0, 2 * math.pi)
            nd = (d * 0.6 + Vector((math.cos(ang), math.sin(ang), 0.35)) * 1.1).normalized()
            branche(fin, nd, longueur * 0.8, rayon * 0.66, niveau + 1, f"{idx}{k}")
    for t in range(p["troncs"]):
        branche(Vector((rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), 0)),
                Vector((rnd.uniform(-0.4, 0.4), rnd.uniform(-0.4, 0.4), 1)), p["hauteur"], 0.11, 1, str(t))


def cristal(p, rnd):
    for k in range(p["nombre"]):
        h = p["hauteur"] * (1 if k == 0 else rnd.uniform(0.35, 0.8)); r = 0.16 * h ** 0.5 * p["epaisseur"]
        prof = [(0.0001, h * 1.18), (r, h), (r, 0), (0.0001, -0.02)]
        vs, fs = revolution(prof, 6)
        ax = Vector((rnd.uniform(-0.6, 0.6), rnd.uniform(-0.6, 0.6), 1)).normalized() if k else Vector((0, 0, 1))
        rot = Vector((0, 0, 1)).rotation_difference(ax).to_matrix()
        dec = Vector((rnd.uniform(-0.25, 0.25), rnd.uniform(-0.25, 0.25), 0)) if k else Vector()
        o = objet(f"cristal_{k}", [tuple(rot @ Vector(v) + dec) for v in vs], fs, materiau("cristal", p["c_cristal"]), lisse=False)
    vs, fs = revolution([(0.0001, 0.05), (0.45, 0.02), (0.5, -0.05)], 10,
                        rayon_mod=lambda t, v: 1 + 0.15 * math.sin(3 * t + 1))
    objet("socle", vs, fs, materiau("socle", p["c_socle"]), lisse=False)


def rocher(p, rnd):
    bm = bmesh.new(); bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
    graine = Vector((rnd.random() * 100, rnd.random() * 100, 0))
    for v in bm.verts:
        d = noise.noise(v.co * p["bosses"] + graine) * 0.28 + noise.noise(v.co * 4.0 + graine) * 0.07
        v.co *= 1 + d
        v.co.x *= p["largeur"]; v.co.z *= p["hauteur"]
        if v.co.z < -0.3 * p["hauteur"]: v.co.z = -0.3 * p["hauteur"] + (v.co.z + 0.3 * p["hauteur"]) * 0.15
    me = bpy.data.meshes.new("rocher"); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new("rocher", me); bpy.context.scene.collection.objects.link(o)
    o.data.materials.append(materiau("roche", p["c_roche"])); o.data.materials.append(materiau("mousse", p["c_mousse"]))
    for f in me.polygons:
        f.material_index = 1 if (p["mousse"] and f.normal.z > 0.55) else 0


GABARITS = {
    "meduse": (meduse, [dict(hauteur=h, festons=f, bras=b, tentacules=t, longueur=l,
                             c_cloche="#f2a7d8", c_dessous="#9a3f86", c_bras="#d9609f", c_tentacules="#f7c9e8")
                        for h, f, b, t, l in [(0.75, 8, 4, 16, 2.4), (0.55, 12, 4, 24, 1.8), (0.95, 8, 0, 12, 2.8),
                                              (0.65, 16, 4, 32, 2.2), (0.8, 10, 6, 10, 3.2), (0.5, 8, 0, 20, 1.5)]]),
    "algue": (algue, [dict(tiges=t, feuilles=f, hauteur=h, largeur=w, c_tige="#5b6b2a", c_feuilles="#7fa83a")
                      for t, f, h, w in [(1, 8, 2.2, 0.5), (3, 6, 2.0, 0.4), (2, 10, 2.8, 0.45), (1, 12, 3.0, 0.6),
                                         (4, 5, 1.6, 0.35), (2, 7, 2.4, 0.7)]]),
    "corail": (corail, [dict(troncs=t, niveaux=n, hauteur=h, c_corail="#e8735a", c_bouts="#ffd1b8")
                        for t, n, h in [(1, 3, 0.45), (2, 3, 0.4), (3, 2, 0.55), (1, 4, 0.35), (2, 4, 0.3), (4, 3, 0.3)]]),
    "cristal": (cristal, [dict(nombre=n, hauteur=h, epaisseur=e, c_cristal="#7fe3f0", c_socle="#5c5470")
                          for n, h, e in [(1, 1.0, 1.0), (3, 1.0, 1.0), (5, 0.9, 0.9), (7, 0.8, 0.8), (4, 1.2, 1.3), (9, 0.7, 0.7)]]),
    "rocher": (rocher, [dict(bosses=b, largeur=w, hauteur=h, mousse=m, c_roche="#857a6e", c_mousse="#5f8a3a")
                        for b, w, h, m in [(1.2, 1.3, 0.8, False), (1.8, 1.0, 1.0, True), (1.0, 1.6, 0.6, True),
                                           (2.2, 1.1, 0.9, False), (1.5, 1.4, 1.1, True), (1.3, 0.9, 1.3, False)]]),
}
if TYPE not in GABARITS:
    raise SystemExit(f"type inconnu : {TYPE}. Types : {', '.join(GABARITS)}")
fabrique, VARIANTES = GABARITS[TYPE]


def construire(i):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    fabrique(VARIANTES[i], random.Random(1000 + i))
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def rendre(meshes, vues, taille=240):
    scene = bpy.context.scene
    synchroniser_couleurs()
    pts = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in meshes])
    lo, hi = pts.min(0), pts.max(0); c = Vector((lo + hi) / 2); t = float((hi - lo).max())
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading; sh.light = "STUDIO"; sh.color_type = "TEXTURE"; sh.show_shadows = True; sh.show_cavity = True
    scene.render.film_transparent = True; scene.render.resolution_x = scene.render.resolution_y = taille
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam)
    cam.data.type = "ORTHO"; cam.data.ortho_scale = t * 1.15; cam.data.clip_end = t * 30; scene.camera = cam
    ims = []
    for v in vues:
        v = Vector(v).normalized(); cam.location = c + v * t * 6; cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
        p = os.path.join(DOSSIER, f"_v_{os.getpid()}.png"); scene.render.filepath = p; bpy.ops.render.render(write_still=True)
        ims.append(ajuster(lire_image(p), taille, taille, fond=(0.75, 0.82, 0.88))); os.remove(p)
    return ims


if CHOIX is None:
    cases = []
    for i in range(len(VARIANTES)):
        ims = rendre(construire(i), [(-1, 0, 0.15), (-1, -1, 0.6)])
        cases.append(numeroter(np.concatenate([ims[0], np.ones((240, 6, 4)), ims[1]], 1), i + 1, k=3))
    p = os.path.join(DOSSIER, f"gabarit_{TYPE}_variantes.png")
    ecrire_image(p, grille(cases, colonnes=3, case=(cases[0].shape[1], cases[0].shape[0])))
    print(f"REGARDE : {p}  (chaque case : profil + 3/4). Choisis la forme la plus belle et la plus lisible.")
    print(f"Puis : usine gabarit {TYPE} {IDENT} <numero>")
else:
    meshes = construire(CHOIX - 1)
    sortie = os.path.join(DOSSIER, "source", f"{IDENT}.glb")
    bpy.ops.export_scene.gltf(filepath=sortie, export_format="GLB")
    ims = rendre(meshes, [(0, -1, 0), (-1, 0, 0), (0, -0.0001, 1), (-1, -1, 0.8)], 320)
    ecrire_image(os.path.join(DOSSIER, "apercu.png"), grille(ims, colonnes=4, case=(320, 320)))
    infos = {"id": IDENT, "fichier": sortie, "gabarit": TYPE, "variante": CHOIX, "parametres": VARIANTES[CHOIX - 1],
             "materiaux": sorted({m.name for o in meshes for m in o.data.materials}), "animations": [],
             "objets": [o.name for o in meshes]}
    json.dump(infos, open(os.path.join(DOSSIER, "infos.json"), "w"), indent=1, ensure_ascii=False)
    lic = os.path.join(DOSSIER, "licence.txt")
    open(lic, "w").write(f"Modele {IDENT} genere par l'usine a assets (gabarit procedural '{TYPE}', variante {CHOIX}).\n"
                         "Aucun contenu tiers. Le generateur place ce modele dans le domaine public : CC0 1.0.\n")
    json.dump({"id": IDENT, "type": "modele3d", "url": "https://github.com/Dari-Universer-Pub/KIT-OUTIL",
               "licence": "CC0", "auteur": f"usine a assets (gabarit {TYPE}, variante {CHOIX})", "fichier": sortie,
               "sha256": sha256(sortie), "page_licence": lic, "genere": True},
              open(os.path.join(DOSSIER, "provenance.json"), "w"), indent=1, ensure_ascii=False)
    print(f"MODELE GENERE : {sortie}\n  REGARDE : {DOSSIER}/apercu.png\n  materiaux (pour \"couleurs\") : {infos['materiaux']}")
