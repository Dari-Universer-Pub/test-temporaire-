"""Fonctions communes de l'usine a assets (tourne dans le Python de Blender : numpy inclus, pas de PIL)."""
import os, sys, json, re, math, subprocess, hashlib, urllib.parse
import numpy as np
import builtins as _builtins

# Windows : les fichiers texte (JSON, recettes) sont toujours lus/ecrits en UTF-8 (sinon cp1252 casse les accents)
_open_origine = _builtins.open
def _open_utf8(f, mode="r", *a, **k):
    if "b" not in mode and "encoding" not in k and not a:
        k["encoding"] = "utf-8"
    return _open_origine(f, mode, *a, **k)
_builtins.open = _open_utf8

ICI = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (usine-assets)"


def jeton_sketchfab():
    """Jeton Sketchfab OPTIONNEL : variable SKETCHFAB_TOKEN, sinon fichier usine_jetons.json du projet
    ({"sketchfab": "..."}), cherche dans le dossier courant puis ses parents. Sans jeton : Sketchfab ignore."""
    t = os.environ.get("SKETCHFAB_TOKEN", "").strip()
    if t:
        return t
    d = os.getcwd()
    for _ in range(4):
        p = os.path.join(d, "usine_jetons.json")
        if os.path.exists(p):
            try:
                t = str(json.load(open(p)).get("sketchfab", "")).strip()
            except Exception:
                t = ""
            if t and not t.startswith("COLLE"):
                return t
        d = os.path.dirname(d)
    return None


