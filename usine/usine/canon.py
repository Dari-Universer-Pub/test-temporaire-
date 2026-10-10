"""Rendu canon : la lumiere et la palette sont celles du PROJET (usine_projet.json, cle "canon"), pas de l'agent.

A partir de deux passes haute definition par image -- couleur a plat (albedo) et normales -- :
  1. chaque pixel prend la RAMPE de la palette la plus proche de sa couleur, et son cran de base dans la rampe ;
  2. la lumiere du canon decale ce cran (ombre / ton / lumiere, reflet de bord) : bandes nettes, teintes justes ;
  3. reduction par COULEUR MAJORITAIRE (jamais de moyenne : pas de demi-teintes, pas de damier) ;
  4. nettoyage des pixels isoles, contour (aucun / selectif dans la meme rampe / noir / couleur) ;
  5. mesures de lisibilite (pixels isoles, traits d'un pixel, contraste entre parties).
"""
import numpy as np

# matieres (numero = rouge de la passe matiere) : comment la surface prend la lumiere du canon
MATIERES = ("mat", "metal", "brillant", "tissu", "peau", "rugueux")

DEFAUT = {"lumiere": [-0.6, 0.65, 0.55], "bandes": {"seuils": [-0.1, 0.4], "crans": [-1, 0, 1]},
          "reflet": 0.3, "reflet_crans": 1, "couverture": 0.45, "contour": "selectif", "exposition": 0.65, "details": 0.04,
          "ombre_contact": 0.8, "matieres": True}


def regler(canon, contour_recette=None):
    c = dict(DEFAUT)
    if isinstance(canon, dict):
        c.update(canon)
    if contour_recette is not None and not (isinstance(canon, dict) and "contour" in canon):
        c["contour"] = contour_recette
    L = np.array(c["lumiere"], float); c["_L"] = L / max(np.linalg.norm(L), 1e-9)
    return c


def verifier(canon):
    """-> liste d'erreurs lisibles (vide si le canon est valide)."""
    err = []
    if canon is True or canon is None:
        return err
    if not isinstance(canon, dict):
        return ["\"canon\" doit etre true ou un objet {...} (lumiere, bandes, reflet, contour)"]
    b = canon.get("bandes")
    if b is not None and b != "doux":
        if not (isinstance(b, dict) and isinstance(b.get("seuils"), list) and isinstance(b.get("crans"), list)
                and len(b["crans"]) == len(b["seuils"]) + 1):
            err.append("canon.bandes : \"doux\" ou {\"seuils\": [s1, s2], \"crans\": [c0, c1, c2]} (un cran de plus que de seuils)")
    l_ = canon.get("lumiere")
    if l_ is not None and not (isinstance(l_, list) and len(l_) == 3 and all(isinstance(v, (int, float)) for v in l_)):
        err.append("canon.lumiere : [x, y, z] (x droite, y haut, z vers la camera)")
    ct = canon.get("contour")
    if ct is not None and ct not in ("aucun", "selectif", "noir", False) and not (isinstance(ct, str) and ct.startswith("#")):
        err.append("canon.contour : \"aucun\", \"selectif\", \"noir\" ou \"#rrggbb\"")
    d_ = canon.get("details")
    if d_ is not None and not (isinstance(d_, (int, float)) and 0 <= d_ <= 0.3):
        err.append("canon.details : nombre de 0 (aucune finition) a 0.3 (part de l'image sous laquelle une partie est un detail a garder)")
    return err


