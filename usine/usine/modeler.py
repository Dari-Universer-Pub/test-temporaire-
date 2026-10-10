"""modeler : modifier un modele ou en construire un de zero, par CONTRAINTES (jamais de coordonnees devinees).

    usine analyser modeles/<id>/source/<fichier>   -> carte du modele : repere (haut/avant/droite) + zones numerotees
    usine modeler  recettes/<id>.json              -> applique "modelage" ; planche + MESURES ; ecrit "modele" dans la recette

Recette : {"id": "...", "modelage": {"base": "<fichier ou rien>", "operations": [ ... ]}, ...le reste comme d'habitude}
Toutes les longueurs = fractions de H (hauteur du sujet ; 1 m si on part de zero). Angles en degres.
Mode d'emploi complet : LISEZMOI.md, section "Modeler".
"""
import os, sys, json, math, shutil, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *
import bpy
from mathutils import Vector, Matrix
import geometrie as G
import pieces as P
import corps as C

ARGS = sys.argv[sys.argv.index("--") + 1:]
MODE = ARGS[0]
VUES_PLANCHE = [("face", "avant", 0.0), ("droite", "droite", 0.0), ("dos", "arriere", 0.0), ("3/4", "avant-droite", 0.35)]


# ------------------------------------------------------------------ rendu
def preparer_rendu(taille):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sh = sc.display.shading; sh.light = "STUDIO"; sh.color_type = "TEXTURE"; sh.show_shadows = True; sh.show_cavity = True
    sc.render.film_transparent = True; sc.render.resolution_x = sc.render.resolution_y = taille
    cam = bpy.data.objects.get("_cam") or bpy.data.objects.new("_cam", bpy.data.cameras.new("_cam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"; sc.camera = cam
    return cam


def rendre_vues(objs, rep, taille=300, vues=VUES_PLANCHE, reperes=None, dossier=".", cadre=None, numeros=True):
    """Rend les vues dans le repere du SUJET. reperes = [(numero, point monde)] dessines sur chaque vue."""
    from bpy_extras.object_utils import world_to_camera_view
    synchroniser_couleurs()
    cam = preparer_rendu(taille)
    pts = G.points_monde(objs, 20000) if cadre is None else G.points_monde(cadre, 20000)
    if len(pts) == 0:
        pts = G.points_monde(objs, 20000)
    if len(pts) == 0:
        raise SystemExit("ERREUR : rien de visible a rendre (tout est cache ou vide)")
    c = Vector((pts.min(0) + pts.max(0)) / 2); t = float(np.ptp(pts, 0).max())
    if cadre is not None:
        t *= 1.8
    cam.data.ortho_scale = t * 1.2; cam.data.clip_end = t * 40
    ims = []
    for nom, d, el in vues:
        v = (G.direction(d, rep) + rep["u"] * el).normalized()
        cam.location = c + v * t * 8
        cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        p = os.path.abspath(os.path.join(dossier, f"_vue_{os.getpid()}.png")); bpy.context.scene.render.filepath = p
        bpy.ops.render.render(write_still=True)
        im = ajuster(lire_image(p), taille, taille, fond=(0.75, 0.82, 0.88)); os.remove(p)
        places = []
        for n, pt in (reperes or []):
            q = world_to_camera_view(bpy.context.scene, cam, Vector(pt))
            x, y = int(q.x * taille), int((1 - q.y) * taille)
            if not (0 <= x < taille and 0 <= y < taille):
                continue
            vis = True
            if BVH is not None:  # point cache derriere la surface vue : marque en terne
                h = BVH.ray_cast(Vector(pt) + v * 0.004 * t, v, t * 10)
                vis = h[0] is None
            if not vis:
                continue
            im[max(0, y - 2):y + 3, max(0, x - 2):x + 3, :3] = (0.95, 0.1, 0.1)
            w, hh = (6 * len(str(n)) + 1) * 2, 18
            # etiquette sans chevauchement : on essaie des positions de plus en plus loin du point
            for r_ in range(0, 120, 6):
                ok = None
                for dx, dy in ((6, -20), (6, 4), (-w - 6, -20), (-w - 6, 4), (6 + r_, -20), (-w - 6 - r_, -20),
                               (6, -20 - r_), (6, 4 + r_), (-w - 6, -20 - r_), (-w - 6, 4 + r_)):
                    x0, y0 = x + dx, y + dy
                    if x0 < 0 or y0 < 0 or x0 + w > taille or y0 + hh > taille:
                        continue
                    if all(x0 + w < a or x0 > a + aw or y0 + hh < b_ or y0 > b_ + bh for a, b_, aw, bh in places):
                        ok = (x0, y0); break
                if ok:
                    break
            if not ok:
                continue
            x0, y0 = ok
            places.append((x0, y0, w, hh))
            s_ = numeroter(np.ones((hh, w + 2, 4)), n, k=2, couleur=(1, 1, 1), fond=(0.65, 0.0, 0.0))
            im[y0:y0 + hh, x0:x0 + w] = s_[:hh, :w]
            # trait fin du point vers l'etiquette
            cx_, cy_ = x0 + (w // 2), y0 + (hh // 2)
            for k in range(1, 12):
                xx, yy = int(x + (cx_ - x) * k / 12), int(y + (cy_ - y) * k / 12)
                if 0 <= xx < taille and 0 <= yy < taille:
                    im[yy, xx, :3] = (0.65, 0.0, 0.0)
        ims.append(numeroter(im, vues.index((nom, d, el)) + 1, k=2, fond=(0.2, 0.2, 0.25)) if numeros else im)
    return ims


BVH = None


# ------------------------------------------------------------------ analyser
def verifier_echelle_animee(objs, arm):
    """Certains fichiers (export cm -> m) ont un repos 5 a 100 fois plus grand que le modele anime : les os sont
    re-echelonnes par l'animation. Les pieces, mesurees au repos, seraient alors a la mauvaise echelle."""
    ad = arm.animation_data
    act = (ad.action if ad and ad.action else None) or next((a for a in bpy.data.actions if os_de_action(a) & {b.name for b in arm.data.bones}), None)
    if act is None:
        return
    ms = G.maillages(objs)
    arm.data.pose_position = "REST"; bpy.context.view_layer.update()
    t_repos = float(np.ptp(G.points_monde(ms, 5000), 0).max())
    anc = ad.action if ad else None
    arm.animation_data_create(); arm.animation_data.action = act; choisir_slot(arm, act)
    arm.data.pose_position = "POSE"; bpy.context.scene.frame_set(int(act.frame_range[0])); bpy.context.view_layer.update()
    t_anime = float(np.ptp(G.points_monde(ms, 5000), 0).max())
    arm.animation_data.action = anc; arm.data.pose_position = "REST"; bpy.context.view_layer.update()
    k = max(t_repos, 1e-9) / max(t_anime, 1e-9)
    if k > 2 or k < 0.5:
        msg = (f"ATTENTION : ce modele change d'echelle quand il est anime (x{1 / k:.2f} : defaut d'export de l'auteur). "
               "Les pieces de 'modelage' seraient a la mauvaise taille sur le sprite anime -> prends un autre modele "
               "(ou garde-le sans modelage).")
        print("  " + msg)
        ALERTES_IMPORT.append(msg)


ALERTES_IMPORT = []


def charger_base(chemin, retourner=False, cacher=()):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = G.importer(chemin)
    for nom in cacher:
        for o in objs:
            if nom.lower() in o.name.lower():
                o.hide_render = True
    arm = G.squelette_principal(objs)
    if arm:
        verifier_echelle_animee(objs, arm)
        arm.data.pose_position = "REST"; bpy.context.view_layer.update()
    rep = G.repere(objs, arm)
    if retourner:
        rep = G.retourner(rep)
    return objs, arm, rep


if MODE == "analyser":
    chemin = ARGS[1]
    retourner = "retourner" in ARGS[2:]
    objs, arm, rep = charger_base(chemin, retourner)
    BVH = G.bvh_monde(objs)
    Z = G.zones(objs, arm, rep)
    nommees = [n for n in Z if not n.startswith("os:")]
    # sur l'image : les zones nommees ; les os un par un seulement s'il n'y a pas de zones de corps nommees
    noms = nommees + ([n for n in Z if n.startswith("os:")] if len(nommees) <= 7 else [])
    autres_os = [n for n in Z if n.startswith("os:") and n not in noms]
    marques = []
    for i, n in enumerate(noms):  # on montre le point de SURFACE ou une piece serait posee
        S, _ = G.point_surface(BVH, Z[n]["point"], G.direction_zone(Z[n], Z[n]["cote"], rep), rep["H"]) if n != "centre" else (None, None)
        Z[n]["surface"] = S
        if S is not None:
            marques.append((i + 1, S))
    ims = rendre_vues(objs, rep, 420, reperes=marques)
    dm = dossier_modele(chemin) or os.path.dirname(os.path.abspath(chemin))
    p = os.path.join(dm, "analyse.png")
    ecrire_image(p, grille(ims, colonnes=2, case=(420, 420)))
    info = {"fichier": chemin, "H_m": round(rep["H"], 4), "symetrique": rep["symetrique"],
            "haut_trouve_par": rep["source_haut"], "avant_trouve_par": rep["source_avant"], "squelette": bool(arm),
            "zones": {n: {"numero": i + 1, "os": Z[n]["os"], "cote_par_defaut": Z[n]["cote"],
                          "position": G.vers_repere(Z[n]["point"], rep)} for i, n in enumerate(noms)}}
    json.dump(info, open(os.path.join(dm, "analyse.json"), "w"), indent=1, ensure_ascii=False)
    print(f"\nANALYSE : {p}")
    print(f"  Les 4 vues sont, dans l'ordre : 1 = FACE (le sujet te regarde), 2 = son cote DROIT, 3 = son DOS, 4 = 3/4 avant-droit.")
    print(f"  VERIFIE sur la vue 1 que le sujet te fait bien FACE. Sinon : mets \"retourner\": true dans \"modelage\".")
    print(f"  Hauteur H = {rep['H']:.3f} m (toutes les longueurs de la recette sont des fractions de H).")
    print(f"  Symetrique : {'oui' if rep['symetrique'] else 'non'} ; haut trouve par : {rep['source_haut']} ; avant trouve par : {rep['source_avant']}")
    print("  Zones (numero sur l'image -> nom a ecrire dans la recette) :")
    for i, n in enumerate(noms):
        print(f"    {i + 1:2d} = {n}" + (f"   (os {Z[n]['os']})" if Z[n]["os"] and not n.startswith("os:") else ""))
    if autres_os:
        print("  Aussi utilisables (chaque os du squelette, pas dessines) : " + ", ".join(autres_os))
    sys.exit(0)


# ------------------------------------------------------------------ modeler
RECETTE = ARGS[1]
R = lire_recette(RECETTE)
ID = R["id"]
M = R.get("modelage") or {}
GABARITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gabarits")
if M.get("gabarit"):
    _g = os.path.join(GABARITS, str(M["gabarit"]) + ".json")
    if not os.path.exists(_g):
        raise SystemExit(f"ERREUR : gabarit inconnu '{M['gabarit']}'. Gabarits : "
                         f"{sorted(f[:-5] for f in os.listdir(GABARITS) if f.endswith('.json'))}")
    _gj = json.load(open(_g, encoding="utf-8"))
    _reg = dict(_gj.get("reglages", {})); _inc = [k for k in (M.get("reglages") or {}) if k not in _reg]
    if _inc:
        raise SystemExit(f"ERREUR : reglage(s) inconnu(s) pour le gabarit '{M['gabarit']}' : {_inc}. Reglages : {sorted(_reg)}")
    _reg.update(M.get("reglages") or {})
    _txt = json.dumps(_gj.get("operations", []))
    for k_, v_ in _reg.items():  # "$cle" -> valeur (nombre, liste, texte...)
        _txt = _txt.replace(json.dumps("$" + k_), json.dumps(v_))
    M = dict(M, operations=json.loads(_txt) + list(M.get("operations", [])))
    print(f"  gabarit '{M['gabarit']}' : {len(_gj.get('operations', []))} operation(s), reglages {_reg}")
# affinage numerote : la valeur {"affiner": [min, max]} prend la valeur de l'essai USINE_AFFINAGE (1..N)
AFF = int(os.environ.get("USINE_AFFINAGE", "0")); AFF_N = int(os.environ.get("USINE_AFFINAGE_N", "6"))
AFF_VAL = {}
def _affiner(x):
    if isinstance(x, dict):
        if "affiner" in x and len(x) == 1:
            a_, b_ = x["affiner"]
            t_ = (AFF - 1) / max(AFF_N - 1, 1) if AFF else 0.5
            v_ = [round(p + (q - p) * t_, 4) for p, q in zip(a_, b_)] if isinstance(a_, list) else round(a_ + (b_ - a_) * t_, 4)
            AFF_VAL["v"] = v_; AFF_VAL.setdefault("n", 0); AFF_VAL["n"] += 1
            return v_
        return {k: _affiner(y) for k, y in x.items()}
    if isinstance(x, list):
        return [_affiner(y) for y in x]
    return x
M = _affiner(M)
if AFF_VAL.get("n", 0) > 1:
    raise SystemExit("une seule valeur {\"affiner\": [...]} a la fois")
if AFF_VAL and not AFF:
    print(f"  (affinage en attente : valeur du milieu {AFF_VAL['v']} utilisee ; lance usine affiner pour choisir)")
DOSSIER = os.path.join("modeles", ID)
os.makedirs(os.path.join(DOSSIER, "source"), exist_ok=True)
SOURCES = []  # dossiers de provenance des fichiers utilises

if M.get("base"):
    objs, ARM, REP = charger_base(M["base"], M.get("retourner"), M.get("cacher", []))
    d = dossier_modele(M["base"])
    if d:
        SOURCES.append(d)
        for v in glob.glob(os.path.join(d, "vignette_officielle.*")):  # la reference visuelle reste celle de la base
            if os.path.abspath(os.path.dirname(v)) != os.path.abspath(DOSSIER):
                shutil.copyfile(v, os.path.join(DOSSIER, os.path.basename(v)))
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs, ARM = [], None
    REP = {"u": Vector((0, 0, 1)), "f": Vector((0, -1, 0)), "r": Vector((-1, 0, 0)), "centre": Vector((0, 0, 0.5)),
           "bas": Vector((0, 0, 0)), "H": 1.0, "largeur": 1.0, "profondeur": 1.0, "symetrique": True,
           "ecart_symetrie": 0.0, "source_haut": "construction", "source_avant": "construction"}
H = REP["H"]
PIECES = {}          # nom -> liste d'objets
CADRES = {}          # nom -> Matrix 3x3 : colonnes = (droite, avant, haut) de la piece, en monde
SUJET = list(objs)   # ce qui forme le corps (sert aux contacts "sur": "sujet")
ALERTES, RAPPORT = list(ALERTES_IMPORT), []
ANIMS_CREES = []
LIGNES = {}          # lignes centrales des tubes fusionnes (gardees pour le squelette)
REPARTIS = {}        # piece repartie -> noms de ses copies (un seul gros plan pour toutes)
TUBES = {}           # nom de tube -> points de sa ligne centrale (monde) : sert au squelette automatique


def est_sujet(nom):
    return isinstance(nom, str) and (nom in ("sujet", "base") or (nom == "corps" and "corps" not in PIECES))


def objets_de(nom):
    if nom in PIECES and nom not in ("sujet", "base"):  # une piece nommee "corps" reste cette piece
        return PIECES[nom]
    if nom in ("sujet", "corps", "base"):
        if not SUJET:  # construction de zero : le "sujet" = tout ce qui est deja construit
            return [o for n_ in PIECES for o in PIECES[n_] if o.type == "MESH" and not o.hide_render and o.name in bpy.data.objects]
        return [o for o in SUJET if o.type == "MESH" and not o.hide_render]
    if nom in PIECES:
        return PIECES[nom]
    t = [o for o in bpy.data.objects if o.type == "MESH" and nom.lower() in o.name.lower()]
    if not t:
        raise SystemExit(f"'{nom}' introuvable. Pieces : {sorted(PIECES)} ; objets : {sorted(o.name for o in bpy.data.objects if o.type == 'MESH')}")
    return t


def cibles_op(nom):
    """objets vises par une operation ; message clair si le sujet est encore vide (construction de zero)."""
    t = PIECES[nom] if nom in PIECES else objets_de(nom)
    if not [o for o in t if o.type == "MESH"]:
        raise SystemExit(f"'{nom}' : rien a modifier (pas de \"base\" et aucune piece construite pour l'instant)" if est_sujet(nom)
                         else f"'{nom}' : piece vide")
    return t


def transformer(nom, T):
    """Applique T (monde) a la piece, a son cadre et a sa ligne centrale (tubes)."""
    if nom in TUBES:
        TUBES[nom] = [T @ p for p in TUBES[nom]]
    for o in PIECES[nom]:
        if o.parent is None or o.parent not in PIECES[nom]:
            o.matrix_world = T @ o.matrix_world
    CADRES[nom] = T.to_3x3() @ CADRES[nom]
    bpy.context.view_layer.update()


def cadre_axes(nom):
    C = CADRES[nom]
    return [Vector(C.col[i]).normalized() for i in range(3)]


def L(x):
    """fraction de H -> metres (nombres, listes imbriquees)."""
    if isinstance(x, (list, tuple)):
        return [L(v) for v in x]
    return float(x) * H


def _nombres(v, n=None, quoi="valeur"):
    """verifie une liste de nombres (ou de points) ; message clair sinon."""
    try:
        a = np.array(v, dtype=float)
    except (TypeError, ValueError):
        raise SystemExit(f"{quoi} : nombres attendus, recu {v}")
    if n is not None and a.shape[-1:] != (n,):
        raise SystemExit(f"{quoi} : {n} nombres attendus par element, recu {v}")
    if not np.isfinite(a).all():
        raise SystemExit(f"{quoi} : nombre invalide dans {v}")
    return a


MATIERES = ("mat", "metal", "brillant", "tissu", "peau", "rugueux")


def matiere_op(op):
    """"matiere" : comment la surface prend la lumiere du canon (metal, brillant, tissu, peau, rugueux, mat)."""
    m = op.get("matiere")
    if m is not None and m not in MATIERES:
        raise SystemExit(f"matiere inconnue : {m}. Matieres : {', '.join(MATIERES)}")
    return m


def nouvelle_piece(op):
    nom, forme = op["nom"], op.get("forme")
    if nom in PIECES or nom in ("sujet", "base"):
        raise SystemExit(f"piece '{nom}' : ce nom existe deja (ou est reserve). Donne un autre \"nom\".")
    if forme == "tube":
        pts = _nombres(op["points"], 3, "tube : points [[droite, avant, haut], ...]")
        if len(pts) < 2:
            raise SystemExit("tube : au moins 2 points")
        r_ = op.get("rayons", 0.03)
        if isinstance(r_, list) and len(r_) not in (1, len(pts)):
            raise SystemExit(f"tube : {len(pts)} points mais {len(r_)} rayons (un rayon par point, ou un seul nombre)")
        if isinstance(r_, list) and len(r_) == 1:
            op = dict(op, rayons=r_[0])
    elif forme == "lame":
        c_ = _nombres(op["contour"], 2, "lame : contour [[droite, haut], ...]")
        if len(c_) < 3:
            raise SystemExit("lame : au moins 3 points de contour (un triangle)")
    elif forme in ("masse", "bloc"):
        d_ = _nombres(op.get("dimensions", [0.2, 0.2, 0.2]), 3, f"{forme} : dimensions [largeur, profondeur, hauteur]")
        if (d_ <= 0).any():
            raise SystemExit(f"{forme} : dimensions > 0")
    elif forme == "tour":
        if float(op.get("hauteur", 0.2)) <= 0 or float(op.get("rayon", 0.05)) <= 0:
            raise SystemExit("tour : hauteur et rayon > 0")
        if op.get("profil") is not None:
            pr = _nombres(op["profil"], 2, "tour : profil [[t, r], ...]")
            if len(pr) < 2:
                raise SystemExit("tour : profil d'au moins 2 points")
    if forme == "tour":
        o = P.tour(nom, L(op.get("hauteur", 0.2)), L(op.get("rayon", 0.05)), op.get("profil"))
    elif forme == "tube":
        o = P.tube(nom, L(op["points"]), L(op.get("rayons", 0.03)))
        TUBES[nom] = [Vector(p) for p in L(op["points"])]   # en repere de piece ; passe en monde plus bas
    elif forme == "masse":
        o = P.masse(nom, L(op.get("dimensions", [0.2, 0.2, 0.2])), op.get("bosses", 0.0), op.get("graine", 0))
    elif forme == "bloc":
        o = P.bloc(nom, L(op.get("dimensions", [0.2, 0.2, 0.2])), op.get("arrondi", 0.1))
    elif forme == "lame":
        o = P.lame(nom, L(op["contour"]), L(op.get("epaisseur", 0.01)),
                   lisse=int(op.get("lisse", 0 if float(op.get("epaisseur", 0.01)) == 0 else 1)))  # "lisse": 0 = aretes nettes (toit, mur)
    else:
        raise SystemExit(f"forme inconnue : {forme}. Formes : tour, tube, masse, bloc, lame")
    # repere propre de la piece (X droite, Y avant, Z haut) -> repere du sujet
    B = Matrix((tuple(REP["r"]), tuple(REP["f"]), tuple(REP["u"]))).transposed()
    o.matrix_world = Matrix.Translation(REP["centre"]) @ B.to_4x4()
    PIECES[nom] = [o]; CADRES[nom] = B.copy()
    if nom in TUBES:
        TUBES[nom] = [o.matrix_world @ p for p in TUBES[nom]]
    G.colorer([o], op.get("couleur", "#a0a0a0"), op.get("emission", 0.0), op.get("alpha", 1.0), nom=f"mat_{nom}", matiere=matiere_op(op))
    if op.get("a") is not None:
        placer({"quoi": nom, "a": op["a"]})
    return o


def importer_piece(op):
    nom = op["nom"]
    nv = [o for o in G.importer(op["fichier"]) if o.type in ("MESH", "EMPTY")]
    for o in nv:  # une piece importee = des maillages rigides (on retire leur squelette eventuel)
        if o.type == "MESH":
            for m in list(o.modifiers):
                if m.type == "ARMATURE":
                    o.modifiers.remove(m)
    ms = [o for o in nv if o.type == "MESH"]
    for o in ms:
        mw = o.matrix_world.copy(); o.parent = None; o.matrix_world = mw
    for o in nv:
        if o.type == "EMPTY":
            bpy.data.objects.remove(o, do_unlink=True)
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and not o.children and o not in SUJET:
            bpy.data.objects.remove(o, do_unlink=True)
    PIECES[nom] = ms
    # cadre d'une piece importee : convention des imports (haut Z, avant -Y) ; "retourner_piece" pour corriger
    CADRES[nom] = Matrix(((-1, 0, 0), (0, -1, 0), (0, 0, 1)))  # colonnes : droite -X, avant -Y, haut Z
    d = dossier_modele(op["fichier"])
    if d:
        SOURCES.append(d)
    if op.get("couleur"):
        G.colorer(ms, op["couleur"], nom=f"mat_{nom}", matiere=matiere_op(op))
    # l'avant et le haut d'un objet telecharge ne se devinent pas : l'IA les choisit sur la planche des 6 cotes
    if op.get("avant_piece") and op.get("haut_piece"):
        if not (1 <= int(op["avant_piece"]) <= 6 and 1 <= int(op["haut_piece"]) <= 6):
            raise SystemExit(f"{nom} : avant_piece et haut_piece = numeros de 1 a 6 (lus sur piece_{nom}_6_cotes.png)")
        f, u = AXES6[int(op["avant_piece"]) - 1], AXES6[int(op["haut_piece"]) - 1]
        if abs(f.dot(u)) > 0.5:
            raise SystemExit(f"{nom} : avant_piece et haut_piece doivent etre deux cotes differents et non opposes")
        CADRES[nom] = Matrix((tuple(f.cross(u)), tuple(f), tuple(u))).transposed()
    else:
        p = planche_six_cotes(nom)
        ALERTES.append(f"{nom} : orientation NON confirmee. REGARDE {p} et ajoute a l'operation importer "
                       f"\"avant_piece\": <numero du cote qui est l'AVANT>, \"haut_piece\": <numero du cote qui est le HAUT>")
    return ms


AXES6 = [Vector((0, -1, 0)), Vector((0, 1, 0)), Vector((-1, 0, 0)), Vector((1, 0, 0)), Vector((0, 0, 1)), Vector((0, 0, -1))]


def planche_six_cotes(nom):
    """La piece seule, vue de ses 6 cotes (numeros 1 a 6) : la case n montre la face qui regarde AXES6[n-1]."""
    autres = [o for o in bpy.data.objects if o.type == "MESH" and o not in PIECES[nom] and not o.hide_render]
    for o in autres:
        o.hide_render = True
    cam = preparer_rendu(260)
    pts = G.points_monde(PIECES[nom], 8000); c = Vector((pts.min(0) + pts.max(0)) / 2); t = float(np.ptp(pts, 0).max())
    cam.data.ortho_scale = t * 1.3; cam.data.clip_end = t * 40
    ims = []
    for i, v in enumerate(AXES6):
        cam.location = c + v * t * 8
        haut = Vector((0, 0, 1)) if abs(v.z) < 0.9 else Vector((0, 1, 0))
        cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
        if abs(v.z) > 0.9:
            cam.rotation_euler = (-v).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        p = os.path.abspath(os.path.join(DOSSIER, f"_vue_{os.getpid()}.png")); bpy.context.scene.render.filepath = p
        bpy.ops.render.render(write_still=True)
        ims.append(numeroter(ajuster(lire_image(p), 260, 260, fond=(0.75, 0.82, 0.88)), i + 1, k=3)); os.remove(p)
    for o in autres:
        o.hide_render = False
    p = os.path.join(DOSSIER, f"piece_{nom}_6_cotes.png")
    ecrire_image(p, grille(ims, colonnes=3, case=(260, 260)))
    return p


def orienter_piece(nom, haut_vers, avant_vers):
    """Rotation exacte : l'axe 'haut' de la piece -> haut_vers, son 'avant' -> avant_vers (projete)."""
    r, f, u = cadre_axes(nom)
    hv = haut_vers.normalized()
    av = (avant_vers - hv * avant_vers.dot(hv))
    if av.length < 1e-6:  # avant_vers parallele a haut_vers : on garde l'avant actuel au mieux
        av = f - hv * f.dot(hv)
        if av.length < 1e-6:
            av = r.cross(hv)
    av.normalize()
    cible = Matrix((tuple(av.cross(hv)), tuple(av), tuple(hv))).transposed()   # colonnes : droite, avant, haut
    actuel = Matrix((tuple(r), tuple(f), tuple(u))).transposed()
    Rm = cible @ actuel.inverted()
    p = G.points_monde(PIECES[nom], 3000); c = Vector(p.mean(0))
    transformer(nom, Matrix.Translation(c) @ Rm.to_4x4() @ Matrix.Translation(-c))


def tourner_piece(nom, axe, degres):
    p = G.points_monde(PIECES[nom], 3000); c = Vector(p.mean(0))
    transformer(nom, Matrix.Translation(c) @ Matrix.Rotation(math.radians(degres), 4, axe) @ Matrix.Translation(-c))


def taille_piece(nom, taille):
    """taille : nombre (plus grande dimension, fraction de H) ou {"hauteur"|"largeur"|"profondeur": x}."""
    r, f, u = cadre_axes(nom)
    if isinstance(taille, dict):
        k, v = next(iter(taille.items()))
        axe = {"hauteur": u, "largeur": r, "profondeur": f}[k]
        p = G.points_monde(PIECES[nom], 4000); t = float(np.ptp(p @ np.array(axe)))
    else:
        v = taille; p = G.points_monde(PIECES[nom], 4000); t = float(np.ptp(p, 0).max())
    k = L(v) / max(t, 1e-9); c = Vector(p.mean(0))
    transformer(nom, Matrix.Translation(c) @ Matrix.Scale(k, 4) @ Matrix.Translation(-c))


def placer(op):
    """Place le CENTRE de la piece a une position du repere du sujet [droite, avant, haut] (fractions de H)."""
    nom = op["quoi"]
    if op.get("haut_vers") or op.get("avant_vers"):
        orienter_piece(nom, G.direction(op.get("haut_vers", "haut"), REP), G.direction(op.get("avant_vers", "avant"), REP))
    if op.get("taille") is not None:
        taille_piece(nom, op["taille"])
    p = G.points_monde(PIECES[nom], 4000)
    cible = G.depuis_repere(op["a"], REP)
    v = cible - Vector((p.min(0) + p.max(0)) / 2)
    transformer(nom, Matrix.Translation(v))


SYNONYMES_ZONES = {"bassin": "hanches", "hanche": "hanches", "poitrine": "torse", "buste": "torse", "visage": "tete", "crane": "tete",
                   "nuque": "cou", "main_droite": "main_d", "main_gauche": "main_g", "pied_droit": "pied_d", "pied_gauche": "pied_g",
                   "epaule_droite": "epaule_d", "epaule_gauche": "epaule_g", "bras_droit": "bras_d", "bras_gauche": "bras_g",
                   "dessus": "haut", "dessous": "bas", "devant": "avant", "derriere": "arriere", "milieu": "centre"}


def zone_nom(z):
    """nom de zone tel qu'ecrit -> nom connu (synonymes, os sans prefixe 'os:')."""
    Z = ZONES()
    if z in Z:
        return z
    if z in SYNONYMES_ZONES and SYNONYMES_ZONES[z] in Z:
        return SYNONYMES_ZONES[z]
    if "os:" + z in Z:
        return "os:" + z
    return z


def zone_ou_point(op, rep):
    if "point" in op:
        return G.depuis_repere(op["point"], rep), op.get("cote", "avant"), None, {"point": G.depuis_repere(op["point"], rep)}
    Z = ZONES()
    z = zone_nom(op.get("zone", "centre"))
    if z not in Z:
        raise SystemExit(f"zone inconnue : '{z}'. Zones de ce modele : {sorted(Z)} (lance usine analyser pour les voir)")
    return Z[z]["point"].copy(), op.get("cote", Z[z]["cote"]), Z[z]["os"], Z[z]


_Z = {}
def ZONES():
    if "z" not in _Z:
        _Z["z"] = G.zones(objets_de("sujet"), ARM, REP) if objets_de("sujet") else {
            n_: {"point": REP["centre"].copy(), "cote": {"haut": "dessus", "bas": "dessous", "centre": "avant"}.get(n_, n_), "os": None}
            for n_ in ("centre", "haut", "bas", "avant", "arriere", "droite", "gauche")}
        # zones donnees a la main dans la recette (squelette aux noms inhabituels) : {"main_d": "os:Palm.R", ...}
        for z, cible in (M.get("zones") or {}).items():
            nb = cible[3:] if cible.startswith("os:") else cible
            if ARM is None or nb not in ARM.data.bones:
                raise SystemExit(f"zones : os '{nb}' introuvable. Os : {[b.name for b in ARM.data.bones] if ARM else 'aucun squelette'}")
            b = ARM.data.bones[nb]; Mw = ARM.matrix_world
            _Z["z"][z] = {"point": Mw @ ((b.head_local + b.tail_local) / 2), "cote": _Z["z"].get(z, {}).get("cote", "dehors"),
                          "os": nb, "axe_os": (Mw @ b.tail_local - Mw @ b.head_local).normalized()}
    return _Z["z"]


def surface_cible(op):
    """objets 'sur' lesquels on pose + leur BVH (pose de repos)."""
    sur = op.get("sur", "sujet")
    noms = sur if isinstance(sur, list) else [sur]
    cibles = []
    soi = set(PIECES.get(op.get("quoi"), []))
    for n in noms:
        cibles += [o for o in objets_de(n) if o not in soi]
    return cibles, G.bvh_monde(cibles)


def poser(op):
    """Pose une piece SUR une surface : zone + cote -> point de la vraie surface -> contact sans enfoncement."""
    nom = op["quoi"]
    cibles, bvh = surface_cible(op)
    if bvh is None:
        raise SystemExit(f"rien sur quoi poser '{nom}'")
    A, cote, os_zone, zone = zone_ou_point(op, REP)
    sur = op.get("sur", "sujet")
    if not est_sujet(sur) and op.get("zone", "centre") in ("centre", "haut", "bas", "avant", "arriere", "droite", "gauche") \
            and "point" not in op:
        A = Vector(G.points_monde(cibles, 20000).mean(0))   # zones generiques d'une PIECE : depuis le centre de la piece
        zone = {"point": A}
        # la piece posee suivra la piece support (meme os)
        if cibles[0].parent is not None and cibles[0].parent_type == "BONE":
            os_zone = cibles[0].parent_bone
    d = G.direction_zone(zone, cote, REP)
    if op.get("decaler"):
        A = A + (REP["r"] * op["decaler"][0] + REP["f"] * op["decaler"][1] + REP["u"] * op["decaler"][2]) * H
    copies = [(nom, 0.0)]
    if op.get("symetrique"):
        e = float(op.get("ecart", 0.0))
        copies = [(nom, e)]
    resultats = []
    for n, ecart in copies:
        # orientation : haut de la piece -> haut_vers (defaut : haut du sujet) ; avant de la piece -> vers l'exterieur
        hv = G.direction(op["haut_vers"], REP) if op.get("haut_vers") and op["haut_vers"] != "normale" else REP["u"]
        S, N = G.point_surface(bvh, A + REP["r"] * ecart * H, d, H)
        if S is None:
            raise SystemExit(f"'{nom}' : aucune surface trouvee depuis la zone dans la direction '{cote}'")
        if op.get("haut_vers") == "normale":
            hv = N
        av = G.direction(op["avant_vers"], REP) if op.get("avant_vers") else d
        orienter_piece(n, hv, av)
        if op.get("tourner"):
            tourner_piece(n, cadre_axes(n)[2], op["tourner"])
        if op.get("incliner"):  # pencher le haut de la piece vers l'exterieur (degres)
            tourner_piece(n, cadre_axes(n)[2].cross(d).normalized(), -op["incliner"])
        if op.get("taille") is not None:
            taille_piece(n, op["taille"])
        G.centrer_sur(PIECES[n], S)
        if op.get("contact", True):
            G.resoudre_contact(PIECES[n], bvh, d, H, tolerance=float(op.get("tolerance", 0.004)))
            if op.get("enfoncer"):
                G.deplacer(PIECES[n], -d * L(op["enfoncer"]))
        resultats.append((n, S))
    # symetrie : copie miroir par le plan median du sujet
    if op.get("symetrique"):
        cop = G.miroir(PIECES[nom], REP, "_sym")
        PIECES[nom + "_sym"] = cop
        Rm = Matrix.Identity(3) - 2 * Matrix(((REP["r"].x ** 2, REP["r"].x * REP["r"].y, REP["r"].x * REP["r"].z),
                                               (REP["r"].y * REP["r"].x, REP["r"].y ** 2, REP["r"].y * REP["r"].z),
                                               (REP["r"].z * REP["r"].x, REP["r"].z * REP["r"].y, REP["r"].z ** 2)))
        CADRES[nom + "_sym"] = Rm @ CADRES[nom]
    # lien au squelette (la piece suit les animations)
    if ARM is not None and op.get("lier", True):
        zone_paire = op.get("zone", "")[-2:] in ("_g", "_d")
        for n in [nom] + ([nom + "_sym"] if op.get("symetrique") else []):
            c = Vector(G.points_monde(PIECES[n], 2000).mean(0))
            if op.get("os"):
                os_ = op["os"]
            elif os_zone and not (op.get("symetrique") and zone_paire):
                os_ = os_zone          # zone centrale (dos, tete...) : les deux copies suivent le meme os
            else:
                os_ = G.os_le_plus_proche(ARM, c)
            G.lier_os(PIECES[n], ARM, os_)
    mesurer(nom, op, bvh)


def englober(op):
    """Coiffe/enveloppe une zone (casque sur la tete, cloche sur un objet) : centre sur la VRAIE geometrie
    de la zone (sommets pondares sur son os) et taille = zone * (1 + marge). Mesure la part couverte."""
    nom = op["quoi"]
    Z = ZONES()
    z = zone_nom(op.get("zone", "tete"))
    if nom not in PIECES:
        raise SystemExit(f"englober : '{nom}' doit etre une PIECE (creee par piece ou importer). Pieces : {sorted(PIECES)}")
    if z not in Z:
        raise SystemExit(f"zone inconnue : '{z}'. Zones : {sorted(Z)}")
    if not objets_de("sujet"):
        raise SystemExit("englober : il n'y a pas encore de sujet a englober (pas de \"base\" et aucune autre piece)")
    pts = points_zone(Z[z], z)
    if len(pts) == 0:
        raise SystemExit(f"englober : la zone '{z}' ne contient aucun point du sujet")
    orienter_piece(nom, G.direction(op.get("haut_vers", "haut"), REP), G.direction(op.get("avant_vers", "avant"), REP))
    c_zone = Vector((pts.min(0) + pts.max(0)) / 2)
    r, f, u = cadre_axes(nom)
    dims_zone = [float(np.ptp(pts @ np.array(a))) for a in (REP["r"], REP["f"], REP["u"])]
    p = G.points_monde(PIECES[nom], 4000)
    dims_p = [float(np.ptp(p @ np.array(a))) for a in (REP["r"], REP["f"], REP["u"])]
    ks = [dz / max(dp, 1e-9) * (1 + float(op.get("marge", 0.35))) for dz, dp in zip(dims_zone, dims_p)]
    c = Vector(p.mean(0))
    mode = op.get("ajuster", "auto")
    if mode not in ("auto", "uniforme", "par_axe"):
        raise SystemExit("englober : \"ajuster\" = \"auto\", \"uniforme\" (garde la forme : casque) ou \"par_axe\" (manche, jambiere)")
    if mode == "par_axe" or (mode == "auto" and max(ks) > 1.5 * min(ks)):
        # zone allongee (bras, jambe, queue) : la piece prend la longueur ET l'epaisseur de la zone (sinon tube geant)
        S = Matrix.Identity(4)
        for k_, a in zip(ks, (REP["r"], REP["f"], REP["u"])):
            a = Vector(a).normalized(); S = S @ (Matrix.Identity(4) + (k_ - 1) * Matrix(
                [[a.x * a.x, a.x * a.y, a.x * a.z, 0], [a.y * a.x, a.y * a.y, a.y * a.z, 0], [a.z * a.x, a.z * a.y, a.z * a.z, 0], [0, 0, 0, 0]]))
        transformer(nom, Matrix.Translation(c) @ S @ Matrix.Translation(-c))
    else:
        transformer(nom, Matrix.Translation(c) @ Matrix.Scale(max(ks), 4) @ Matrix.Translation(-c))
    p = G.points_monde(PIECES[nom], 4000)
    v = c_zone - Vector((p.min(0) + p.max(0)) / 2)
    if op.get("decaler"):
        v += (REP["r"] * op["decaler"][0] + REP["f"] * op["decaler"][1] + REP["u"] * op["decaler"][2]) * H
    transformer(nom, Matrix.Translation(v))
    if ARM is not None and Z[z]["os"]:
        G.lier_os(PIECES[nom], ARM, Z[z]["os"])
    # mesure : part de la zone a l'INTERIEUR de la piece
    bvh_p = G.bvh_monde(PIECES[nom])
    couvre = G.part_englobee(pts[:: max(1, len(pts) // 400)], bvh_p, H)
    RAPPORT.append({"piece": nom, "operation": "englober", "zone": z, "zone_couverte": round(couvre, 3)})
    print(f"  MESURE {nom} : {couvre * 100:.0f} % de la zone '{z}' est a l'interieur")
    if couvre < 0.7:
        ALERTES.append(f"{nom} : seulement {couvre * 100:.0f} % de '{z}' est couvert -> augmente \"marge\" ou ajuste \"decaler\"")


def _proches(c, p):
    sel = p[np.linalg.norm(p - np.array(c), axis=1) < 0.1 * H]
    if len(sel) < 10 and len(p):  # zone sans sommets proches : les 200 sommets les plus proches
        sel = p[np.argsort(np.linalg.norm(p - np.array(c), axis=1))[:200]]
    return sel


def points_zone(zone, nom=None):
    """Sommets de la zone : ceux qui dependent surtout de l'os de la zone (poids > 0.5) ; zone generale (haut,
    avant...) : la tranche du sujet la plus loin dans cette direction (20 % de son epaisseur)."""
    if nom in ("haut", "bas", "avant", "arriere", "droite", "gauche"):
        p = G.points_monde(objets_de("sujet"), 30000)
        h = p @ np.array(G.direction(nom, REP))
        return p[h >= h.max() - 0.2 * (h.max() - h.min())]
    if ARM is None or not zone["os"]:
        return _proches(zone["point"], G.points_monde(objets_de("sujet"), 30000))
    out = []
    for o in objets_de("sujet"):
        g = o.vertex_groups.get(zone["os"])
        if g is None:
            continue
        M_ = np.array(o.matrix_world)
        for v in o.data.vertices:
            for ge in v.groups:
                if ge.group == g.index and ge.weight > 0.5:
                    out.append(np.array(v.co))
        if out:
            a = np.array(out); out = list(a @ M_[:3, :3].T + M_[:3, 3])
    if not out:
        return _proches(zone["point"], G.points_monde(objets_de("sujet"), 30000))
    return np.array(out)


def mesurer(nom, op, bvh):
    for n in [nom] + ([nom + "_sym"] if op.get("symetrique") else []):
        m = G.mesurer_contact(PIECES[n], bvh, H)
        m.update({"piece": n, "operation": op.get("faire")})
        RAPPORT.append(m)
        print(f"  MESURE {n} : enfoncement {m['enfoncement'] * 100:.1f} % de H, ecart {m['ecart'] * 100:.1f} % de H")
        if op.get("contact", True) and m["enfoncement"] > 0.01 + L(op.get("enfoncer", 0)) / H:
            ALERTES.append(f"{n} : enfoncee de {m['enfoncement'] * 100:.1f} % de H dans la surface")
        if op.get("contact", True) and m["ecart"] > 0.01:
            ALERTES.append(f"{n} : flotte a {m['ecart'] * 100:.1f} % de H de la surface")
    if op.get("symetrique"):
        a = G.points_monde(PIECES[nom], 1500).mean(0); b = G.points_monde(PIECES[nom + "_sym"], 1500).mean(0)
        c = np.array(REP["centre"]); r = np.array(REP["r"])
        err = abs(((a - c) @ r) + ((b - c) @ r)) / H
        RAPPORT.append({"piece": nom, "symetrie_ecart": round(float(err), 4)})


def couleur(op):
    cibles = cibles_op(op["quoi"])
    if op["quoi"] in PIECES or op.get("remplacer", True):
        G.colorer(cibles, op["couleur"], op.get("emission", 0.0), op.get("alpha", 1.0), nom=f"mat_{op['quoi']}", matiere=matiere_op(op))


def cacher(op):
    for o in cibles_op(op["quoi"]):
        o.hide_render = True


def fusionner(op):
    noms = op["quoi"] if isinstance(op["quoi"], list) else [op["quoi"]]
    for n in noms:
        if n not in PIECES:
            raise SystemExit(f"fusionner : piece inconnue '{n}'. Pieces : {sorted(PIECES)}")
    objs_ = sum((PIECES[n] for n in noms), [])
    if any(m.type == "ARMATURE" for o in objs_ for m in o.modifiers):
        ALERTES.append("fusionner : une piece suivait un squelette ; la piece fusionnee ne le suit plus -> fusionne AVANT 'squelette', ou garde les pieces separees")
    nom = op.get("nom", noms[0])
    if op.get("lisse", True):
        o = P.union_lisse(objs_, nom, finesse=L(op.get("finesse", 0.006)))
    else:
        o = P.joindre(objs_, nom)
    CADRES[nom] = CADRES[noms[0]].copy()
    for n in noms:
        PIECES.pop(n, None)
        if n in TUBES:
            LIGNES[n] = TUBES[n]
    PIECES[nom] = [o]
    if op.get("couleur"):
        G.colorer([o], op["couleur"], nom=f"mat_{nom}")


def _booleen(op, operation):
    """creuse (DIFFERENCE) ou garde le commun (INTERSECT) sur CHAQUE objet de 'quoi' (piece ou sujet)."""
    if op["outil"] not in PIECES:
        raise SystemExit(f"outil '{op['outil']}' : piece inconnue. Pieces : {sorted(PIECES)}")
    cibles = G.maillages(cibles_op(op["quoi"]))
    outils = PIECES.pop(op["outil"])
    if len(outils) > 1:
        copies = []
        for o in outils:
            if o.type == "MESH":
                k = o.copy(); k.data = o.data.copy(); bpy.context.scene.collection.objects.link(k); copies.append(k)
        outil = P.joindre(copies, "_outil")
    else:
        outil = outils[0]
    for o in cibles:
        P.booleen(o, outil, operation, garder_outil=True)
    for o in set(outils) | {outil}:
        if o.name in bpy.data.objects:
            bpy.data.objects.remove(o, do_unlink=True)
    vides = [o.name for o in cibles if not len(o.data.polygons)]
    if vides and len(vides) == len(cibles):
        raise SystemExit(f"{op['faire']} : il ne reste RIEN de '{op['quoi']}' (l'outil le contient en entier ou ne le touche pas)")


def soustraire(op):
    _booleen(op, "DIFFERENCE")


def intersecter(op):
    _booleen(op, "INTERSECT")


# ------------------------------------------------------------------ couper / squelette / repartir / animer
def copie_figee(objs, nom):
    """Copie des maillages DANS LEUR ETAT ACTUEL (deformations appliquees), en un seul objet sans squelette."""
    dg = bpy.context.evaluated_depsgraph_get()
    import bmesh
    bm = bmesh.new()
    mats = []
    for o in G.maillages(objs):
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
        me.transform(o.matrix_world)
        decal = len(mats)
        for m in me.materials:
            mats.append(m)
        for p in me.polygons:
            p.material_index += decal
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new(nom); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new(nom, me); bpy.context.scene.collection.objects.link(o)
    return o


def plan_de(op, cibles):
    """Plan de coupe : 'normale' (direction) + position 'hauteur' (0 = bout le plus bas de la cible le long de la normale,
    1 = bout le plus haut) ou 'point' [droite, avant, haut] du repere."""
    n = G.direction(op.get("normale", "haut"), REP)
    if op.get("point") is not None:
        return G.depuis_repere(op["point"], REP), n
    p = G.points_monde(cibles, 30000); h = p @ np.array(n)
    t = h.min() + float(op.get("hauteur", 0.5)) * (h.max() - h.min())
    c = Vector(p.mean(0)); c = c + n * (t - c.dot(n))
    return c, n


def couper(op):
    """Coupe une piece (ou le sujet) en deux par un plan. Les trous sont bouches (couleur 'couleur_coupe').
    Chaque morceau GARDE son squelette (un personnage coupe s'anime toujours)."""
    import bmesh
    quoi = op.get("quoi", "sujet")
    cibles = G.maillages(cibles_op(quoi))
    c, n = plan_de(op, cibles)
    bas_nom, haut_nom = op.get("noms", [quoi + "_bas", quoi + "_haut"])
    mat_coupe = G.materiau(f"mat_coupe_{quoi}", op.get("couleur_coupe", "#4a1a1a"))
    morceaux = {bas_nom: [], haut_nom: []}
    for src in cibles:
        A = src.matrix_world.to_3x3()
        c_l = src.matrix_world.inverted() @ c; n_l = (A.transposed() @ n).normalized()
        for nom, garder_haut in ((bas_nom, False), (haut_nom, True)):
            o = src.copy(); o.data = src.data.copy(); o.name = f"{nom}_{src.name}"[:60]
            for col in src.users_collection:
                col.objects.link(o)
            if o.data.shape_keys:
                o.shape_key_clear()
            bm = bmesh.new(); bm.from_mesh(o.data)
            geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
            r = bmesh.ops.bisect_plane(bm, geom=geom, plane_co=c_l, plane_no=n_l, clear_inner=garder_haut, clear_outer=not garder_haut)
            bord = [e for e in r["geom_cut"] if isinstance(e, bmesh.types.BMEdge)]
            if op.get("boucher", True) and bord:
                if mat_coupe.name not in [m.name for m in o.data.materials if m]:
                    o.data.materials.append(mat_coupe)
                idx = [m.name if m else "" for m in o.data.materials].index(mat_coupe.name)
                avant_f = set(bm.faces)
                bmesh.ops.holes_fill(bm, edges=bord, sides=0)   # chaque trou de la coupe est bouche separement
                for fa in bm.faces:
                    if fa not in avant_f:
                        fa.material_index = idx
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            vide = len(bm.faces) == 0
            bm.to_mesh(o.data); bm.free()
            if vide:
                bpy.data.objects.remove(o, do_unlink=True); continue
            for p_ in o.data.polygons:
                p_.use_smooth = True
            o.hide_render = False
            morceaux[nom].append(o)
    for o in cibles:
        o.hide_render = True
    B = Matrix((tuple(REP["r"]), tuple(REP["f"]), tuple(REP["u"]))).transposed()
    for nom, objs_ in morceaux.items():
        if objs_:
            PIECES[nom] = objs_; CADRES[nom] = B.copy()
        else:
            ALERTES.append(f"couper {quoi} : le morceau '{nom}' est VIDE (plan hors de l'objet) -> change 'hauteur' (entre 0 et 1) ou 'point'")
    if est_sujet(quoi):
        SUJET[:] = morceaux[bas_nom] + morceaux[haut_nom]
    else:
        PIECES.pop(quoi, None)
    _Z.clear()
    RAPPORT.append({"operation": "couper", "quoi": quoi, "plan": G.vers_repere(c, REP), "morceaux": [k for k, v in morceaux.items() if v]})


def squelette():
    """Le squelette du modele (cree s'il n'existe pas) et son os racine."""
    global ARM
    if ARM is None:
        a = bpy.data.armatures.new("squelette")
        ARM = bpy.data.objects.new("squelette", a); bpy.context.scene.collection.objects.link(ARM)
        ajouter_os("racine", REP["bas"], REP["bas"] + REP["u"] * 0.25 * H, None)
    return ARM


def os_racine():
    """L'os racine qui porte le corps : parmi les os sans parent, celui qui a le plus de descendants
    (les cibles IK et poles sont aussi sans parent, mais ne portent rien)."""
    return max((b for b in ARM.data.bones if b.parent is None), key=lambda b: len(b.children_recursive)).name


def ajouter_os(nom, tete, queue, parent):
    bpy.context.view_layer.objects.active = ARM
    for o in bpy.context.view_layer.objects:
        o.select_set(o == ARM)
    bpy.ops.object.mode_set(mode="EDIT")
    Mi = ARM.matrix_world.inverted()
    b = ARM.data.edit_bones.new(nom)
    b.head = Mi @ Vector(tete); b.tail = Mi @ Vector(queue)
    if parent:
        b.parent = ARM.data.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def charniere(op):
    """Charniere : la piece tourne autour d'un AXE pose sur un de ses BORDS (couvercle, porte, machoire, paupiere).
    bord : ex. 'arriere-bas' ; axe : ex. 'droite'. Cree l'os '<nom>' ; animation : {"<nom>": {"ouvrir": degres}}."""
    nom_p = op["quoi"]; nom = op.get("nom", nom_p)
    squelette()
    p = G.points_monde(PIECES[nom_p], 20000)
    piv = Vector(p.mean(0))
    for mot in op.get("bord", "arriere-bas").replace("+", "-").split("-"):
        d = G.direction(mot, REP); h = p @ np.array(d)
        piv = piv + d * (float(h.max()) - piv.dot(d))
    axe = G.direction(op.get("axe", "droite"), REP)
    hs = p @ np.array(axe); piv = piv + axe * ((float(hs.max()) + float(hs.min())) / 2 - piv.dot(axe))
    longueur = float(hs.max() - hs.min()) / 2
    n_seg = int(op.get("segments", 1))
    if not 1 <= n_seg <= 8:
        raise SystemExit("charniere : \"segments\" de 1 a 8")
    ajouter_os(nom, piv - axe * longueur, piv + axe * longueur, op.get("parent_os") or os_racine())
    if n_seg == 1:
        G.lier_os(PIECES[nom_p], ARM, nom)
    else:   # la piece se PLIE : n charnieres paralleles en chaine, du bord vers le bout, peau douce entre elles
        a_ = np.array(axe); q_ = p - np.array(piv); q_ -= np.outer(q_ @ a_, a_)
        d_out = Vector(q_.mean(0)).normalized(); ext = float((q_ @ np.array(d_out)).max())
        noms = [nom] + [f"{nom}_{k}" for k in range(2, n_seg + 1)]
        for k in range(1, n_seg):
            c_ = piv + d_out * ext * k / n_seg
            ajouter_os(noms[k], c_ - axe * longueur, c_ + axe * longueur, noms[k - 1])
        ARM.data.bones[nom]["usine_segments"] = noms
        for o in G.maillages(PIECES[nom_p]):
            for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
                o.modifiers.remove(m)
            mw = o.matrix_world.copy(); o.parent = ARM; o.parent_type = "OBJECT"; bpy.context.view_layer.update(); o.matrix_world = mw
            gs = [o.vertex_groups.get(n_) or o.vertex_groups.new(name=n_) for n_ in noms]
            for v in o.data.vertices:
                t = (o.matrix_world @ v.co - piv).dot(d_out) / max(ext, 1e-9) * n_seg   # 0 au bord, n_seg au bout
                for k in range(n_seg):   # poids en rampe douce autour de chaque pli
                    w = min(1.0, max(0.0, t - k + 0.5)) * (1.0 if k == n_seg - 1 else min(1.0, max(0.0, k + 1.5 - t)))
                    if w > 0:
                        gs[k].add([v.index], w, "REPLACE")
            md = o.modifiers.new("squelette", "ARMATURE"); md.object = ARM
        bpy.context.view_layer.update()
    # sens d'ouverture : un angle POSITIF fait aller la piece vers 'ouvre_vers' (defaut : haut)
    pb = ARM.pose.bones[nom]; pb.rotation_mode = "XYZ"
    ARM.data.pose_position = "POSE"
    c0 = Vector(G.points_monde(PIECES[nom_p], 2000).mean(0))
    pb.rotation_euler = (0, math.radians(15), 0); bpy.context.view_layer.update()
    c1 = Vector(G.points_monde(PIECES[nom_p], 2000).mean(0))
    pb.rotation_euler = (0, 0, 0); bpy.context.view_layer.update()
    ARM.data.pose_position = "REST"; bpy.context.view_layer.update()
    sens = 1 if (c1 - c0).dot(G.direction(op.get("ouvre_vers", "haut"), REP)) >= 0 else -1
    ARM.data.bones[nom]["usine_sens"] = sens
    for n_ in ARM.data.bones[nom].get("usine_segments", []):
        ARM.data.bones[n_]["usine_sens"] = sens
    RAPPORT.append({"operation": "charniere", "os": nom, "pivot": G.vers_repere(piv, REP), "axe": op.get("axe", "droite")})


def section(cibles, c, n):
    """Courbe de section de la surface par un plan : points ordonnes (tour complet)."""
    import bmesh
    o = copie_figee(cibles, "_section")
    bm = bmesh.new(); bm.from_mesh(o.data)
    r = bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=c, plane_no=n)
    pts = np.array([v.co[:] for v in r["geom_cut"] if isinstance(v, bmesh.types.BMVert)])
    bm.free(); bpy.data.objects.remove(o, do_unlink=True)
    if len(pts) < 3:
        return None
    # on garde le contour EXTERIEUR : enveloppe angulaire (pour chaque angle, le point le plus loin du centre)
    n_ = np.array(n); a0 = np.cross(n_, [1, 0, 0]) if abs(n_[0]) < 0.9 else np.cross(n_, [0, 1, 0]); a0 /= np.linalg.norm(a0)
    b0 = np.cross(n_, a0); ctr = pts.mean(0); q = pts - ctr
    ang = np.arctan2(q @ b0, q @ a0); rad = np.hypot(q @ a0, q @ b0)
    bins = np.linspace(-np.pi, np.pi, 181); out = []
    for i in range(180):
        m = (ang >= bins[i]) & (ang < bins[i + 1])
        if m.any():
            j = np.argmax(np.where(m, rad, -1)); out.append(pts[j])
    return np.array(out), ctr


def repartir(op):
    """Repartit N copies d'une piece : le long d'une SECTION de la surface (bord, ceinture, rangee de dents)
    ou sur une ZONE de surface (ecailles, pics, boutons). Chaque copie est orientee sur la surface."""
    nom = op["quoi"]; N = int(op.get("nombre", 8))
    if N < 1:
        raise SystemExit(f"repartir {nom} : nombre >= 1")
    if nom not in PIECES:
        raise SystemExit(f"repartir : piece inconnue '{nom}'. Pieces : {sorted(PIECES)}")
    sur = op.get("sur", "sujet"); cibles = [o for o in objets_de(sur) if o not in PIECES[nom]]
    if not cibles:
        raise SystemExit(f"repartir {nom} : rien sur quoi repartir ('sur' : {sur})")
    if "zone" in op:
        return repartir_surface(op, cibles)
    c, n = plan_de(op.get("le_long", {}), cibles)
    res = section(cibles, c, n)
    if res is None:
        raise SystemExit(f"repartir {nom} : le plan ne coupe pas '{sur}' (change 'hauteur')")
    pts, ctr = res
    retrait = L(op.get("le_long", {}).get("retrait", 0.0))
    if retrait:
        v = pts - ctr; v /= np.linalg.norm(v, axis=1, keepdims=True); pts = pts - v * retrait
    # parametre par longueur d'arc sur la boucle fermee
    boucle = np.vstack([pts, pts[:1]]); seg = np.linalg.norm(np.diff(boucle, axis=0), axis=1); s = np.concatenate([[0], np.cumsum(seg)])
    garder = op.get("seulement")  # ex. "avant" : garde les positions dont l'exterieur regarde vers l'avant (+ cotes)
    cibles_s = (np.arange(N) + 0.5) / N * s[-1] if not garder else None
    if garder:
        dg = G.direction(garder, REP)
        cand = (np.arange(N * 6) + 0.5) / (N * 6) * s[-1]
        ok = []
        for t in cand:
            i = min(np.searchsorted(s, t) - 1, len(pts) - 1); p_ = boucle[i] + (boucle[i + 1] - boucle[i]) * ((t - s[i]) / max(seg[i], 1e-9))
            if (Vector(p_ - ctr).normalized()).dot(dg) > float(op.get("seuil", 0.0)):
                ok.append(t)
        if not ok:
            raise SystemExit(f"repartir {nom} : aucune position cote '{garder}'")
        ok = np.array(ok); cibles_s = np.linspace(ok.min(), ok.max(), N) if N > 1 else ok[len(ok) // 2:len(ok) // 2 + 1]
    modele = PIECES[nom]; cad0 = CADRES[nom].copy()
    copies = []
    for k, t in enumerate(cibles_s):
        i = min(np.searchsorted(s, t) - 1, len(pts) - 1)
        p_ = Vector(boucle[i] + (boucle[i + 1] - boucle[i]) * ((t - s[i]) / max(seg[i], 1e-9)))
        dehors = (p_ - Vector(ctr)); dehors = (dehors - n * dehors.dot(n)).normalized()
        nm = f"{nom}_{k + 1}"; REPARTIS.setdefault(nom, []).append(nm)
        objs_k = []
        for o in modele:
            kk = o.copy(); kk.data = o.data.copy(); kk.name = nm; kk.parent = None
            bpy.context.scene.collection.objects.link(kk); kk.matrix_world = o.matrix_world.copy(); objs_k.append(kk)
        PIECES[nm] = objs_k; CADRES[nm] = cad0.copy()
        hv = G.direction(op["haut_vers"], REP) if op.get("haut_vers") else n
        orienter_piece(nm, hv, dehors if op.get("avant_vers", "dehors") == "dehors" else G.direction(op["avant_vers"], REP))
        if op.get("taille") is not None:
            taille_piece(nm, op["taille"])
        pp = G.points_monde(objs_k, 2000)
        ancre = op.get("ancre", "base")  # 'base' : le pied de la piece sur la courbe ; 'centre' : son centre
        if ancre == "base":
            hvv = cadre_axes(nm)[2]; h = pp @ np.array(hvv)
            bas_ = Vector(pp.mean(0)) + hvv * (float(h.min()) - Vector(pp.mean(0)).dot(hvv))
            G.deplacer(objs_k, p_ - bas_)
        else:
            G.deplacer(objs_k, p_ - Vector(pp.mean(0)))
        if op.get("enfoncer"):
            G.deplacer(objs_k, -cadre_axes(nm)[2] * L(op["enfoncer"]))
        lien = op.get("os") or (cibles[0].parent_bone if cibles and cibles[0].parent and cibles[0].parent_type == "BONE" else None)
        if ARM is not None and lien:
            G.lier_os(objs_k, ARM, lien)
        copies.append(nm)
    for o in modele:
        bpy.data.objects.remove(o, do_unlink=True)
    PIECES.pop(nom); CADRES.pop(nom)
    RAPPORT.append({"operation": "repartir", "quoi": nom, "copies": len(copies), "sur": sur})


def repartir_surface(op, cibles):
    nom = op["quoi"]; N = int(op.get("nombre", 8))
    A, cote, os_zone, zone = zone_ou_point(op, REP)
    bvh = G.bvh_monde(cibles)
    S, _ = G.point_surface(bvh, A, G.direction_zone(zone, cote, REP), H)
    rayon = L(op.get("rayon", 0.1))
    if S is None:
        S = A
    p = G.points_surface_uniformes(cibles, 40000)
    proches = p[np.linalg.norm(p - np.array(S), axis=1) < rayon]
    if len(proches) < max(N, 1):
        raise SystemExit(f"repartir {nom} : zone trop petite pour {N} copies (augmente 'rayon')")
    if len(proches) > 6000:
        proches = proches[:: len(proches) // 6000 + 1]
    # echantillonnage le plus regulier possible : point le plus eloigne des deja choisis (Poisson approche)
    choix = [proches[np.argmin(np.linalg.norm(proches - np.array(S), axis=1))]]
    for _ in range(N - 1):
        d = np.min(np.linalg.norm(proches[:, None] - np.array(choix)[None], axis=2), axis=1)
        choix.append(proches[np.argmax(d)])
    modele = PIECES[nom]; cad0 = CADRES[nom].copy()
    for k, q in enumerate(choix):
        loc, nor, _, _ = bvh.find_nearest(Vector(q))
        nm = f"{nom}_{k + 1}"; objs_k = []; REPARTIS.setdefault(nom, []).append(nm)
        for o in modele:
            kk = o.copy(); kk.data = o.data.copy(); kk.name = nm; kk.parent = None
            bpy.context.scene.collection.objects.link(kk); kk.matrix_world = o.matrix_world.copy(); objs_k.append(kk)
        PIECES[nm] = objs_k; CADRES[nm] = cad0.copy()
        orienter_piece(nm, nor, REP["u"] if abs(nor.dot(REP["u"])) < 0.9 else REP["f"])
        if op.get("taille") is not None:
            taille_piece(nm, op["taille"])
        pp = G.points_monde(objs_k, 2000); hvv = cadre_axes(nm)[2]; h = pp @ np.array(hvv)
        bas_ = Vector(pp.mean(0)) + hvv * (float(h.min()) - Vector(pp.mean(0)).dot(hvv))
        G.deplacer(objs_k, loc - bas_ - hvv * L(op.get("enfoncer", 0.0)))
        if ARM is not None:
            G.lier_os(objs_k, ARM, op.get("os") or G.os_le_plus_proche(ARM, loc))
    for o in modele:
        bpy.data.objects.remove(o, do_unlink=True)
    PIECES.pop(nom); CADRES.pop(nom)


def _melanger(p0, p1, k):
    """pose p0 + k * (p1 - p0), sur les valeurs NUMERIQUES (degres, decalages) ; le reste vient de p1."""
    out = {}
    for c in set(p0) | set(p1):
        a_, b_ = p0.get(c), p1.get(c)
        if isinstance(a_, dict) or isinstance(b_, dict):
            out[c] = _melanger(a_ or {}, b_ or {}, k)
        elif isinstance(b_, (int, float)) or isinstance(a_, (int, float)):
            x0 = a_ if isinstance(a_, (int, float)) else (1 if c == "grossir" else 0)
            x1 = b_ if isinstance(b_, (int, float)) else (1 if c == "grossir" else 0)
            out[c] = x0 + k * (x1 - x0)
        elif b_ is not None:
            out[c] = b_
    return out


def preparer_cles(cles, anticipation=0.0):
    """Outils d'animation universels (tout squelette) :
    "tenir": d sur une cle -> la pose reste figee jusqu'a t + d (impact, pose forte) ;
    "anticipation": a sur l'animation -> avant chaque grand geste, la pose part d'abord a l'OPPOSE (a = part du geste,
    0.2 a 0.4), juste avant la cle. Valeurs numeriques seulement (ouvrir, plier, virer, rouler, racine)."""
    cles = sorted([dict(c) for c in cles], key=lambda c: float(c["t"]))
    out = []
    for i, c in enumerate(cles):
        if anticipation and i > 0 and not c.get("sans_anticipation"):
            p = cles[i - 1]; dt = float(c["t"]) - float(p["t"])
            if dt > 0.12:
                pose_p = {"os": p.get("os", {}), "racine": p.get("racine", {})}
                pose_c = {"os": c.get("os", {}), "racine": c.get("racine", {})}
                a_ = _melanger(pose_c, pose_p, 1 + anticipation)   # au-dela de la pose precedente, a l'oppose du geste
                out.append({"t": float(c["t"]) - dt * 0.35, "os": a_.get("os", {}), **({"racine": a_["racine"]} if a_.get("racine") else {})})
        out.append(c)
        if c.get("tenir"):
            out.append({k: v for k, v in c.items() if k != "tenir"} | {"t": min(1.0, float(c["t"]) + float(c["tenir"]))})
    return sorted(out, key=lambda c: float(c["t"]))


def animation(op):
    """Animation par images cles. cles : [{"t": 0..1, "os": {"<os>": {"ouvrir": deg} | {"tourner": [x, y, z]}},
    "racine": {"haut": h, "avant": a, "droite": d, "tourner": deg, "grossir": k}}]. t = 0 debut, 1 fin (boucle : derniere = premiere)."""
    squelette()
    figer_contraintes()
    nom = op["nom"]; n_img = int(op.get("images", 12))
    act = bpy.data.actions.new(nom); act.use_fake_user = True
    ARM.animation_data_create(); ARM.animation_data.action = act
    ARM.data.pose_position = "POSE"
    rac = os_racine()
    Mw = ARM.matrix_world.to_3x3()
    cles = list(op.get("cles", []))
    # onde : chaque os d'une chaine suit une sinusoide decalee (nage, queue, tentacule, ver, drapeau)
    for onde in op.get("ondes", []):
        chaine = sorted([b.name for b in ARM.data.bones if b.name.startswith(onde["chaine"] + "_")],
                        key=lambda n: int(n.rsplit("_", 1)[1]))
        nb = int(op.get("images", 12))
        for i in range(nb + 1):
            t = i / nb
            poses = {}
            for k, b in enumerate(chaine):
                amp = float(onde.get("amplitude", 20)) * (1 + float(onde.get("croissance", 1.0)) * k / max(len(chaine) - 1, 1)) / 2
                ang = amp * math.sin(2 * math.pi * (t * float(onde.get("tours", 1)) - k * float(onde.get("decalage", 0.15))))
                poses[b] = {onde.get("axe", "virer"): ang}
            cles.append({"t": t, "os": poses})
    cles = preparer_cles(cles, float(op.get("anticipation", 0)))
    ips = 24 * float(op.get("duree_ms", 100)) / 1000      # images Blender (24/s) par image du sprite : vraie duree
    for cle in cles:
        fr = 1 + float(cle["t"]) * n_img * ips
        for b in ARM.pose.bones:  # chaque cle fixe tous les os cites ; les autres gardent leur pose de repos
            pass
        poses_cle = {resoudre_nom_os(k): v for k, v in cle.get("os", {}).items()}
        for k_ in list(poses_cle):   # "replier": deg sur une charniere a segments = chaque pli suivant s'ouvre de deg
            segs = ARM.data.bones[k_].get("usine_segments") if k_ in ARM.data.bones else None
            if segs and "replier" in poses_cle[k_]:
                pl = float(poses_cle[k_]["replier"])
                for n_ in list(segs)[1:]:
                    d_ = dict(poses_cle.get(n_, {})); d_["ouvrir"] = float(d_.get("ouvrir", 0)) + pl; poses_cle[n_] = d_
                poses_cle[k_] = {kk: vv for kk, vv in poses_cle[k_].items() if kk != "replier"}
        for pb in ARM.pose.bones:  # chaque cle repart de la pose de repos (les os non cites restent au repos)
            pb.rotation_mode = "QUATERNION"; pb.rotation_quaternion = (1, 0, 0, 0)
        bpy.context.view_layer.update()
        for nom_os in sorted(poses_cle, key=profondeur_os):
            pose = poses_cle[nom_os]
            pb = ARM.pose.bones[nom_os]
            pb.rotation_quaternion = rotation_os(nom_os, pose)
            bpy.context.view_layer.update()
            if "vers" in pose:
                viser(nom_os, G.direction(pose["vers"], REP))
            if "atteindre" in pose:
                atteindre(nom_os, pose["atteindre"], pose.get("coude_vers"))
        for nom_os in poses_cle:
            pb = ARM.pose.bones[nom_os]
            pb.keyframe_insert("rotation_quaternion", frame=fr)
            par = pb.parent
            if "atteindre" in poses_cle[nom_os] and par is not None:
                par.keyframe_insert("rotation_quaternion", frame=fr)
        r = cle.get("racine")
        if r is not None:
            pb = ARM.pose.bones[rac]; pb.rotation_mode = "XYZ"
            dw = (REP["u"] * r.get("haut", 0) + REP["f"] * r.get("avant", 0) + REP["r"] * r.get("droite", 0)) * H
            loc = ARM.data.bones[rac].matrix_local.to_3x3().inverted() @ (Mw.inverted() @ dw)
            pb.location = loc; pb.keyframe_insert("location", frame=fr)
            if "tourner" in r:  # rotation autour du haut du sujet
                q = (ARM.data.bones[rac].matrix_local.to_3x3().inverted() @ (Mw.inverted() @ REP["u"])).normalized()
                pb.rotation_mode = "AXIS_ANGLE"; pb.rotation_axis_angle = (math.radians(r["tourner"]), *q)
                pb.keyframe_insert("rotation_axis_angle", frame=fr)
            if "grossir" in r or "ecraser" in r:  # echelle (1 = taille du modele) ; ecraser k : plus bas et plus large (volume garde)
                g = r.get("grossir", 1); g = (g, g, g) if isinstance(g, (int, float)) else tuple(g)
                e = float(r.get("ecraser", 0)); f_ = (1 + e / 2, 1 - e, 1 + e / 2)   # Y de l'os racine = le haut
                pb.scale = tuple(a_ * b_ for a_, b_ in zip(g, f_)); pb.keyframe_insert("scale", frame=fr)
    act.frame_range = (1, 1 + n_img * ips)
    ANIMS_CREES.append((nom, n_img, cles))
    ARM.animation_data.action = None
    for pb in ARM.pose.bones:
        pb.location = (0, 0, 0); pb.rotation_euler = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.scale = (1, 1, 1)
        pb.rotation_axis_angle = (0, 0, 1, 0); pb.rotation_mode = "QUATERNION"   # sinon un "tourner" deborde sur les autres animations
    ARM.data.pose_position = "REST"; bpy.context.view_layer.update()
    print(f"  animation '{nom}' : {len(cles)} cles sur {n_img} images (dans la recette : \"action\": \"{nom}\")")


def lier(op):
    """Attache une piece a un os (elle suivra ses mouvements). Sans 'os' : l'os le plus proche."""
    squelette()
    objs_ = cibles_op(op["quoi"])
    c = Vector(G.points_monde(objs_, 1000).mean(0))
    G.lier_os(objs_, ARM, op.get("os") or G.os_le_plus_proche(ARM, c) or os_racine())



def peindre(op):
    """Colore une REGION d'une piece. La region = toutes les faces qui respectent TOUTES les regles donnees :
    "selon" (direction, defaut haut) + "de"/"a" (0 = bout bas de la piece, 1 = bout haut) ;
    "normales_vers" (direction) + "seuil" (0..1) ; "interieur": true (faces qui regardent une autre partie de l'objet : creux, bouche, dedans d'une boite) ;
    "pres_de": {"zone"|"point", "rayon"} ; "materiau": "<nom contenu>"."""
    import bmesh
    objs_ = cibles_op(op["quoi"])
    mat = G.materiau(f"mat_peint_{op['quoi']}_{len(RAPPORT)}", op["couleur"], op.get("emission", 0.0), op.get("alpha", 1.0), matiere_op(op))
    p_all = G.points_monde(objs_, 30000); centre = Vector(p_all.mean(0))
    sel = G.direction(op.get("selon", "haut"), REP); hh = p_all @ np.array(sel); h0, h1 = float(hh.min()), float(hh.max())
    nv = G.direction(op["normales_vers"], REP) if op.get("normales_vers") else None
    pres = None
    if op.get("pres_de"):
        pd = op["pres_de"]
        if isinstance(pd, str):
            pd = {"zone": pd}
        elif isinstance(pd, list):
            pd = {"point": pd}
        if "point" not in pd and zone_nom(pd.get("zone", "")) not in ZONES():
            raise SystemExit(f"pres_de : zone inconnue '{pd.get('zone')}'. Zones : {sorted(ZONES())}")
        pc = G.depuis_repere(pd["point"], REP) if "point" in pd else ZONES()[zone_nom(pd["zone"])]["point"]
        pres = (pc, L(pd.get("rayon", 0.1)))
    total = 0
    bvh_i = G.bvh_monde(objs_) if op.get("interieur") else None
    taille_ = float(np.ptp(p_all, 0).max())
    for o in G.maillages(objs_):
        M_ = o.matrix_world; N_ = M_.to_3x3().inverted().transposed()
        o.data.materials.append(mat); idx = len(o.data.materials) - 1
        for f in o.data.polygons:
            c = M_ @ f.center; n = (N_ @ f.normal).normalized()
            t = (c.dot(sel) - h0) / max(h1 - h0, 1e-9)
            if not (float(op.get("de", 0)) <= t <= float(op.get("a", 1))):
                continue
            if nv is not None and n.dot(nv) < float(op.get("seuil", 0.5)):
                continue
            if op.get("interieur"):
                # face INTERIEURE = elle regarde vers une autre partie de l'objet (cavite), pas vers le vide
                h = bvh_i.ray_cast(c + n * 0.001 * taille_, n, taille_ * 1.5)
                if h[0] is None or h[3] < float(op.get("profondeur_min", 0.15)) * taille_:
                    continue   # vide, ou simple petit creux de surface (moins de 15 % de la taille)
            if pres and (c - pres[0]).length > pres[1]:
                continue
            if op.get("materiau") and op["materiau"].lower() not in (o.data.materials[f.material_index].name.lower() if o.data.materials[f.material_index] else ""):
                continue
            f.material_index = idx; total += 1
    RAPPORT.append({"operation": "peindre", "quoi": op["quoi"], "faces": total})
    print(f"  peindre {op['quoi']} : {total} faces")
    if total == 0:
        ALERTES.append(f"peindre {op['quoi']} : aucune face ne respecte les regles (elargis-les)")


def ligne(nom):
    if nom in TUBES:
        return TUBES[nom]
    if nom in LIGNES:
        return LIGNES[nom]
    raise SystemExit(f"squelette : '{nom}' n'est pas un tube (chaines possibles : {sorted(set(TUBES) | set(LIGNES))})")


def creer_squelette(op):
    """Squelette automatique : une CHAINE d'os le long de chaque tube cite (corps, cou, queue, pattes, tentacules...).
    Chaque chaine s'accroche a l'os le plus proche des chaines deja creees. Puis 'peau' : chaque sommet suit les os
    proches (poids = inverse de la distance a la puissance 4, 3 os au plus) ; les pieces non fusionnees suivent l'os le plus proche."""
    squelette()
    for ch in op["chaines"]:
        nom_c = ch if isinstance(ch, str) else ch["tube"]
        n_os = 3 if isinstance(ch, str) else int(ch.get("os", 3))
        pts = ligne(nom_c)
        # re-echantillonnage regulier le long de la ligne
        seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]; tot = sum(seg)
        def a_dist(t):
            d = t * tot
            for i, l in enumerate(seg):
                if d <= l or i == len(seg) - 1:
                    return pts[i].lerp(pts[i + 1], min(1.0, d / max(l, 1e-9)))
                d -= l
        jalons = [a_dist(k / n_os) for k in range(n_os + 1)]
        # parent : l'os existant le plus proche du DEBUT de la chaine
        parent = G.os_le_plus_proche_tous(ARM, jalons[0]) or os_racine()
        for k in range(n_os):
            nb = f"{nom_c}_{k + 1}"
            ajouter_os(nb, jalons[k], jalons[k + 1], parent if k == 0 else f"{nom_c}_{k}")
        RAPPORT.append({"operation": "squelette", "chaine": nom_c, "os": n_os, "parent": parent})
    # peau
    os_ = [b for b in ARM.data.bones if b.name != os_racine() or len(ARM.data.bones) == 1]
    M = ARM.matrix_world
    segs = [(b.name, M @ b.head_local, M @ b.tail_local) for b in os_]
    peaux = op.get("peau") or [n for n in PIECES if PIECES[n] and PIECES[n][0].parent is None]
    for n in peaux:
        for o in PIECES.get(n, []):
            if o.type != "MESH":
                continue
            if op.get("rigides") and n in op["rigides"]:
                c = Vector(G.points_monde([o], 500).mean(0)); G.lier_os([o], ARM, G.os_le_plus_proche_tous(ARM, c)); continue
            Mo = o.matrix_world
            P_ = np.array([Mo @ v.co for v in o.data.vertices])
            D = np.empty((len(P_), len(segs)))
            for j, (_, a, b) in enumerate(segs):
                a, b = np.array(a), np.array(b); ab = b - a
                t = np.clip(((P_ - a) @ ab) / max(ab @ ab, 1e-12), 0, 1)
                D[:, j] = np.linalg.norm(P_ - (a + t[:, None] * ab), axis=1)
            W = 1.0 / (D + 1e-4 * H) ** 4
            idx = np.argsort(-W, axis=1)[:, :3]
            for j, (nb, _, _) in enumerate(segs):
                g = o.vertex_groups.get(nb) or o.vertex_groups.new(name=nb)
            for vi in range(len(P_)):
                w = W[vi, idx[vi]]; w = w / w.sum()
                for jj, ww in zip(idx[vi], w):
                    if ww > 0.01:
                        o.vertex_groups[segs[jj][0]].add([vi], float(ww), "REPLACE")
            m = o.modifiers.new("squelette", "ARMATURE"); m.object = ARM
            mw = o.matrix_world.copy(); o.parent = ARM; o.parent_type = "OBJECT"; o.matrix_world = mw
    bpy.context.view_layer.update()
    print(f"  squelette : {len(ARM.data.bones)} os ; peau calculee pour {', '.join(peaux)}")


def rotation_os(nom_os, pose):
    """Rotation d'un os exprimee dans le repere du SUJET (pas dans celui de l'os) :
    plier = autour de l'axe droite (lever/baisser), virer = autour du haut (gauche/droite), rouler = autour de l'os lui-meme.
    L'ordre plier -> virer -> rouler couvre TOUTES les rotations possibles."""
    b = ARM.data.bones[nom_os]
    Rl = (ARM.matrix_world.to_3x3() @ b.matrix_local.to_3x3())   # os -> monde (repos)
    q = Matrix.Identity(3).to_quaternion()
    def autour(axe_monde, deg):
        ax = (Rl.inverted() @ axe_monde).normalized()
        from mathutils import Quaternion
        return Quaternion(ax, math.radians(deg))
    if pose.get("plier"):
        q = autour(REP["r"], pose["plier"]) @ q
    if pose.get("virer"):
        q = autour(REP["u"], pose["virer"]) @ q
    if pose.get("rouler"):
        from mathutils import Quaternion
        q = Quaternion(Vector((0, 1, 0)), math.radians(pose["rouler"])) @ q
    if pose.get("ouvrir"):
        from mathutils import Quaternion
        q = Quaternion(Vector((0, 1, 0)), math.radians(pose["ouvrir"]) * b.get("usine_sens", 1)) @ q
    return q


def deformer(op):
    """Deformation douce d'une REGION de piece, mesuree le long d'un axe du sujet ('selon', defaut haut) :
    region = de 'de' a 'a' (0 = bout bas de la piece, 1 = bout haut), avec un fondu doux ('fondu').
    etirer (facteur de longueur), gonfler (facteur d'epaisseur), effiler (epaisseur au bout 'a'),
    plier (degres, vers 'vers'), tordre (degres autour de l'axe), decaler [droite, avant, haut] (fractions de H).
    Tout ce qui est au-dela de la region suit (pas de dechirure) : le deplacement est l'integrale du poids."""
    objs_ = cibles_op(op["quoi"])
    axe = G.direction(op.get("selon", "haut"), REP)
    p_all = G.points_monde(objs_, 40000); hh = p_all @ np.array(axe); h0, h1 = float(hh.min()), float(hh.max())
    de, a = float(op.get("de", 0.0)), float(op.get("a", 1.0)); fondu = float(op.get("fondu", 0.1))
    centre = Vector(p_all.mean(0))
    # poids w(t) et son integrale cumulee F(t) sur 400 niveaux
    T = np.linspace(-0.05, 1.05, 441)
    W = np.where(T < de, np.clip(1 - (de - T) / max(fondu, 1e-6), 0, 1), np.where(T > a, np.clip(1 - (T - a) / max(fondu, 1e-6), 0, 1), 1.0))
    W = W * W * (3 - 2 * W)
    F = np.concatenate([[0], np.cumsum((W[1:] + W[:-1]) / 2 * np.diff(T))])
    Ftot = max(F[-1], 1e-9)
    longueur = h1 - h0
    s0 = h0 + de * longueur
    vers = G.direction(op.get("vers", "avant"), REP); ax_pli = axe.cross(vers)
    ax_pli = ax_pli.normalized() if ax_pli.length > 1e-6 else REP["r"]
    k_e = float(op.get("etirer", 1.0)); k_g = float(op.get("gonfler", 1.0)); k_f = float(op.get("effiler", 1.0))
    off = (REP["r"] * op["decaler"][0] + REP["f"] * op["decaler"][1] + REP["u"] * op["decaler"][2]) * H if op.get("decaler") else Vector()
    for o in G.maillages(objs_):
        Mo = o.matrix_world; Mi = Mo.inverted()
        for v in o.data.vertices:
            p = Mo @ v.co; s_ = p.dot(axe); t = (s_ - h0) / max(longueur, 1e-9)
            w = float(np.interp(t, T, W)); f = float(np.interp(t, T, F)) / Ftot   # f : part de la region deja traversee
            base = centre + axe * (s_ - centre.dot(axe)); radial = p - base
            u_ = min(max((t - de) / max(a - de, 1e-9), 0.0), 1.0)
            radial = radial * (1 + (k_g - 1) * w) * (1 + (k_f - 1) * u_ * w)
            if op.get("tordre"):
                radial = Matrix.Rotation(math.radians(op["tordre"]) * f, 3, axe) @ radial
            # etirement : chaque niveau avance de (k - 1) x (integrale du poids jusqu'a lui)
            ds = (k_e - 1) * float(np.interp(t, T, F)) * longueur
            q = base + axe * ds + radial
            if op.get("plier"):
                piv = centre + axe * (s0 - centre.dot(axe))
                q = piv + Matrix.Rotation(math.radians(op["plier"]) * f, 3, ax_pli) @ (q - piv)
            q = q + off * w
            v.co = Mi @ q
        o.data.update()
    RAPPORT.append({"operation": "deformer", "quoi": op["quoi"], "region": [de, a]})



def symetriser(op):
    """Copie miroir d'une piece par le plan median du sujet (patte droite -> patte gauche). Nom : 'nom' ou <quoi>_sym."""
    nom = op["quoi"]; nv = op.get("nom", nom + "_sym")
    cop = G.miroir(PIECES[nom], REP, "_tmp")
    for o in cop:
        o.name = nv
    PIECES[nv] = cop
    n = REP["r"]; c = REP["centre"]
    Rm = Matrix.Identity(3) - 2 * Matrix(((n.x * n.x, n.x * n.y, n.x * n.z), (n.y * n.x, n.y * n.y, n.y * n.z), (n.z * n.x, n.z * n.y, n.z * n.z)))
    CADRES[nv] = Rm @ CADRES[nom]
    if nom in TUBES:
        TUBES[nv] = [c + Rm @ (p - c) for p in TUBES[nom]]


def resoudre_nom_os(n):
    """'main_d' (zone humaine), 'os:hand_r' ou 'hand_r' -> nom d'os."""
    if n in ARM.pose.bones:
        return n
    if n.startswith("os:") and n[3:] in ARM.pose.bones:
        return n[3:]
    Z = ZONES()
    if n in Z and Z[n].get("os"):
        return Z[n]["os"]
    raise SystemExit(f"os ou zone '{n}' inconnu. Zones : {sorted(k for k in Z if Z[k].get('os'))} ; os : {[b.name for b in ARM.pose.bones]}")


def profondeur_os(n):
    b = ARM.data.bones[n]; k = 0
    while b.parent:
        b = b.parent; k += 1
    return k


def viser(nom_os, cible_dir):
    """Tourne l'os (dans sa pose actuelle) pour qu'il pointe EXACTEMENT vers cible_dir (monde)."""
    pb = ARM.pose.bones[nom_os]
    Mw = ARM.matrix_world @ pb.matrix
    cur = (Mw.to_3x3() @ Vector((0, 1, 0))).normalized()
    qw = cur.rotation_difference(cible_dir.normalized())
    Rb = Mw.to_quaternion()
    pb.rotation_quaternion = pb.rotation_quaternion @ (Rb.inverted() @ qw @ Rb)
    bpy.context.view_layer.update()


def atteindre(nom_os, cible, coude_vers=None):
    """Cinematique inverse exacte a 2 os : le BOUT de l'os 'nom_os' touche le point cible (le parent plie au coude).
    cible : [droite, avant, haut] (fractions de H) ou {"zone": "..."} ; coude_vers : direction du coude (defaut : arriere)."""
    pb = ARM.pose.bones[nom_os]; par = pb.parent
    if par is None:
        raise SystemExit(f"atteindre : '{nom_os}' n'a pas d'os parent")
    if isinstance(cible, str):
        cible = {"zone": cible}
    if isinstance(cible, dict) and zone_nom(cible.get("zone", "")) not in ZONES():
        raise SystemExit(f"atteindre : zone inconnue '{cible.get('zone')}'. Zones : {sorted(ZONES())}")
    T = ZONES()[zone_nom(cible["zone"])]["point"] if isinstance(cible, dict) else G.depuis_repere(cible, REP)
    M = ARM.matrix_world
    A = M @ par.head
    l1 = (M @ par.tail - A).length; l2 = (M @ pb.tail - M @ pb.head).length
    d = min((T - A).length, (l1 + l2) * 0.999)
    u = (T - A).normalized()
    pole = G.direction(coude_vers, REP) if coude_vers else (M @ par.tail - A)
    v = pole - u * pole.dot(u)
    if v.length < 1e-6:
        v = REP["f"] - u * REP["f"].dot(u)
    v.normalize()
    ca = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
    K = A + l1 * (u * ca + v * math.sqrt(1 - ca * ca))
    viser(par.name, K - A)
    bpy.context.view_layer.update()
    viser(nom_os, (A + u * d) - (M @ pb.head))


ZONES_TRANSFERT = ["hanches", "ventre", "torse", "cou", "tete", "epaule_d", "epaule_g", "bras_d", "bras_g", "avant_bras_d",
                   "avant_bras_g", "main_d", "main_g", "cuisse_d", "cuisse_g", "jambe_d", "jambe_g", "pied_d", "pied_g"]


def reprendre(op):
    """Reprend une animation d'un AUTRE modele (squelette different) : pour chaque zone commune (bras, jambes...),
    l'os du modele pointe dans la meme direction que celui de la source (reperes des deux sujets alignes) ;
    le deplacement des hanches est mis a l'echelle des hauteurs. {"fichier", "action", "nom", "images"}."""
    squelette()
    figer_contraintes()          # avant l'import : seules les animations du modele sont concernees
    avant = set(bpy.data.objects); acts_avant = set(bpy.data.actions)
    nv = G.importer(op["fichier"])
    src_arm = G.squelette_principal(nv)
    if src_arm is None:
        raise SystemExit("reprendre : le fichier source n'a pas de squelette")
    src_arm.data.pose_position = "REST"; bpy.context.view_layer.update()
    rep_s = G.repere([o for o in nv if o.type == "MESH"], src_arm)
    Zs = G.zones([o for o in nv if o.type == "MESH"], src_arm, rep_s); Zt = ZONES()
    paires = [(z, Zs[z]["os"], Zt[z]["os"]) for z in ZONES_TRANSFERT if z in Zs and z in Zt and Zs[z]["os"] and Zt[z]["os"]]
    if len(paires) < 6:
        raise SystemExit(f"reprendre : trop peu de zones communes ({[p[0] for p in paires]}) : les deux modeles doivent etre humanoides")
    # l'action est cherchee parmi celles du fichier SOURCE (le modele peut avoir une action du meme nom)
    nouvelles = [a for a in bpy.data.actions if a not in acts_avant]
    act_s = trouver_action(op["action"], nouvelles)
    if act_s is None:
        raise SystemExit(f"reprendre : action '{op['action']}' introuvable. Actions : {sorted(a.name for a in bpy.data.actions)}")
    # rotation qui envoie le repere source sur le repere cible
    Ms = Matrix((tuple(rep_s["r"]), tuple(rep_s["f"]), tuple(rep_s["u"]))).transposed()
    Mt = Matrix((tuple(REP["r"]), tuple(REP["f"]), tuple(REP["u"]))).transposed()
    Rst = Mt @ Ms.inverted(); k_h = REP["H"] / rep_s["H"]
    # directions de repos (monde, repere cible) : choix os par os entre direction absolue et rotation relative
    REPOS_S = {bs: (Rst @ (src_arm.matrix_world.to_3x3() @ (src_arm.data.bones[bs].tail_local - src_arm.data.bones[bs].head_local))).normalized()
               for _, bs, _ in paires}
    REPOS_T = {bt: (ARM.matrix_world.to_3x3() @ (ARM.data.bones[bt].tail_local - ARM.data.bones[bt].head_local)).normalized()
               for _, _, bt in paires}
    ABSOLU = {bt: REPOS_S[bs].dot(REPOS_T[bt]) > 0.5 for _, bs, bt in paires}
    src_arm.animation_data_create(); src_arm.animation_data.use_nla = False; src_arm.animation_data.action = act_s
    choisir_slot(src_arm, act_s)
    src_arm.data.pose_position = "POSE"
    d0, d1 = act_s.frame_range; n_img = int(op.get("images", 12))
    nom = op["nom"]; act = bpy.data.actions.new(nom); act.use_fake_user = True
    ARM.animation_data_create(); ARM.animation_data.action = act; ARM.data.pose_position = "POSE"
    hs_os, ht_os = Zs["hanches"]["os"] if "hanches" in Zs else None, Zt["hanches"]["os"] if "hanches" in Zt else None
    bpy.context.scene.frame_set(int(d0)); bpy.context.view_layer.update()
    h0_s = (src_arm.matrix_world @ src_arm.pose.bones[hs_os].head) if hs_os else None
    for i in range(n_img + 1):
        f = d0 + (d1 - d0) * i / n_img
        bpy.context.scene.frame_set(int(math.floor(f)), subframe=f - math.floor(f)); bpy.context.view_layer.update()
        for pb in ARM.pose.bones:
            pb.rotation_mode = "QUATERNION"; pb.rotation_quaternion = (1, 0, 0, 0); pb.location = (0, 0, 0)
        bpy.context.view_layer.update()
        for z, bs, bt in sorted(paires, key=lambda p: profondeur_os(p[2])):
            ps = src_arm.pose.bones[bs]; Mw = src_arm.matrix_world @ ps.matrix
            ds = Rst @ (Mw.to_3x3() @ Vector((0, 1, 0))).normalized()
            if ABSOLU[bt]:      # os comparables (meme sens au repos) : meme direction que la source
                viser(bt, ds)
            else:               # conventions differentes : meme rotation PAR RAPPORT AU REPOS que la source
                viser(bt, REPOS_S[bs].rotation_difference(ds) @ REPOS_T[bt])
        # bout de membre qui n'est PAS l'enfant du segment precedent (poignee IK) : recolle au bout du segment
        for bout, seg in (("pied_d", "jambe_d"), ("pied_g", "jambe_g"), ("main_d", "avant_bras_d"), ("main_g", "avant_bras_g")):
            if bout in Zt and seg in Zt and Zt[bout]["os"] and Zt[seg]["os"]:
                bb, bsg = ARM.data.bones[Zt[bout]["os"]], ARM.data.bones[Zt[seg]["os"]]
                anc = bb.parent
                while anc is not None and anc != bsg:
                    anc = anc.parent
                if anc is None:
                    pbb = ARM.pose.bones[bb.name]; bout_seg = ARM.pose.bones[bsg.name].tail
                    Mx = pbb.matrix.copy(); Mx.translation = bout_seg; pbb.matrix = Mx
                    bpy.context.view_layer.update()
                    pbb.keyframe_insert("location", frame=1 + (f - d0))
        if hs_os and ht_os:  # deplacement des hanches (sauts, rebonds), a l'echelle du modele
            dh = (src_arm.matrix_world @ src_arm.pose.bones[hs_os].head) - h0_s
            dw = Rst @ dh * k_h
            pbt = ARM.pose.bones[ht_os]
            loc = ARM.data.bones[ht_os].matrix_local.to_3x3().inverted() @ (ARM.matrix_world.to_3x3().inverted() @ dw)
            pbt.location = loc; pbt.keyframe_insert("location", frame=1 + (f - d0))
        for z, bs, bt in paires:
            ARM.pose.bones[bt].keyframe_insert("rotation_quaternion", frame=1 + (f - d0))
    act.frame_range = (1, 1 + (d1 - d0))
    ARM.animation_data.action = None
    for pb in ARM.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0); pb.location = (0, 0, 0)
    ARM.data.pose_position = "REST"
    for o in [o for o in bpy.data.objects if o not in avant]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    ANIMS_CREES.append((nom, n_img, [{"t": 0.5, "os": {"x": {"atteindre": 1}}}]))
    d = dossier_modele(op["fichier"])
    if d:
        SOURCES.append(d)
    print(f"  animation '{nom}' reprise de '{act_s.name}' ({len(paires)} zones transferees, {n_img} images)")


def figer_contraintes():
    """Un squelette pilote par des contraintes (IK, cibles) ecraserait les poses donnees par l'usine :
    on 'fige' d'abord chaque animation existante en rotations simples (pose visuelle image par image),
    puis on retire les contraintes. Les animations d'origine gardent exactement le meme rendu."""
    if ARM is None or not any(pb.constraints for pb in ARM.pose.bones) or ARM.get("usine_fige"):
        return
    ARM.data.pose_position = "POSE"
    ARM.animation_data_create()
    noms_os = {b.name for b in ARM.data.bones}
    def a_moi(a):
        cs = [fc.data_path.split('"')[1] for fc in _courbes(a) if fc.data_path.startswith("pose.bones")]
        return cs and all(c in noms_os for c in cs)
    for act in [a for a in bpy.data.actions if a_moi(a)]:
        ARM.animation_data.use_nla = False; ARM.animation_data.action = act
        choisir_slot(ARM, act)
        d0, d1 = int(act.frame_range[0]), int(math.ceil(act.frame_range[1]))
        poses = []
        for f in range(d0, d1 + 1):
            bpy.context.scene.frame_set(f)
            poses.append({pb.name: pb.matrix.copy() for pb in ARM.pose.bones})
        nv = bpy.data.actions.new(act.name + "_fige"); nv.use_fake_user = True
        ARM.animation_data.action = nv
        cons = {pb.name: [(c, c.mute) for c in pb.constraints] for pb in ARM.pose.bones}
        for lst in cons.values():
            for c, _ in lst:
                c.mute = True
        for k, f in enumerate(range(d0, d1 + 1)):
            for pb in sorted(ARM.pose.bones, key=lambda p: profondeur_os(p.name)):
                pb.matrix = poses[k][pb.name]
                bpy.context.view_layer.update()
            for pb in ARM.pose.bones:
                pb.rotation_mode = "QUATERNION"
                pb.keyframe_insert("rotation_quaternion", frame=f); pb.keyframe_insert("location", frame=f)
                pb.keyframe_insert("scale", frame=f)
        for lst in cons.values():
            for c, m in lst:
                c.mute = m
        nom = act.name; bpy.data.actions.remove(act); nv.name = nom
    ARM.animation_data.action = None
    for pb in ARM.pose.bones:
        for c in list(pb.constraints):
            pb.constraints.remove(c)
        pb.rotation_mode = "QUATERNION"; pb.rotation_quaternion = (1, 0, 0, 0); pb.location = (0, 0, 0); pb.scale = (1, 1, 1)
    ARM["usine_fige"] = True
    ARM.data.pose_position = "REST"; bpy.context.view_layer.update()
    print("  squelette a contraintes : animations figees, contraintes retirees")


def _courbes(a):
    if hasattr(a, "fcurves") and len(a.fcurves):
        return list(a.fcurves)
    out = []
    for l in getattr(a, "layers", []):
        for st in l.strips:
            for cb in st.channelbags:
                out += list(cb.fcurves)
    return out


def tissu(op):
    """Rend une piece SOUPLE (cape, drapeau, jupe, voile, cheveux longs) : vraie simulation de tissu dans fabriquer.
    fixer : la region accrochee (comme peindre : "selon", "de", "a") ; elle suit l'os de la piece (fais d'abord poser/lier).
    sur : ce qu'elle ne doit pas traverser (defaut : le sujet). raideur (defaut 15), poids (defaut 0.3), finesse (subdivisions)."""
    objs_ = PIECES[op["quoi"]]
    for o in G.maillages(objs_):
        bm_ = __import__("bmesh").new(); bm_.from_mesh(o.data)
        if any(not e.is_boundary for e in bm_.edges) and all(not e.is_boundary for e in bm_.edges):
            ALERTES.append(f"tissu {op['quoi']} : piece fermee (epaisse) ; pour un tissu, cree la lame avec \"epaisseur\": 0")
        bm_.free()
    sel = G.direction(op.get("fixer", {}).get("selon", "haut"), REP)
    de, a = float(op.get("fixer", {}).get("de", 0.85)), float(op.get("fixer", {}).get("a", 1.0))
    for o in G.maillages(objs_):
        if len(o.data.vertices) < 400:  # assez de points pour plier
            m = o.modifiers.new("finesse", "SUBSURF"); m.subdivision_type = "SIMPLE"; m.levels = int(op.get("finesse", 3))
            P.appliquer(o)
        Mo = o.matrix_world
        h = np.array([(Mo @ v.co).dot(sel) for v in o.data.vertices]); h0, h1 = h.min(), h.max()
        g = o.vertex_groups.get("fixe") or o.vertex_groups.new(name="fixe")
        ids = [i for i, x in enumerate(h) if de <= (x - h0) / max(h1 - h0, 1e-9) <= a]
        g.add(ids, 1.0, "REPLACE")
        if not ids or len(ids) == len(h):
            ALERTES.append(f"tissu {op['quoi']} : {'aucun' if not ids else 'tous les'} point(s) accroche(s) -> regle \"fixer\" "
                           "(ex. {\"selon\": \"haut\", \"de\": 0.9, \"a\": 1})")
        # decolle le tissu du corps (sinon la collision l'expulse a la premiere image) : le long de la normale moyenne
        bvh_c = G.bvh_monde(objets_de(op.get("sur", "sujet")))
        if bvh_c is not None:
            ns = Vector()
            for v in list(o.data.vertices)[:: max(1, len(o.data.vertices) // 300)]:
                loc_, nor_, _, _ = bvh_c.find_nearest(Mo @ v.co)
                if nor_ is not None:
                    ns += nor_
            if ns.length > 0:
                o.matrix_world = Matrix.Translation(ns.normalized() * 0.012 * H) @ o.matrix_world
                bpy.context.view_layer.update()
        cl = o.modifiers.new("tissu", "CLOTH")
        cl.show_viewport = False; cl.show_render = False   # coupe pendant le modelage, reactive a l'enregistrement
        st = cl.settings
        st.vertex_group_mass = "fixe"; st.quality = 6
        st.mass = float(op.get("poids", 0.3)); st.tension_stiffness = st.compression_stiffness = float(op.get("raideur", 15))
        st.bending_stiffness = float(op.get("pliage", 0.5)); st.air_damping = float(op.get("air", 1.0))
        cl.collision_settings.use_collision = True; cl.collision_settings.distance_min = 0.003 * H
        cl.collision_settings.use_self_collision = False
        o["usine_tissu"] = True; o["usine_H"] = H
        RAPPORT.append({"operation": "tissu", "quoi": op["quoi"], "points_fixes": len(ids), "points": len(o.data.vertices)})
    for c in objets_de(op.get("sur", "sujet")):
        if not any(m.type == "COLLISION" for m in c.modifiers):
            c.modifiers.new("collision", "COLLISION")
            c.collision.thickness_outer = 0.004 * H

def _point(p, arm_lib):
    """[droite, avant, haut] en fractions de H, ou {"os": nom, "bout": "tete"|"queue", "decalage": [d, a, h]}."""
    if isinstance(p, dict):
        arm_lib = arm_lib or ARM   # une piece ajoutee se place sur le squelette du sujet
        if arm_lib is None or p["os"] not in arm_lib.data.bones:
            raise SystemExit(f"corps : os '{p.get('os')}' absent du squelette du gabarit")
        b = arm_lib.data.bones[p["os"]]; v = arm_lib.matrix_world @ (b.tail_local if p.get("bout") == "queue" else b.head_local)
        d = p.get("decalage", [0, 0, 0])
        v = v + (REP["r"] * d[0] + REP["f"] * d[1] + REP["u"] * d[2]) * H
        if p.get("ecarter"):  # eloigne le point de l'axe du corps, de cote (jambes qui ne se soudent pas)
            v = v + REP["r"] * (1 if (v - REP["bas"]).dot(REP["r"]) >= 0 else -1) * float(p["ecarter"]) * H
        return v
    d, a_, h = _nombres([p], 3, "corps : point [droite, avant, haut]")[0]
    return REP["bas"] + (REP["r"] * d + REP["f"] * a_ + REP["u"] * h) * H


def corps_op(op):
    """Construit une peau continue autour de lignes a epaisseurs, avec son squelette (voir LISEZMOI section 5)."""
    global ARM, REP, H
    nom = op.get("nom", "corps")
    if nom in PIECES:
        raise SystemExit(f"corps : la piece '{nom}' existe deja")
    if SUJET and ARM is not None and not op.get("piece"):
        raise SystemExit("corps : le sujet a deja un squelette (une \"base\") ; pour ajouter une forme, mets \"piece\": true")
    arm_lib = None
    if op.get("squelette_bibliotheque"):  # squelette d'une bibliotheque d'animations (les animations s'y branchent)
        f_ = os.path.join(GABARITS, op["squelette_bibliotheque"])
        avant = set(bpy.data.objects); bpy.ops.import_scene.gltf(filepath=f_)
        nv = [o for o in bpy.data.objects if o not in avant]
        for o in nv:
            if o.type != "ARMATURE":
                bpy.data.objects.remove(o, do_unlink=True)
        arm_lib = next(o for o in bpy.data.objects if o.type == "ARMATURE" and o not in avant)
        bpy.context.view_layer.update()
    if op.get("ramifier"):
        r_ = dict(op["ramifier"]); b_ = _point(r_.pop("depuis", [0, 0, 0]), arm_lib)
        haut_ = REP["u"] if "vers" not in r_ else G.direction(r_.pop("vers"), REP)
        r_.pop("vers", None)
        lignes = C.ramifier(b_, haut_, L(r_.pop("longueur", 0.45)), L(r_.pop("rayon", 0.05)), nom=nom, **r_)
    else:
        if not op.get("lignes"):
            raise SystemExit("corps : \"lignes\" (ou \"ramifier\", ou un \"gabarit\") obligatoire")
        lignes = []
        for k, l in enumerate(op["lignes"]):
            pts = [_point(p, arm_lib) for p in l["points"]]
            ry = l.get("rayons", 0.05); ry = ry if isinstance(ry, list) else [ry] * len(pts)
            if len(ry) != len(pts):
                raise SystemExit(f"corps : ligne {k + 1} : {len(pts)} points mais {len(ry)} rayons")
            fac = float((op.get("epaisseurs") or {}).get(l.get("famille", ""), 1.0)) * float(op.get("epaisseur", 1.0))
            lignes.append({"famille": l.get("famille", f"ligne{k}"), "nom": l.get("nom", l.get("famille", f"ligne{k}")), "parent": l.get("parent"),
                           "points": pts, "rayons": [L(x) * fac for x in ry]})
    o = C.peau(lignes, finesse=L(op.get("finesse", 0.011)), k_rayon=float(op.get("k_rayon", 1.5)),
               lissage=int(op.get("lisse", 3)), nom=nom)
    G.colorer([o], op.get("couleur", "#a0a0a0"), nom=f"mat_{nom}", matiere=matiere_op(op))
    PIECES[nom] = [o]
    if op.get("feuillage") and op.get("ramifier") and float(op["feuillage"].get("rayon", 0.09)) > 0:  # masses de feuilles au bout des branches (une seule surface)
        fo = op["feuillage"]; prof = max(len(l["nom"]) for l in lignes)
        bouts = [l for l in lignes if len(l["nom"]) >= prof - 1]
        import random as _r; rnd_ = _r.Random(int(op["ramifier"].get("graine", 1)))
        rf = L(fo.get("rayon", 0.09))
        masses = [{"famille": "feuilles", "points": [l["points"][-1] + Vector((rnd_.uniform(-1, 1), rnd_.uniform(-1, 1), rnd_.uniform(0, 1))) * rf * 0.4],
                   "rayons": [rf * rnd_.uniform(0.75, 1.2)]} for l in bouts]
        of = C.peau(masses, finesse=L(op.get("finesse", 0.011)), k_rayon=1.0, lissage=2, nom=nom + "_feuilles")
        G.colorer([of], fo.get("couleur", "#4f8a3a"), nom=f"mat_{nom}_feuilles", matiere=matiere_op(fo)); PIECES[nom + "_feuilles"] = [of]
    arm = arm_lib or (C.squelette_lignes(lignes, "squelette") if op.get("squelette", not op.get("ramifier") and not op.get("piece")) else None)
    if arm is not None and not op.get("piece"):
        C.lier_peau(o, arm, douceur=L(op.get("douceur", 0.02)), exclure=("index", "middle", "pinky", "ring_", "thumb", "leaf", "ik_"))
        ARM = arm
    if op.get("tenue"):
        if arm is None or op.get("piece"):
            raise SystemExit("corps : \"tenue\" demande un corps avec squelette (pas \"piece\")")
        mt_ = matiere_op({"matiere": op.get("matiere_tenue", "tissu")})   # vetements : tissu sauf avis contraire (armure : metal)
        C.vetir(o, op["tenue"], lambda c, k: G.materiau(f"mat_{nom}_tenue{k}", c, matiere=mt_))
    if op.get("piece") and ARM is not None and not op.get("ramifier"):  # piece posee sur un os : elle le suit
        os_ = next((p["os"] for l in op["lignes"] for p in l["points"] if isinstance(p, dict) and "os" in p), None)
        if os_:
            G.lier_os(PIECES[nom] + PIECES.get(nom + "_feuilles", []), ARM, os_)
    if not op.get("piece"):
        SUJET.append(o)
        REP = G.repere(SUJET, ARM); H = REP["H"]; _Z.clear()
    print(f"  corps '{nom}' : {len(lignes)} ligne(s), {len(o.data.vertices)} sommets" + (", squelette " + arm.name if arm else ""))


def relief(op):
    """Detail fin sur la surface d'une piece : 'bosses' (pierre, ecorce, peau rugueuse, muscles), 'plis' (manches,
    pantalon, cape : anneaux autour de l'axe 'selon'), 'stries' (bois, ecailles allongees : traits le long de 'selon').
    force : hauteur du relief (fraction de H, defaut 0.012) ; echelle : taille d'un motif (fraction de H, defaut 0.06).
    Ou : 'zones' (noms d'os : ["Arm", "Leg"] -> seulement la peau de ces os) ou region 'de'/'a' le long de 'selon'."""
    from mathutils import noise
    objs_ = cibles_op(op["quoi"]); genre = op.get("type", "bosses")
    if genre not in ("bosses", "plis", "stries"):
        raise SystemExit(f"relief : type inconnu '{genre}' (bosses, plis, stries)")
    force = L(float(op.get("force", 0.012))); ech = max(L(float(op.get("echelle", 0.06))), 1e-4)
    axe = G.direction(op.get("selon", "haut"), REP)
    p_all = G.points_monde(objs_, 20000); hh = p_all @ np.array(axe); h0, h1 = float(hh.min()), float(hh.max())
    de, a = float(op.get("de", 0.0)), float(op.get("a", 1.0)); fondu = max(float(op.get("fondu", 0.08)), 1e-6)
    zones = op.get("zones"); graine = Vector((float(op.get("graine", 0)) * 13.7, 0, 0)); n_mod = 0
    for o in G.maillages(objs_):
        me = o.data; Mo = o.matrix_world; Mi = Mo.inverted(); N3 = Mo.to_3x3().inverted().transposed()
        if zones:
            gz = [g.index for g in o.vertex_groups if any(z.lower() in g.name.lower() for z in zones)]
            if not gz:
                raise SystemExit(f"relief : aucune zone {zones} sur '{o.name}' (groupes : {[g.name for g in o.vertex_groups][:12]})")
        axe_os = {}   # plis / stries sur des zones : chaque zone suit SON os (bras tendu, jambe pliee)
        if zones and "selon" not in op and ARM is not None:
            for g in o.vertex_groups:
                if g.index in gz and g.name in ARM.data.bones:
                    b = ARM.data.bones[g.name]; Mw = ARM.matrix_world
                    axe_os[g.index] = ((Mw @ b.tail_local) - (Mw @ b.head_local)).normalized()
        for v in me.vertices:
            p = Mo @ v.co; t = (p.dot(axe) - h0) / max(h1 - h0, 1e-9)
            if zones:
                gs = [g for g in v.groups if g.group in gz]
                w = max([g.weight for g in gs] or [0.0])
                if gs and axe_os:
                    axe = axe_os.get(max(gs, key=lambda g: g.weight).group, axe)
            else:
                w = 1.0 if de <= t <= a else max(0.0, 1 - min(abs(t - de), abs(t - a)) / fondu)
            if w <= 0:
                continue
            q = p / ech + graine
            if genre == "bosses":
                d = noise.noise(q) + 0.5 * noise.noise(q * 2.1)
            elif genre == "plis":   # anneaux un peu ondules : vrais plis de tissu
                s = p.dot(axe) / ech + 0.8 * noise.noise(q * 0.5)
                d = abs(math.sin(math.pi * s)) * 1.6 - 0.8
            else:                   # stries le long de l'axe
                r_ = p - axe * p.dot(axe); s = (r_.length * math.atan2(r_.dot(REP["f"]), r_.dot(REP["r"]))) / ech
                d = (abs(math.sin(math.pi * (s + 0.6 * noise.noise(q * 0.3)))) * 1.6 - 0.8)
            nrm = (N3 @ v.normal).normalized()
            v.co = Mi @ (p + nrm * (force * w * d)); n_mod += 1
        me.update()
    if n_mod == 0:
        print(f"  ATTENTION : relief '{op['quoi']}' : aucune surface touchee (region de/a ou zones ?)")
    RAPPORT.append({"operation": "relief", "quoi": op["quoi"], "type": genre, "sommets": n_mod})


OPS = {"corps": corps_op, "piece": nouvelle_piece, "importer": importer_piece, "placer": placer, "poser": poser, "englober": englober,
       "couleur": couleur, "cacher": cacher, "fusionner": fusionner, "soustraire": soustraire, "intersecter": intersecter,
       "couper": couper, "charniere": charniere, "repartir": repartir, "animation": animation, "lier": lier, "peindre": peindre,
       "squelette": creer_squelette, "deformer": deformer, "symetriser": symetriser,
       "reprendre": reprendre, "tissu": tissu, "relief": relief}

for i, op in enumerate(M.get("operations", [])):
    f = op.get("faire")
    if f not in OPS:
        raise SystemExit(f"operation {i + 1} : 'faire' inconnu : {f}. Operations : {sorted(OPS)}")
    import difflib
    _connues = set("a action air alpha ancre arrondi avant_piece avant_vers axe bord bosses boucher chaines cles contact contour cote "
                   "couleur couleur_coupe de decaler dimensions duree_ms ecart effiler emission enfoncer epaisseur etirer faire fichier "
                   "finesse fixer fondu forme gonfler graine haut_piece haut_vers hauteur images incliner interieur le_long lier lisse "
                   "marge materiau matiere matiere_tenue nom replier segments anticipation nombre noms normale normales_vers ondes os outil ouvre_vers parent_os peau pliage plier poids "
                   "point points pres_de profil profondeur_min quoi raideur rayon rayons remplacer rigides selon seuil seulement sur "
                   "gabarit lignes ramifier epaisseur epaisseurs squelette squelette_bibliotheque piece k_rayon douceur feuillage tenue secondaire ajuster "
                   "symetrique taille tolerance tordre tourner vers zone type force echelle zones".split())
    for k_ in op:
        if not k_.startswith("_") and k_ not in _connues:
            pr_ = difflib.get_close_matches(k_, _connues, 1, 0.7)
            print(f"  ATTENTION : operation {i + 1} ({f}) : cle inconnue \"{k_}\" ignoree" + (f" -> veux-tu dire \"{pr_[0]}\" ?" if pr_ else ""))
    print(f"operation {i + 1} : {f} {op.get('quoi', op.get('nom', ''))}")
    try:
        OPS[f](op)
    except SystemExit as e:
        if str(e).startswith("operation "):
            raise
        raise SystemExit(f"operation {i + 1} ({f}) : ERREUR : {e}")
    except (ValueError, TypeError, IndexError, ZeroDivisionError, AttributeError, RuntimeError) as e:
        import traceback as _tb
        lieu = [f for f in _tb.extract_tb(e.__traceback__) if "usine" in f.filename][-1:]
        ou = f" [{os.path.basename(lieu[0].filename)}:{lieu[0].lineno}]" if lieu else ""
        raise SystemExit(f"operation {i + 1} ({f}) : ERREUR : valeurs de l'operation impossibles a traiter ({type(e).__name__} : "
                         f"{str(e)[:120]}){ou}. Verifie ses cles (LISEZMOI section 5) ; si elles sont justes, note-le dans BUGS_USINE.md.")
    except KeyError as e:
        k = e.args[0] if e.args else "?"
        if isinstance(k, str) and k not in op and k in ("quoi", "nom", "outil", "points", "contour", "fichier", "chaines", "a", "couleur"):
            raise SystemExit(f"operation {i + 1} ({f}) : ERREUR : cle obligatoire manquante : \"{k}\" (voir LISEZMOI section 5)")
        raise SystemExit(f"operation {i + 1} ({f}) : ERREUR : nom inconnu : '{k}'. Pieces : {sorted(PIECES)} ; "
                         f"objets : {sorted(o.name for o in bpy.data.objects if o.type == 'MESH')[:30]}"
                         + (f" ; os : {[b.name for b in ARM.data.bones][:40]}" if ARM else ""))
    _Z.clear() if (f in ("fusionner", "couper", "deformer", "soustraire", "intersecter") or not SUJET) else None

# toute piece libre suit l'os racine (sauts, deplacements du corps entier)
if ARM is not None:
    for o in [o for o in bpy.data.objects if o.type == "MESH" and G.visible(o) and o.parent is None
              and not any(m.type == "ARMATURE" for m in o.modifiers)]:
        G.lier_os([o], ARM, os_racine())

# ------------------------------------------------------------------ sorties
tout = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render and len(o.data.polygons)]
if not tout:
    raise SystemExit("ERREUR : rien a montrer : pas de \"base\" et aucune piece construite (ou tout est cache). "
                     "Ajoute des operations \"piece\" (section 5 du LISEZMOI).")
BVH = G.bvh_monde(tout)
ims = rendre_vues(tout, REP, 300, dossier=DOSSIER)
if AFF:  # essai d'affinage : une image (3/4 + cote + gros plan de la derniere piece touchee), rien n'est enregistre
    dos_ = os.path.join(DOSSIER, "affinage"); os.makedirs(dos_, exist_ok=True)
    v_ = rendre_vues(tout, REP, 260, vues=[("3/4", "avant-droite", 0.35), ("droite", "droite", 0.0)], dossier=dos_, numeros=False)
    cible_ = None
    for op in M.get("operations", []):
        if any(isinstance(x, (int, float, list)) and x == AFF_VAL.get("v") for x in op.values()):
            cible_ = op.get("quoi") or op.get("nom")
    if cible_ in PIECES:
        v_ += rendre_vues(tout, REP, 260, vues=[("3/4", "avant-droite", 0.35)], dossier=dos_, cadre=PIECES[cible_], numeros=False)
    ecrire_image(os.path.join(dos_, f"{AFF}.png"), np.concatenate(v_, 1))
    fv = os.path.join(dos_, "valeurs.json")
    vals = json.load(open(fv)) if os.path.exists(fv) else {}
    vals[str(AFF)] = AFF_VAL.get("v"); json.dump(vals, open(fv, "w"))
    print(f"AFFINAGE essai {AFF} : valeur {AFF_VAL.get('v')}")
    sys.exit(0)
# gros plans : chaque piece posee, de face et de son cote droit, cadree sur elle
_copies = {c: b for b, cs in REPARTIS.items() for c in cs}
_vus, GROS_PLANS, CADRE_GP = set(), [], {}
for n in PIECES:
    if n.endswith("_sym") or not any(o.type == "MESH" and len(o.data.polygons) and not o.hide_render for o in PIECES[n]):
        continue
    if n in _copies:  # toutes les copies d'un "repartir" : un seul gros plan qui les montre ensemble
        b = _copies[n]
        if b in _vus:
            continue
        _vus.add(b); GROS_PLANS.append(f"{b} (x{len(REPARTIS[b])})")
        CADRE_GP[GROS_PLANS[-1]] = [o for c in REPARTIS[b] if c in PIECES for o in PIECES[c]]
    else:
        GROS_PLANS.append(n); CADRE_GP[n] = PIECES[n]
GROS_PLANS = GROS_PLANS[:6]
for nom in GROS_PLANS:
    ims += rendre_vues(tout, REP, 300, vues=[("face", "avant", 0.0), ("droite", "droite", 0.0)], dossier=DOSSIER, cadre=CADRE_GP[nom])
# chaque animation creee : la pose ou la piece bouge le plus (ex. gueule grande ouverte), vue de 3/4 et de cote
for nom_a, n_img, cles in ANIMS_CREES:
    act = bpy.data.actions[nom_a]
    ARM.animation_data_create(); ARM.animation_data.action = act; ARM.data.pose_position = "POSE"
    def ampleur(c):
        return sum(sum(abs(v.get(k, 0)) for k in ("ouvrir", "plier", "virer", "rouler")) + 60 * ("atteindre" in v) + 5 * ("vers" in v)
                   for v in c.get("os", {}).values()) \
            + 100 * sum(abs(c.get("racine", {}).get(k, 0)) for k in ("haut", "avant", "droite"))
    cle = max(cles, key=ampleur)
    fr_ = act.frame_range[0] + float(cle["t"]) * (act.frame_range[1] - act.frame_range[0])
    bpy.context.scene.frame_set(int(fr_), subframe=fr_ - int(fr_))
    ims += rendre_vues(tout, REP, 300, vues=[("3/4", "avant-droite", 0.35), ("droite", "droite", 0.0)], dossier=DOSSIER)
    ARM.animation_data.action = None; ARM.data.pose_position = "REST"; bpy.context.scene.frame_set(1)
    for pb in ARM.pose.bones:
        pb.location = (0, 0, 0); pb.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
planche = os.path.join(DOSSIER, f"{ID}_modelage.png")
ecrire_image(planche, grille(ims, colonnes=4, case=(300, 300)))
ecrire_image(os.path.join(DOSSIER, "apercu.png"), grille(ims[:4], colonnes=4, case=(300, 300)))
# objets techniques (formes d'affichage des os, collections non rendues, objets caches) : retires du modele final
for a_ in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
    for pb in a_.pose.bones:
        if pb.custom_shape is not None:
            pb.custom_shape = None
for o in [o for o in bpy.data.objects if o.type == "MESH" and not G.visible(o)]:
    bpy.data.objects.remove(o, do_unlink=True)
for o in [o for o in bpy.data.objects if o.type == "MESH" and o.users == 0]:
    bpy.data.objects.remove(o, do_unlink=True)
cam = bpy.data.objects.get("_cam")
if cam:
    bpy.data.objects.remove(cam, do_unlink=True)
if ARM is not None:
    ARM.data.pose_position = "POSE"
# orientation STANDARD du modele enregistre : avant = -Y, haut = +Z, droite du sujet = -X, pose au sol au centre.
# (fabriquer et les directions de vue comptent la-dessus, quel que soit le modele de depart)
Rc = Matrix(((-1, 0, 0), (0, -1, 0), (0, 0, 1))) @ Matrix((tuple(REP["r"]), tuple(REP["f"]), tuple(REP["u"])))
p_ = G.points_monde([o for o in bpy.data.objects if o.type == "MESH" and G.visible(o)], 30000)
q_ = (p_ - np.array(REP["centre"])) @ np.array(Rc).T
dec = Vector((-(q_[:, 0].min() + q_[:, 0].max()) / 2, -(q_[:, 1].min() + q_[:, 1].max()) / 2, -q_[:, 2].min()))
Tc = Matrix.Translation(dec) @ Rc.to_4x4() @ Matrix.Translation(-REP["centre"])
for o in [o for o in bpy.data.objects if o.parent is None and o.type in ("MESH", "ARMATURE", "EMPTY", "CURVE")]:
    o.matrix_world = Tc @ o.matrix_world
bpy.context.view_layer.update()
for o in bpy.data.objects:  # tissu : la simulation est rallumee pour fabriquer
    for m in o.modifiers:
        if m.type == "CLOTH":
            m.show_viewport = True; m.show_render = True
sortie = os.path.join(DOSSIER, "source", f"{ID}.blend")
for img in bpy.data.images:  # TOUTES les textures dans le .blend (y compris les couleurs unies generees)
    if img.packed_file is None and img.size[0] > 0:
        try:
            img.pack()
        except Exception as e:
            print(f"  (texture {img.name} non integree : {e})")
bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(sortie), check_existing=False)

# provenance : celle de la base (et des pieces importees) ; les pieces construites sont CC0 (creees ici)
lic = os.path.join(DOSSIER, "licence.txt")
open(lic, "w").write(f"Modele {ID} : modelage par l'usine a assets (operations listees dans la recette).\n"
                     "Les pieces construites par l'usine sont dans le domaine public (CC0 1.0). Les modeles de base\n"
                     "gardent leur licence (voir sources_modelage dans provenance.json).\n")
autres = []
for d in SOURCES:
    pv = json.load(open(os.path.join(d, "provenance.json")))
    if os.path.abspath(d) != os.path.abspath(DOSSIER):
        autres.append(os.path.relpath(d))
base_pv = json.load(open(os.path.join(SOURCES[0], "provenance.json"))) if SOURCES else None
pv = dict(base_pv) if base_pv else {"id": ID, "type": "modele3d", "url": "https://github.com/Dari-Universer-Pub/KIT-OUTIL",
                                     "licence": "CC0", "auteur": "usine a assets (construction)", "fichier": sortie,
                                     "sha256": sha256(sortie), "page_licence": lic, "genere": True}
pv["modelage"] = {"recette": RECETTE, "operations": len(M.get("operations", [])), "fichier_modele": sortie}
pv["sources_modelage"] = autres
json.dump(pv, open(os.path.join(DOSSIER, "provenance.json"), "w"), indent=1, ensure_ascii=False)
json.dump({"repere": {"H_m": REP["H"], "symetrique": REP["symetrique"]}, "mesures": RAPPORT, "alertes": ALERTES},
          open(os.path.join(DOSSIER, f"{ID}_mesures_modelage.json"), "w"), indent=1, ensure_ascii=False)

R["modele"] = sortie.replace("\\", "/")
json.dump(R, open(RECETTE, "w"), indent=1, ensure_ascii=False)
if mode_kit():
    kit_iteration(ID, planche, f"modelage : {len(M.get('operations', []))} operations "
                               f"({', '.join(sorted({o.get('faire') for o in M.get('operations', [])}))})")
print(f"\nMODELE : {sortie}  (ecrit dans la recette, cle \"modele\")")
print(f"REGARDE : {planche}   (ligne 1 : face, cote droit, dos, 3/4 ; ensuite : gros plan de chaque piece, face + cote droit)")
for i, nom in enumerate(GROS_PLANS):
    print(f"   gros plan {i + 1} : {nom}")
for nom_a, _, _ in ANIMS_CREES:
    print(f"   animation '{nom_a}' : sa pose la plus forte (3/4 + cote), en fin de planche")
if ALERTES:
    print("ALERTES (a corriger dans \"modelage\", puis relance usine modeler) :")
    for a in ALERTES:
        print("  - " + a)
else:
    print("MESURES OK : aucune piece enfoncee ni flottante.")
print(f"Ensuite : usine variantes {RECETTE}  puis  usine fabriquer {RECETTE}")