def http(url, sortie=None, data=None, jar=None, timeout=180, essais=3):
    """curl : marche partout (proxy, certificats systeme). Renvoie le texte, ou ecrit un fichier."""
    cache = os.environ.get("USINE_CACHE_HTTP")  # TESTS SEULEMENT : rejoue les reponses deja recues (dossier)
    cp = None
    if cache and data is None and jar is None:
        cp = os.path.join(cache, hashlib.sha1(url.encode()).hexdigest())
        if os.path.exists(cp):
            if sortie:
                shutil.copyfile(cp, sortie); return None
            return open(cp, encoding="utf-8", errors="replace").read()
        os.makedirs(cache, exist_ok=True)
    cmd = ["curl", "-sSLf", "--connect-timeout", str(min(30, timeout)), "--retry", str(max(0, essais - 1)), "--max-time", str(timeout), "-A", UA]
    if jar:
        cmd += ["-c", jar, "-b", jar]
    if data is not None:
        cmd += ["-X", "POST"]
        for k, v in data.items():
            cmd += ["--data-urlencode", f"{k}={v}"]
    if sortie:
        cmd += ["-o", sortie]
    tok = jeton_sketchfab() if "api.sketchfab.com" in url else None
    if tok:
        cmd += ["-H", f"Authorization: Token {tok}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        if sortie and os.path.exists(sortie):
            os.remove(sortie)  # jamais de fichier a moitie telecharge ou de page d'erreur gardee en cache
        raise RuntimeError(f"telechargement impossible : {url} ({r.stderr.decode(errors='replace')[:200]})")
    if cp:
        if sortie:
            shutil.copyfile(sortie, cp)
        else:
            open(cp, "wb").write(r.stdout)
    return None if sortie else r.stdout.decode("utf-8", errors="replace")


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def slug(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s.lower()).strip("_")
    return s[:48] or "x"


# ----------------------------------------------------------- images (bpy)
def lire_image(p):
    import bpy
    im = bpy.data.images.load(p)
    w, h = im.size
    a = np.array(im.pixels[:]).reshape(h, w, im.channels)[::-1]
    if im.channels == 3:
        a = np.concatenate([a, np.ones((h, w, 1))], -1)
    bpy.data.images.remove(im)
    return a


def ecrire_image(p, a):
    import bpy
    h, w = a.shape[:2]
    if a.shape[2] == 3:
        a = np.concatenate([a, np.ones((h, w, 1))], -1)
    im = bpy.data.images.new("tmp", w, h, alpha=True)
    im.pixels.foreach_set(np.ascontiguousarray(a[::-1]).astype(np.float32).ravel())
    im.filepath_raw = p
    im.file_format = "PNG"
    im.save()
    bpy.data.images.remove(im)


def redimensionner(a, w, h):
    """Reduction/agrandissement simple (moyenne par blocs approchee, sans PIL)."""
    H, W = a.shape[:2]
    ys = (np.arange(h) * H / h).astype(int)
    xs = (np.arange(w) * W / w).astype(int)
    return a[ys][:, xs]


def ajuster(a, w, h, fond=(0.92, 0.92, 0.92)):
    """Fait tenir l'image dans w x h en gardant les proportions, sur fond uni."""
    H, W = a.shape[:2]
    k = min(w / W, h / H)
    nw, nh = max(1, int(W * k)), max(1, int(H * k))
    b = redimensionner(a, nw, nh)
    out = np.ones((h, w, 4))
    out[..., :3] = fond
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    al = b[..., 3:4]
    out[y0:y0 + nh, x0:x0 + nw, :3] = out[y0:y0 + nh, x0:x0 + nw, :3] * (1 - al) + b[..., :3] * al
    return out


# chiffres 5x7 pour numeroter les planches (texte d'interface, pas un asset)
_CH = {"0": "01110100011001110101110011000101110", "1": "00100011000010000100001000010001110",
       "2": "01110100010000100010001000100011111", "3": "11110000010000101110000010000111110",
       "4": "00010001100101010010111110001000010", "5": "11111100001111000001000011000101110",
       "6": "00110010001000011110100011000101110", "7": "11111000010001000100010000100001000",
       "8": "01110100011000101110100011000101110", "9": "01110100011000101111000010001001100"}


def numeroter(a, n, k=4, couleur=(1, 1, 1), fond=(0.05, 0.05, 0.08)):
    s = str(n)
    w = (6 * len(s) + 1) * k
    a[:9 * k, :w, :3] = fond
    for i, c in enumerate(s):
        bits = _CH[c]
        for y in range(7):
            for x in range(5):
                if bits[y * 5 + x] == "1":
                    a[(1 + y) * k:(2 + y) * k, (1 + i * 6 + x) * k:(2 + i * 6 + x) * k, :3] = couleur
    return a


def grille(images, colonnes=5, case=(256, 256), marge=8):
    lignes = []
    for i in range(0, len(images), colonnes):
        rang = images[i:i + colonnes]
        rang += [np.ones((case[1], case[0], 4))] * (colonnes - len(rang))
        sep = np.ones((case[1], marge, 4))
        lignes.append(np.concatenate(sum([[im, sep] for im in rang], [])[:-1], 1))
        lignes.append(np.ones((marge, lignes[-1].shape[1], 4)))
    return np.concatenate(lignes[:-1], 0)


def reparer_textures(dossier):
    """Relie les images introuvables (chemins de l'auteur, ex. C:\\Users\\...) aux fichiers du dossier du modele."""
    import bpy
    index = {}
    for racine, _, fichiers in os.walk(dossier):
        for f in fichiers:
            index.setdefault(f.lower(), os.path.join(racine, f))
    reparees = 0
    for im in bpy.data.images:
        if im.source != "FILE" or im.packed_file:
            continue
        p = bpy.path.abspath(im.filepath)
        if os.path.exists(p):
            continue
        nom = re.split(r"[\\/]", im.filepath)[-1].lower()
        cand = index.get(nom) or next((v for k, v in index.items()
                                       if os.path.splitext(k)[0] == os.path.splitext(nom)[0] and k.endswith((".png", ".jpg", ".jpeg", ".tga"))), None)
        if not cand:  # nom approche : nom du materiau qui utilise l'image, puis mots communs (leaf ~ leaves)
            mats = [m.name.lower() for m in bpy.data.materials if m.use_nodes and
                    any(n.type == "TEX_IMAGE" and n.image == im for n in m.node_tree.nodes)]
            def mots_(x): return {w[:4] for w in re.split(r"[^a-z0-9]+", os.path.splitext(x)[0].lower()) if len(w) >= 3}
            cible = mots_(nom) | set().union(*[mots_(m) for m in mats]) if mats else mots_(nom)
            meilleur, sc = None, 0
            for k, v in index.items():
                if not k.endswith((".png", ".jpg", ".jpeg", ".tga")) or "variation" in v.lower():
                    continue
                if mats and os.path.splitext(k)[0] in mats:
                    meilleur, sc = v, 99; break
                s_ = len(mots_(k) & cible) - 0.1 * len(mots_(k) - cible)
                if s_ > sc:
                    meilleur, sc = v, s_
            cand = meilleur if sc >= 0.9 else None
        if cand:
            im.filepath = os.path.abspath(cand); im.reload(); reparees += 1
    # materiaux sans texture alors qu'une image du dossier porte leur nom (conversion d'anciens formats)
    images_dossier = {os.path.splitext(k)[0]: v for k, v in index.items()
                      if k.endswith((".png", ".jpg", ".jpeg", ".tga")) and not re.search(r"(normal|rough|metal|_ao|spec|bump|height|_nrm|_n\.)", k)}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.data.uv_layers:
            continue
        for m in o.data.materials:
            if not m or (m.use_nodes and any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes)):
                continue
            cand = images_dossier.get(m.name.lower()) or images_dossier.get(o.name.lower())
            if not cand and len(images_dossier) == 1:
                cand = next(iter(images_dossier.values()))
            if not cand:
                continue
            m.use_nodes = True
            nt = m.node_tree
            bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None) or nt.nodes.new("ShaderNodeBsdfPrincipled")
            sortie = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or nt.nodes.new("ShaderNodeOutputMaterial")
            if not sortie.inputs["Surface"].links:
                nt.links.new(bsdf.outputs[0], sortie.inputs["Surface"])
            tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(cand, check_existing=True)
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            reparees += 1
    return reparees