class Rampes:
    """Palette rangee par rampes (sombre -> clair). PAL : (n,3) rgb 0..1 ; RAMPE_DE : rampe de chaque couleur."""
    def __init__(self, PAL, RAMPE_DE, distance, lab, exposition=0.65):
        self.expo = exposition
        self.PAL, self.RAMPE_DE, self.distance, self.lab = PAL, RAMPE_DE, distance, lab
        self.LAB = lab(PAL)
        self.membres = [np.nonzero(RAMPE_DE == j)[0] for j in range(RAMPE_DE.max() + 1)]
        # ordre sombre -> clair dans chaque rampe (par luminance Lab), position de chaque couleur dans sa rampe
        self.membres = [m[np.argsort(self.LAB[m, 0])] for m in self.membres]
        self.pos = np.zeros(len(PAL), int)
        for m in self.membres:
            self.pos[m] = np.arange(len(m))
        self.noir = int(np.argmin(self.LAB[:, 0]))

    def base(self, rgb):
        """couleur(s) a plat -> indice de palette : la RAMPE d'abord (gris -> rampe neutre, couleur -> meme teinte),
        puis le cran par la luminosite, un cran sous le plus clair (la couleur a plat est la couleur eclairee)."""
        X = self.lab(np.atleast_2d(rgb)); out = np.empty(len(X), int)
        if not hasattr(self, "_rampe_lab"):
            self._rampe_lab = [self.LAB[m].mean(0) for m in self.membres]
            self._chroma_r = np.array([np.hypot(v[1], v[2]) for v in self._rampe_lab])
        chroma = np.hypot(X[:, 1], X[:, 2])
        for k, x in enumerate(X):
            dpal = np.linalg.norm(self.LAB - x, axis=1)
            if dpal.min() < 6:   # couleur prise dans la palette : on reste dans SA rampe
                j = int(self.RAMPE_DE[int(dpal.argmin())])
            elif chroma[k] < 12:   # gris : la rampe la plus neutre, a luminosite proche
                cand = np.argsort(self._chroma_r)[:max(1, len(self.membres) // 4)]
                j = min(cand, key=lambda j_: abs(self._rampe_lab[j_][0] - x[0]) * 0.3 + self._chroma_r[j_])
            else:                # couleur : la rampe de teinte la plus proche (luminosite peu importante)
                h = np.arctan2(x[2], x[1])
                def d(j_):
                    v = self._rampe_lab[j_]; dh = abs((np.arctan2(v[2], v[1]) - h + np.pi) % (2 * np.pi) - np.pi)
                    return dh * 40 + abs(self._chroma_r[j_] - chroma[k]) * 0.4 + (60 if self._chroma_r[j_] < 10 else 0)
                j = min(range(len(self.membres)), key=d)
            m = self.membres[j]
            pos = int(np.abs(self.LAB[m, 0] - x[0] * self.expo).argmin())
            out[k] = m[min(pos, len(m) - 2) if len(m) > 2 else pos]
        return out

    def decaler(self, idx, dec):
        out = np.empty_like(idx)
        for j, m in enumerate(self.membres):
            sel = self.RAMPE_DE[idx] == j
            if sel.any():
                out[sel] = m[np.clip(self.pos[idx[sel]] + dec[sel], 0, len(m) - 1)]
        return out


def _bruit(h, w, taille, graine=7):
    """bruit doux a gros grains (taille en pixels HD) : survit a la reduction en pixel art."""
    rnd = np.random.default_rng(graine); gh, gw = h // taille + 2, w // taille + 2
    g = rnd.uniform(-1, 1, (gh, gw))
    y = np.arange(h) / taille; x = np.arange(w) / taille
    y0 = y.astype(int); x0 = x.astype(int); fy = (y - y0)[:, None]; fx = (x - x0)[None, :]
    fy = fy * fy * (3 - 2 * fy); fx = fx * fx * (3 - 2 * fx)
    a = g[y0][:, x0]; b = g[y0][:, x0 + 1]; c = g[y0 + 1][:, x0]; d = g[y0 + 1][:, x0 + 1]
    return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy


def ombrer(alb, nor, R_, c, mat=None, occ=None, sur=8):
    """alb, nor : (h, w, 4) haute definition -> indices de palette (h, w), -1 = vide.
    mat (passe matiere : rouge = numero, vert = emet) et occ (ombre portee + creux) : facultatifs."""
    h, w = alb.shape[:2]; a = alb[..., 3] > 0.5
    out = np.full((h, w), -1)
    if not a.any():
        return out, out
    rgb = alb[..., :3][a]
    # couleurs a plat : peu de valeurs differentes -> on ne cherche la rampe qu'une fois par couleur
    q = (np.clip(rgb, 0, 1) * 63).round().astype(int); cle = q[:, 0] * 4096 + q[:, 1] * 64 + q[:, 2]
    uniq, inv = np.unique(cle, return_inverse=True)
    rep = np.stack([(uniq // 4096), (uniq // 64) % 64, uniq % 64], 1) / 63.0
    base = R_.base(rep)[inv]
    n = nor[..., :3][a] * 2 - 1; n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
    lam = n @ c["_L"]
    if c["bandes"] == "doux":
        dec = np.round((np.clip(lam * 0.5 + 0.5, 0, 1) - 0.62) / 0.2).astype(int)
    else:
        dec = np.full(lam.shape, c["bandes"]["crans"][0], int)
        for s_, t in zip(c["bandes"]["seuils"], c["bandes"]["crans"][1:]):
            dec = np.where(lam > s_, t, dec)
    if c.get("reflet"):  # reflet de bord : surfaces vues de profil, du cote eclaire
        bord = (np.abs(n[:, 2]) < c["reflet"]) & (lam > -0.15)
        dec = np.where(bord, dec + int(c.get("reflet_crans", 1)), dec)
    if mat is not None and c.get("matieres", True):
        r_ = mat[..., 0][a]; r_ = np.where(r_ <= 0.04045, r_ / 12.92, ((r_ + 0.055) / 1.055) ** 2.4)   # passe enregistree en sRGB
        k = np.round(r_ * 8).astype(int); emet = mat[..., 1][a] > 0.5
        sp = (2 * lam[:, None] * n - c["_L"][None])[:, 2]          # reflet speculaire vers la camera
        met = k == 1   # metal : contraste fort (sombre au coeur, eclat franc)
        dec = np.where(met, np.where(lam > 0.25, dec, dec - 1), dec)
        dec = np.where(met & (sp > 0.8), dec + 2, dec)
        dec = np.where((k == 2) & (sp > 0.9), dec + 1, dec)          # brillant : petit eclat
        tis = k == 3   # tissu : pas d'eclat ni de reflet de bord, ombre douce
        dec = np.where(tis, np.minimum(dec, 0), dec)
        pea = k == 4   # peau : ombre adoucie (la lumiere traverse un peu)
        dec = np.where(pea & (dec < 0) & (lam > -0.35), dec + 1, dec)
        rug = k == 5   # rugueux : la lumiere se brise en plaques (pierre, ecorce, croute)
        if rug.any():
            bz = _bruit(h, w, max(2, int(sur * 2.2)))[a]
            dec = np.where(rug, np.where(lam + bz * 0.35 > 0.4, 1, np.where(lam + bz * 0.35 > -0.1, 0, -1)) +
                           np.where(bz < -0.7, -1, 0), dec)
        dec = np.where(emet, 2, dec)   # ce qui emet de la lumiere ne prend pas d'ombre
    else:
        emet = np.zeros(lam.shape, bool)
    if occ is not None and c.get("ombre_contact"):   # ombre portee d'une partie sur l'autre, creux
        o_ = occ[..., :3][a].mean(1)
        dec = np.where((o_ < c["ombre_contact"]) & ~emet, dec - 1, dec)
    out[a] = R_.decaler(base, dec)
    grp = np.full((h, w), -1); grp[a] = inv   # couleur a plat de chaque pixel (= la partie de l'objet)
    return out, grp


def reduire(idx, sur, couverture, grp=None, details=0.04):
    """reduction par couleur MAJORITAIRE ; finition : une partie RARE de l'image (moins de `details` de la surface :
    yeux, boucle, gemme, serrure) garde son pixel des qu'elle couvre 1/5 du bloc, au lieu d'etre avalee."""
    h, w = idx.shape; H, W = h // sur, w // sur
    b = idx[:H * sur, :W * sur].reshape(H, sur, W, sur).transpose(0, 2, 1, 3).reshape(H, W, sur * sur)
    out = np.full((H, W), -1)
    n_min = sur * sur * couverture
    rares = []
    if grp is not None and details:
        g_ = grp[:H * sur, :W * sur].reshape(H, sur, W, sur).transpose(0, 2, 1, 3).reshape(H, W, sur * sur)
        v = grp[grp >= 0]
        if len(v):
            part = np.bincount(v) / len(v)
            n_bloc = sur * sur
            # une vraie partie (pas un melange de bord) : au moins un bloc entier de pixels
            rares = [j for j in np.argsort(part) if 0 < part[j] < details and part[j] * len(v) >= n_bloc]
    for y in range(H):
        for x in range(W):
            v = b[y, x]; ok = v >= 0; v = v[ok]
            if len(v) >= n_min:
                out[y, x] = np.bincount(v).argmax()
                if rares:
                    gv = g_[y, x][ok]
                    for j in rares:   # la partie la plus rare d'abord
                        sel = gv == j
                        if sel.sum() >= sur * sur * 0.2:
                            out[y, x] = np.bincount(v[sel]).argmax(); break
    return out


def nettoyer(img):
    """pixel sans aucun voisin (8) de sa couleur -> couleur majoritaire de ses voisins directs."""
    h, w = img.shape; o = img.copy()
    for y in range(h):
        for x in range(w):
            c = img[y, x]
            if c < 0:
                continue
            v8 = [img[y + dy, x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                  if (dy or dx) and 0 <= y + dy < h and 0 <= x + dx < w]
            if c in v8:
                continue
            v4 = [img[y + dy, x + dx] for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))
                  if 0 <= y + dy < h and 0 <= x + dx < w and img[y + dy, x + dx] >= 0]
            if v4:
                o[y, x] = max(set(v4), key=v4.count)
    return o


def contour(img, R_, mode, couleur=None):
    if mode in (None, False, "aucun"):
        return img
    h, w = img.shape; o = img.copy(); vide = img < 0
    pad = np.pad(vide, 1, constant_values=True)
    touche = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    if mode == "selectif":  # bord interieur : 2 crans plus sombre DANS SA rampe
        sel = ~vide & touche
        o[sel] = R_.decaler(img[sel], np.full(int(sel.sum()), -2))
        return o
    # contour exterieur (noir ou couleur) : les pixels vides voisins d'une masse
    plein = np.pad(~vide, 1, constant_values=False)
    voisin = plein[:-2, 1:-1] | plein[2:, 1:-1] | plein[1:-1, :-2] | plein[1:-1, 2:]
    sel = vide & voisin
    o[sel] = R_.noir if mode == "noir" else couleur
    return o


def mesures(img, R_):
    """lisibilite : pixels isoles, traits d'un pixel, contraste entre zones voisines."""
    op = img >= 0; n = int(op.sum())
    if n == 0:
        return {"pixels": 0, "isoles_pct": 0.0, "traits_1px_pct": 0.0, "contraste_min": 0.0}
    h, w = img.shape; iso = 0
    for y, x in zip(*np.nonzero(op)):
        c = img[y, x]
        if not any(0 <= y + dy < h and 0 <= x + dx < w and img[y + dy, x + dx] == c
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx):
            iso += 1
    pad = np.pad(op, 1, constant_values=False)
    trait = op & ((~pad[1:-1, :-2] & ~pad[1:-1, 2:]) | (~pad[:-2, 1:-1] & ~pad[2:, 1:-1]))
    # contraste : pour chaque paire de PARTIES (rampes) qui se touchent sur une vraie longueur, l'ecart moyen de
    # luminance et de teinte ; la pire paire dit si deux parties se confondent
    L = R_.LAB; rd = np.where(op, R_.RAMPE_DE[np.where(op, img, 0)], -1); paires = {}
    for dy, dx in ((0, 1), (1, 0)):
        a = rd[:h - dy, :w - dx]; b = rd[dy:, dx:]; ia = img[:h - dy, :w - dx]; ib = img[dy:, dx:]
        m = (a >= 0) & (b >= 0) & (a != b)
        for ra, rb, xa, xb in zip(a[m], b[m], ia[m], ib[m]):
            paires.setdefault((min(ra, rb), max(ra, rb)), []).append(float(np.linalg.norm(L[xa] - L[xb])))
    vals = [np.mean(v) for v in paires.values() if len(v) >= 12]
    cmin = float(min(vals)) if vals else 100.0
    return {"pixels": n, "isoles_pct": round(100 * iso / n, 1), "traits_1px_pct": round(100 * float(trait.sum()) / n, 1),
            "contraste_min": round(cmin, 1)}


def alertes(mes):
    a = []
    if max(m["isoles_pct"] for m in mes) > 3:
        a.append("canon : pixels isoles > 3 % -> taille_px plus grande ou formes plus simples")
    if max(m["traits_1px_pct"] for m in mes) > 15:
        a.append("canon : trop de traits d'un pixel (membres ou details trop fins pour cette taille) -> epaissir ou taille_px")
    if min(m["contraste_min"] for m in mes) < 10:
        a.append("canon : deux parties voisines se confondent (meme luminosite) -> couleurs plus contrastees")
    return a


def pixeliser(ALB, NOR, R_, sur, canon, MAT=None, OCC=None):
    """-> (liste d'images RGBA (h, w, 4) 0..1, mesures par image)."""
    imgs, mes = [], []
    for i_, (alb, nor) in enumerate(zip(ALB, NOR)):
        idx_hd, grp = ombrer(alb, nor, R_, canon, MAT[i_] if MAT else None, OCC[i_] if OCC else None, sur)
        idx = reduire(idx_hd, sur, canon["couverture"], grp, float(canon.get("details", 0.04)))
        idx = contour(nettoyer(idx), R_, canon["contour"],
                      R_.base(np.array([[int(canon["contour"][i:i + 2], 16) / 255 for i in (1, 3, 5)]]))[0]
                      if isinstance(canon["contour"], str) and canon["contour"].startswith("#") else None)
        idx = nettoyer(idx)   # le contour interieur peut laisser un pixel seul (coin) : meme regle qu'avant le contour
        rgba = np.zeros(idx.shape + (4,)); m = idx >= 0
        rgba[m, :3] = R_.PAL[idx[m]]; rgba[m, 3] = 1
        imgs.append(rgba); mes.append(mesures(idx, R_))
    return imgs, mes