def saturation_moyenne(a):
    m = a[..., 3] > 0.5
    if not m.any():
        return 0.0
    c = a[m][:, :3]; mx = c.max(1); mn = c.min(1)
    return float(np.mean(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)))


def synchroniser_couleurs():
    """Workbench affiche material.diffuse_color : on y recopie la vraie couleur (Principled / Diffuse) des
    materiaux sans texture. Sans ca, beaucoup de modeles (Quaternius, Kenney...) sortent gris."""
    import bpy
    n = 0
    for m in bpy.data.materials:
        if not m.use_nodes:
            continue
        nt = m.node_tree
        if any(nd.type == "TEX_IMAGE" and nd.image for nd in nt.nodes):
            continue
        # le shader REELLEMENT branche sur la sortie active (un fichier peut contenir plusieurs sorties et shaders)
        sh_actif, _e = _sortie_couleur(m)
        candidats = ([sh_actif] if sh_actif is not None else []) + [nd for nd in nt.nodes if nd is not sh_actif]
        for nd in candidats:
            if nd.type in ("BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION"):
                entree = nd.inputs.get("Base Color") or nd.inputs.get("Color")
                if entree is not None and not entree.links:
                    lin = tuple(entree.default_value)
                    m.diffuse_color = lin
                    # petite texture unie de cette couleur : le mode TEXTURE marche alors pour tous les materiaux
                    srgb = [c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055 for c in lin[:3]]
                    img = bpy.data.images.new(f"uni_{m.name}", 4, 4)
                    img.pixels.foreach_set([*srgb, 1.0] * 16)
                    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = img
                    tex.name = "usine_couleur_unie"
                    nt.nodes.active = tex
                    n += 1
                    break
    try:
        n += cuire_materiaux()
    except Exception as e:  # la cuisson est un plus : jamais bloquante
        print(f"  (cuisson des couleurs impossible : {str(e)[:150]})")
    return n


def montrer_si_tout_cache(objets):
    """Certains fichiers marquent le corps lui-meme 'non rendu' (icone appareil photo coupee) alors qu'il est visible
    dans Blender. Si AUCUN maillage n'est rendu, on rend ceux qui sont visibles a l'ecran (sauf formes d'os)."""
    import bpy
    ms = [o for o in objets if o.type == "MESH" and o.name in bpy.data.objects]
    formes = {pb.custom_shape for a in bpy.data.objects if a.type == "ARMATURE" and a.pose for pb in a.pose.bones if pb.custom_shape}
    def rendu(o):
        return not o.hide_render and not any(c.hide_render for c in o.users_collection)
    if ms and not any(rendu(o) for o in ms if o not in formes):
        for o in ms:
            if o not in formes and not o.hide_viewport and len(o.data.polygons):
                o.hide_render = False
                for c in o.users_collection:
                    c.hide_render = False
        print("  (le fichier marquait tous ses maillages 'non rendus' : ils sont rendus quand meme)")


def _sortie_couleur(m):
    """(noeud BSDF/emission branche sur la sortie, son entree de couleur) ou (None, None)."""
    nt = m.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or \
        next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs["Surface"].links:
        return None, None
    sh = out.inputs["Surface"].links[0].from_node
    for _ in range(4):  # traverse les melanges de shaders (mix, add) : on prend le premier shader colore
        if sh.type in ("MIX_SHADER", "ADD_SHADER"):
            suiv = [l.from_node for i in sh.inputs if i.type == "SHADER" for l in i.links]
            if not suiv:
                return None, None
            sh = suiv[-1]
    e = sh.inputs.get("Base Color") or sh.inputs.get("Color")
    return (sh, e) if e is not None else (None, None)


def _couleurs_sommets_utiles(o):
    """La couche de couleurs de sommets d'un objet si elle porte de vraies couleurs (pas tout blanc, pas uni gris)."""
    if not o.data.color_attributes:
        return None
    a = o.data.color_attributes.active_color or o.data.color_attributes[0]
    n = len(a.data)
    if n == 0:
        return None
    v = np.empty(n * 4, dtype=np.float32); a.data.foreach_get("color", v); v = v.reshape(-1, 4)[:, :3]
    sat = (v.max(1) - v.min(1)).mean()
    if v.min() > 0.97 or (sat < 0.04 and v.std() < 0.02):
        return None
    return a.name


def _deplier(o):
    """Nouvelle couche UV sans chevauchement (Smart UV Project) ; repli : une case par face, en grille."""
    import bpy
    vl = bpy.context.view_layer
    for x in bpy.context.selected_objects:
        x.select_set(False)
    anc = (o.hide_viewport, o.hide_get() if o.name in vl.objects else False, o.hide_select)
    try:
        o.hide_viewport = False; o.hide_select = False
        if o.name not in vl.objects:
            bpy.context.scene.collection.objects.link(o)
        o.hide_set(False); o.select_set(True); vl.objects.active = o
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.004)
        bpy.ops.object.mode_set(mode="OBJECT")
        return
    except Exception as e:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
        print(f"  (depliage auto indisponible ({str(e)[:80]}) : depliage en grille)")
    finally:
        o.hide_viewport, o.hide_select = anc[0], anc[2]
    me = o.data; uv = me.uv_layers.active.data
    n = len(me.polygons); g = int(math.ceil(math.sqrt(n))); c = 1.0 / g; m = c * 0.12
    co = np.array([v.co[:] for v in me.vertices])
    for k, p in enumerate(me.polygons):
        nrm = np.array(p.normal[:]); a = np.cross(nrm, [0, 0, 1] if abs(nrm[2]) < 0.9 else [1, 0, 0]); a /= np.linalg.norm(a) + 1e-12
        b = np.cross(nrm, a); pts = co[[me.loops[l].vertex_index for l in p.loop_indices]]
        q = np.stack([pts @ a, pts @ b], 1); q -= q.min(0); q /= max(q.max(), 1e-12)
        x0, y0 = (k % g) * c + m, (k // g) * c + m
        for l, (u, v) in zip(p.loop_indices, q):
            uv[l].uv = (x0 + u * (c - 2 * m), y0 + v * (c - 2 * m))


def cuire_materiaux():
    """Le rendu pixel (Workbench) n'affiche qu'UNE image par materiau. Couleurs de sommets, textures procedurales,
    melanges (texture x couleur...) sortent alors gris ou faux. On 'cuit' la vraie couleur de base de ces objets dans
    une texture neuve (Cycles, une passe) et on la branche simplement. Modeles low poly a couleurs de sommets,
    packs a 'trim sheet' (Quaternius...), fichiers .blend proceduraux : tous rendus avec leurs vraies couleurs."""
    import bpy
    a_cuire = []
    for o in bpy.data.objects:
        if o.type != "MESH" or not len(o.data.polygons) or o.get("usine_cuit") or not o.data.materials:
            continue
        if len(o.data.polygons) > 150000:  # maillage geant (scan) : la cuisson prendrait des minutes
            continue
        vc = _couleurs_sommets_utiles(o)
        besoin = False
        for m in o.data.materials:
            if not m or not m.use_nodes:
                continue
            sh, e = _sortie_couleur(m)
            if e is None:
                continue
            src = e.links[0].from_node if e.links else None
            if src is not None and src.type != "TEX_IMAGE":
                besoin = True  # melange, couleurs de sommets branchees, procedural, courbes de couleur...
            elif vc and not any(n.type in ("VERTEX_COLOR", "ATTRIBUTE") for n in m.node_tree.nodes):
                besoin = True  # couleurs de sommets non branchees (FBX, OBJ etendu) : la couleur EST la, on la multiplie
        if besoin:
            a_cuire.append((o, vc))
    if not a_cuire:
        return 0
    sc = bpy.context.scene
    anc = (sc.render.engine,)
    sc.render.engine = "CYCLES"; sc.cycles.samples = 1; sc.cycles.device = "CPU"
    try:
        sc.cycles.use_denoising = False
    except Exception:
        pass
    sc.render.bake.margin = 4
    n = 0
    for o, vc in a_cuire:
        # materiaux propres a cet objet (une seule texture cuite pour tous ses materiaux)
        for i, m in enumerate(o.data.materials):
            if m and m.users > 1:
                o.data.materials[i] = m.copy()
        if o.data.users > 1:
            o.data = o.data.copy()
        uv_av = o.data.uv_layers.active.name if o.data.uv_layers.active else None
        uv = o.data.uv_layers.new(name="usine_cuisson")
        if uv is None:  # 8 couches UV deja : on remplace la derniere
            o.data.uv_layers.remove(o.data.uv_layers[-1]); uv = o.data.uv_layers.new(name="usine_cuisson")
        o.data.uv_layers.active = uv
        _deplier(o)
        cote = 256 if len(o.data.polygons) < 400 else (512 if len(o.data.polygons) < 4000 else 1024)
        img = bpy.data.images.new(f"cuit_{o.name}", cote, cote)
        restaurer = []
        for m in o.data.materials:
            if not m:
                continue
            if not m.use_nodes:
                m.use_nodes = True
            nt = m.node_tree
            sh, e = _sortie_couleur(m)
            out = next((x for x in nt.nodes if x.type == "OUTPUT_MATERIAL" and x.is_active_output), None) or \
                next((x for x in nt.nodes if x.type == "OUTPUT_MATERIAL"), None) or nt.nodes.new("ShaderNodeOutputMaterial")
            em = nt.nodes.new("ShaderNodeEmission")
            # couleur de base : ce qui est branche, sinon la valeur (ou la couleur d'affichage)
            if e is not None and e.links:
                coul = e.links[0].from_socket
            else:
                rgb = nt.nodes.new("ShaderNodeRGB")
                rgb.outputs[0].default_value = tuple(e.default_value) if e is not None else tuple(m.diffuse_color)
                coul = rgb.outputs[0]
            uvn = None
            for x in nt.nodes:  # les textures d'origine lisent l'ANCIENNE couche UV (la nouvelle est active)
                if x.type in ("TEX_IMAGE", "NORMAL_MAP") and hasattr(x, "inputs") and "Vector" in x.inputs and not x.inputs["Vector"].links and uv_av:
                    if uvn is None:
                        uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = uv_av
                    nt.links.new(uvn.outputs[0], x.inputs["Vector"])
            if vc and not any(x.type in ("VERTEX_COLOR", "ATTRIBUTE") for x in nt.nodes):
                at = nt.nodes.new("ShaderNodeVertexColor"); at.layer_name = vc
                mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
                mix.inputs["Factor"].default_value = 1.0
                nt.links.new(coul, mix.inputs[6]); nt.links.new(at.outputs["Color"], mix.inputs[7])
                coul = mix.outputs[2]
            nt.links.new(coul, em.inputs["Color"])
            anc_surf = out.inputs["Surface"].links[0].from_socket if out.inputs["Surface"].links else None
            nt.links.new(em.outputs[0], out.inputs["Surface"])
            cible = nt.nodes.new("ShaderNodeTexImage"); cible.image = img
            nt.nodes.active = cible
            restaurer.append((m, sh, e, out, anc_surf, em, cible))
        with bpy.context.temp_override(active_object=o, object=o, selected_objects=[o], selected_editable_objects=[o]):
            bpy.ops.object.bake(type="EMIT", use_clear=True, margin=4)
        img.pack()
        for m, sh, e, out, anc_surf, em, cible in restaurer:
            nt = m.node_tree
            nt.nodes.remove(em)
            if anc_surf is not None:
                nt.links.new(anc_surf, out.inputs["Surface"])
            uvc = nt.nodes.new("ShaderNodeUVMap"); uvc.uv_map = "usine_cuisson"
            nt.links.new(uvc.outputs[0], cible.inputs["Vector"])
            if e is not None:
                for l in list(e.links):
                    nt.links.remove(l)
                nt.links.new(cible.outputs["Color"], e)
            for x in nt.nodes:  # Workbench lit la texture ACTIVE : seule la texture cuite reste candidate
                if x.type == "TEX_IMAGE" and x is not cible and x.name == "usine_couleur_unie":
                    x.image = None
            nt.nodes.active = cible
        o.data.uv_layers.active = o.data.uv_layers["usine_cuisson"]
        o.data.uv_layers["usine_cuisson"].active_render = True
        o["usine_cuit"] = True
        n += 1
    sc.render.engine = anc[0]
    print(f"  couleurs cuites en texture : {n} objet(s) (couleurs de sommets / materiaux composes)")
    return n


# ------------------------------------------------------------ accessoires
SYNONYMES_OS = {"tete": ["head", "tete", "skull"], "cou": ["neck"], "main_droite": ["hand_r", "hand.r", "righthand", "r_hand", "hand_right"],
                "main_gauche": ["hand_l", "hand.l", "lefthand", "l_hand", "hand_left"], "main": ["hand"],
                "dos": ["spine2", "spine_03", "chest", "spine1", "spine"], "torse": ["chest", "spine2", "spine"],
                "hanches": ["hips", "pelvis"], "pied": ["foot"]}


def hex_rgb(h):
    """'#rrggbb', 'rrggbb' ou '#rgb' -> (r, g, b) de 0 a 1 ; message clair sinon."""
    t = str(h).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", t):
        t = "".join(c * 2 for c in t)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", t):
        raise SystemExit(f"ERREUR : couleur invalide : '{h}' (format attendu : \"#rrggbb\", ex. \"#c02020\")")
    return tuple(int(t[i:i + 2], 16) / 255 for i in (0, 2, 4))


def lire_recette(chemin):
    """Lit une recette JSON ; en cas d'erreur, dit OU (ligne, colonne) et quoi faire."""
    if not os.path.isfile(chemin):
        raise SystemExit(f"ERREUR : recette introuvable : {chemin}")
    txt = open(chemin, encoding="utf-8-sig").read()
    try:
        R = json.loads(txt)
    except json.JSONDecodeError as e:
        ligne = txt.splitlines()[e.lineno - 1] if 0 < e.lineno <= len(txt.splitlines()) else ""
        raise SystemExit(f"ERREUR : recette {chemin} illisible (JSON) ligne {e.lineno}, colonne {e.colno} : {e.msg}\n"
                         f"   {ligne.strip()[:120]}\n   (virgule en trop ou manquante, guillemets droits \"...\", pas de commentaire)")
    if not isinstance(R, dict) or not R.get("id"):
        raise SystemExit(f"ERREUR : recette {chemin} : la cle \"id\" (nom de l'asset) est obligatoire")
    if not isinstance(R["id"], str) or re.search(r'[/\\:*?"<>|]', R["id"]) or R["id"].strip(" .") != R["id"]:
        raise SystemExit(f"ERREUR : \"id\" invalide : '{R['id']}' (il sert de nom de dossier et de fichier : pas de / \\ : * ? \" < > |, "
                         "ni espace ou point au debut ou a la fin ; ex. \"epee_de_feu\")")
    return R


VUES_CONNUES = ("cote", "cote_droite", "cote_gauche", "face", "dos", "dessus", "rpg", "rpg_bas", "iso", "iso_gauche", "trois_quarts")
PROCEDURAUX = ("onde", "pulsation", "balancement", "rebond", "rotation", "flottement", "respiration")


def verifier_recette_fabriquer(R):
    """Erreurs de recette detectees AVANT le rendu (message clair au lieu d'un plantage au milieu)."""
    err = []
    if not R.get("modele"):
        err.append("cle \"modele\" manquante : le fichier 3D (apres usine obtenir : modeles/<id>/source/<fichier> ; apres usine modeler : ecrite toute seule)")
    v = R.get("vue", "cote")
    if isinstance(v, str) and v not in VUES_CONNUES:
        err.append(f"vue inconnue : '{v}'. Vues : {', '.join(VUES_CONNUES)} (ou [azimut, elevation] en degres)")
    if not isinstance(v, str) and not (isinstance(v, list) and len(v) == 2):
        err.append("vue : un nom ou [azimut, elevation]")
    try:
        if int(R.get("directions", 1)) not in (1, 2, 4, 8):
            err.append("directions : 1, 2, 4 ou 8")
    except (TypeError, ValueError):
        err.append("directions : 1, 2, 4 ou 8")
    try:
        t = int(R.get("taille_px", 32))
        if not 4 <= t <= 512:
            err.append("taille_px : entre 4 et 512")
    except (TypeError, ValueError):
        err.append("taille_px : un nombre (ex. 32)")
    an = R.get("animations") or {}
    if not isinstance(an, dict):
        err.append("animations : {\"nom\": {\"action\": ..., \"images\": 8}, ...}")
        an = {}
    for k, sp in an.items():
        if not str(k).strip() or re.search(r'[/\\:*?"<>|]', str(k)):
            err.append(f"nom d'animation invalide : '{k}' (il devient un nom de fichier : lettres, chiffres, _)")
        if not isinstance(sp, dict):
            err.append(f"animation '{k}' : un objet {{...}} attendu"); continue
        try:
            if int(sp.get("images", 8)) < 1:
                err.append(f"animation '{k}' : images >= 1")
        except (TypeError, ValueError):
            err.append(f"animation '{k}' : images = un nombre")
        if sp.get("procedural") and sp["procedural"] not in PROCEDURAUX:
            err.append(f"animation '{k}' : procedural '{sp['procedural']}' inconnu. Choix : {', '.join(PROCEDURAUX)}")
        if sp.get("action") and sp.get("procedural"):
            err.append(f"animation '{k}' : 'action' OU 'procedural', pas les deux")
    _rt = R.get("retouches") if isinstance(R.get("retouches"), list) else []
    _px = [px[2] for rt in _rt if isinstance(rt, dict) and isinstance(rt.get("pixels"), list) for px in rt["pixels"]
           if isinstance(px, (list, tuple)) and len(px) == 3 and px[2] != "transparent"]
    for c in list((R.get("couleurs") if isinstance(R.get("couleurs"), dict) else {}).values()) + _px:
        try:
            hex_rgb(c)
        except SystemExit as e:
            err.append(str(e).replace("ERREUR : ", ""))
    for rt in _rt:
        if isinstance(rt, dict) and isinstance(rt.get("pixels"), list) and not all(isinstance(px, (list, tuple)) and len(px) == 3 for px in rt["pixels"]):
            err.append("retouches : chaque pixel = [x, y, \"#rrggbb\" ou \"transparent\"]")
    for k in [k for k, v in R.items() if v is None]:  # "cle": null = cle absente (valeur par defaut)
        print(f"  ATTENTION : \"{k}\" vaut null : ignore (valeur par defaut)"); del R[k]
    # types attendus de chaque cle (une valeur du mauvais type planterait au milieu du rendu)
    NUM = (int, float)
    TYPES = {"points": dict, "boites": dict, "evenements": dict, "couleurs": dict, "cacher": list, "retouches": list,
             "accessoires": list, "grille_variantes": list, "fonds_planche": list, "rampes": list, "case": list,
             "taille_px": NUM, "directions": NUM, "contraste": NUM, "rampes_max": NUM, "seuil_alpha": NUM, "rotation_z": NUM,
             "azimut_plus": NUM, "surechantillonnage": NUM, "marge_px": NUM, "couleurs_base": NUM, "part_min": NUM,
             "nettoyage": NUM, "gravite_tissu": NUM, "normales": bool, "ombres": bool, "cavite": bool, "tete_vers_max": bool,
             "palette": str, "taille_selon": str, "contour": str, "modele": str, "animations_depuis": str, "sortie": str,
             "couleur_mode": str}
    EX = {dict: "un objet {...}", list: "une liste [...]", NUM: "un nombre", bool: "true ou false", str: "un texte \"...\""}
    for k, t in TYPES.items():
        if k in R and R[k] is not None:
            v = R[k]
            if t is NUM and isinstance(v, str):
                try:
                    float(v); continue
                except ValueError:
                    pass
            if not isinstance(v, t) or (t is NUM and isinstance(v, bool)):
                err.append(f"\"{k}\" doit etre {EX[t]} (recu : {json.dumps(v, ensure_ascii=False)[:40]})")
            elif t is NUM and not math.isfinite(float(v)):
                err.append(f"\"{k}\" : nombre invalide")
    BORNES = {"surechantillonnage": (1, 16), "marge_px": (0, 64), "rampes_max": (1, 32), "seuil_alpha": (0, 1), "contraste": (0, 5),
              "couleurs_base": (1, 16), "part_min": (0, 1), "nettoyage": (0, 5), "gravite_tissu": (0, 10)}
    for k, (lo, hi) in BORNES.items():
        v = R.get(k)
        if isinstance(v, (int, float, str)) and not isinstance(v, bool):
            try:
                if not lo <= float(v) <= hi:
                    err.append(f"\"{k}\" : entre {lo} et {hi} (recu : {v})")
            except ValueError:
                pass
    for k in ("points", "boites"):
        if isinstance(R.get(k), dict) and not all(isinstance(x, str) for x in R[k].values()):
            err.append(f"\"{k}\" : chaque valeur est un nom de zone, d'os (\"os:...\") ou d'objet")
    if isinstance(R.get("evenements"), dict):
        for k, sp in R["evenements"].items():
            if not isinstance(sp, dict) or not ("contact" in sp or "images" in sp):
                err.append(f"evenement '{k}' : {{\"contact\": \"pied_d\"}} ou {{\"images\": [3, 7]}}")
            elif "images" in sp and not (isinstance(sp["images"], list) and all(isinstance(x, int) for x in sp["images"])):
                err.append(f"evenement '{k}' : \"images\" = liste de numeros d'images")
    if isinstance(R.get("retouches"), list):
        for rt in R["retouches"]:
            if not isinstance(rt, dict) or not isinstance(rt.get("pixels", []), list):
                err.append("retouches : [{\"image\": \"<tag>_<nn>\", \"pixels\": [[x, y, \"#rrggbb\"], ...]}]"); break
    if isinstance(R.get("cacher"), list) and not all(isinstance(x, str) for x in R["cacher"]):
        err.append("cacher : liste de noms d'objets (textes)")
    import difflib
    connues = {"id", "modele", "modelage", "vue", "taille_px", "taille_selon", "palette", "animations", "animations_depuis",
               "directions", "normales", "points", "boites", "evenements", "retouches", "accessoires", "couleurs", "cacher",
               "rotation_z", "azimut_plus", "case", "marge_px", "sortie", "surechantillonnage", "contraste", "seuil_alpha",
               "rampes_max", "rampes", "contour", "auto_niveaux", "part_min", "nettoyage", "couleurs_base", "couleur_mode",
               "ombres", "cavite", "fonds_planche", "grille_variantes", "gravite_tissu", "tete_vers_max", "type", "biome",
               "provisoire", "data_id", "sorties_kit", "canon", "secondaire"}
    for k in R:
        if not k.startswith("_") and k not in connues:
            proche = difflib.get_close_matches(k, connues, 1, 0.75)
            print(f"  ATTENTION : cle inconnue \"{k}\" ignoree" + (f" -> veux-tu dire \"{proche[0]}\" ?" if proche else ""))
    if err:
        raise SystemExit("ERREUR dans la recette :\n  - " + "\n  - ".join(err))


def courbes_action(a):
    """Toutes les courbes d'une action (anciennes actions et actions a couches/slots de Blender 4.4+)."""
    if hasattr(a, "fcurves") and len(a.fcurves):
        return list(a.fcurves)
    out = []
    for l in getattr(a, "layers", []):
        for st in l.strips:
            for cb in st.channelbags:
                out += list(cb.fcurves)
    return out


def os_de_action(a):
    return {fc.data_path.split('"')[1] for fc in courbes_action(a) if fc.data_path.startswith("pose.bones[")}


def trouver_action(nom, parmi=None):
    """Animation par nom : exact, puis dernier segment exact ('Armature|Armature|Run' pour 'Run'), puis debut, puis contient."""
    import bpy
    acts = sorted(parmi if parmi is not None else bpy.data.actions, key=lambda a: a.name)
    n = nom.lower()
    for test in (lambda a: a.name.lower() == n, lambda a: a.name.lower().split("|")[-1] == n,
                 lambda a: a.name.lower().split("|")[-1].startswith(n), lambda a: n in a.name.lower()):
        r = [a for a in acts if test(a)]
        if r:
            return min(r, key=lambda a: len(a.name))
    return None


def choisir_slot(o, a, slot=None):
    """Blender 4.4+ : une action a des 'slots' (un par objet anime) ; on prend celui de cet objet."""
    ad = o.animation_data
    if ad is None or not hasattr(ad, "action_slot") or not len(getattr(a, "slots", [])):
        return
    try:
        if slot is not None and slot.identifier in [x.identifier for x in a.slots]:
            ad.action_slot = slot; return
        s_ = next((x for x in a.slots if x.target_id_type == "OBJECT" and x.name_display == o.name), None) or \
            next((x for x in a.slots if x.target_id_type == "OBJECT"), None) or a.slots[0]
        ad.action_slot = s_
    except Exception:
        pass


def resoudre_os(armature, nom):
    """'tete' -> le vrai nom de l'os (Head, mixamorig:Head, head.x...). Renvoie None si introuvable."""
    if armature is None or not nom:
        return None
    os_ = [b.name for b in armature.data.bones]
    if nom in os_:
        return nom
    for cle in SYNONYMES_OS.get(nom.lower(), [nom.lower()]):
        for b in os_:
            bl = b.lower().replace(" ", "")
            if cle in bl and not bl.endswith(("end", "_end", "top", "nub")):
                return b
    return None


def taille_base_accessoire(meshes, nom_os):
    """Taille de depart d'un accessoire : une tete fait ~1/7 d'un humain ; casque un peu plus gros."""
    import bpy
    from mathutils import Vector
    pts = np.concatenate([np.array([o.matrix_world @ Vector(b) for b in o.bound_box]) for o in meshes])
    h = float((pts.max(0) - pts.min(0))[2])
    n = (nom_os or "").lower()
    if "head" in n or "tete" in n or "skull" in n:
        return round(h * 0.24, 3)
    if "hand" in n:
        return round(h * 0.18, 3)
    return round(h * 0.3, 3)


def point_attache(armature, nom_os, taille):
    """Point ou l'on centre l'accessoire : pour une tete, le milieu du crane (pas la base du cou)."""
    from mathutils import Vector
    pb = armature.pose.bones[nom_os]
    tete = armature.matrix_world @ pb.head; queue = armature.matrix_world @ pb.tail
    if any(k in nom_os.lower() for k in ("head", "skull", "tete")):
        return tete + Vector((0, 0, 0.32 * taille))
    return (tete + queue) / 2


# ------------------------------------------------------------- mode kit
# Active par "sorties_kit": true dans usine_projet.json : l'usine produit aussi les preuves exigees par le
# controle du kit de jeu (.blend, planches base/modifie/reference/iterations, journal visuel, manifeste,
# provenance). Les 7 criteres et le verdict du journal restent VIDES : l'IA doit regarder et les remplir.
import shutil, glob as _glob
CRITERES = ("silhouette", "couleurs", "cadrage", "taille", "details", "coherence_base", "pixels_parasites")


def style_projet():
    return json.load(open("usine_projet.json")) if os.path.exists("usine_projet.json") else {}


def mode_kit():
    return bool(style_projet().get("sorties_kit"))


def kit_iteration(sid, planche, changement):
    """Copie une planche comme iteration du sprite et ouvre une entree de journal a remplir."""
    if not mode_kit() or not os.path.exists(planche):
        return None
    os.makedirs("boards/iterations", exist_ok=True); os.makedirs("art/journal", exist_ok=True)
    n = len(_glob.glob(f"boards/iterations/{sid}_it*.png")) + 1
    dst = f"boards/iterations/{sid}_it{n}.png"
    shutil.copyfile(planche, dst)
    pj = f"art/journal/{sid}.json"
    j = json.load(open(pj)) if os.path.exists(pj) else {"entrees": []}
    h = sha256(dst)
    if any(e.get("image_sha256") == h for e in j["entrees"]):
        os.remove(dst)
        print(f"  (journal : planche identique a une precedente, rien ajoute ; change un reglage avant de refaire)")
        return None
    j["entrees"].append({"changement": changement, "image": dst, "image_sha256": h,
                         "controle": {c: "" for c in CRITERES}, "verdict": "", "defauts_restants": []})
    json.dump(j, open(pj, "w"), indent=1, ensure_ascii=False)
    print(f"  JOURNAL : REGARDE {dst} puis remplis les 7 criteres et le verdict (garde/annule) de l'entree "
          f"{len(j['entrees'])} de {pj}")
    return dst


def dossier_modele(chemin_modele):
    """Remonte depuis le fichier du modele jusqu'au dossier qui contient provenance.json."""
    d = os.path.dirname(os.path.abspath(chemin_modele))
    for _ in range(6):
        if os.path.exists(os.path.join(d, "provenance.json")):
            return d
        d = os.path.dirname(d)
    return None


def kit_upsert(chemin, cle_liste, entree):
    d = json.load(open(chemin)) if os.path.exists(chemin) else {cle_liste: []}
    d.setdefault(cle_liste, [])
    d[cle_liste] = [e for e in d[cle_liste] if e.get("id") != entree["id"]] + [entree]
    json.dump(d, open(chemin, "w"), indent=1, ensure_ascii=False)
