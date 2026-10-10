"""grille : une image pixel agrandie avec sa grille et ses coordonnees, pour les retouches au pixel pres.

    usine grille build/sprites/<id>/pixel/<tag>_<nn>.png
-> <meme nom>_grille.png : chaque pixel = un carre de 16, une ligne fine tous les pixels, une ligne forte tous les 5,
   les numeros de colonne (x) en haut et de ligne (y) a gauche, tous les 5.
Ensuite, dans la recette : "retouches": [{"image": "<tag>_<nn>", "pixels": [[x, y, "#rrggbb"], [x, y, "transparent"]]}]
puis usine fabriquer. Les couleurs disponibles sont listees (celles deja dans le sprite) : garde la palette.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from commun import *

ARGS = sys.argv[sys.argv.index("--") + 1:]
if not ARGS:
    raise SystemExit("usage : usine grille build/sprites/<id>/pixel/<image>.png [taille_du_pixel]")
src = ARGS[0]
if not os.path.isfile(src):
    raise SystemExit(f"ERREUR : image introuvable : {src} (les images sont dans build/sprites/<id>/pixel/ apres usine fabriquer)")
K = max(4, int(ARGS[1])) if len(ARGS) > 1 and ARGS[1].isdigit() else 16
a = lire_image(src)
h, w = a.shape[:2]
M = 30  # marge pour les numeros
out = np.ones((h * K + M + 20, w * K + M + 40, 4))  # place pour les derniers numeros
# damier sous les pixels transparents
dam = ((np.add.outer(np.arange(h * K) // 8, np.arange(w * K) // 8)) % 2)[..., None] * 0.08 + 0.85
grand = np.repeat(np.repeat(a, K, 0), K, 1)
al = grand[..., 3:4]
out[M:M + h * K, M:M + w * K, :3] = grand[..., :3] * al + dam * (1 - al)
for x in range(w + 1):
    out[M:M + h * K, M + min(x * K, w * K - 1), :3] = (0.2, 0.2, 0.2) if x % 5 == 0 else (0.6, 0.6, 0.6)
for y in range(h + 1):
    out[M + min(y * K, h * K - 1), M:M + w * K, :3] = (0.2, 0.2, 0.2) if y % 5 == 0 else (0.6, 0.6, 0.6)

def coller(img, y0, x0):
    """colle img en (y0, x0), coupee aux bords de out"""
    hh = max(0, min(img.shape[0], out.shape[0] - y0)); ww = max(0, min(img.shape[1], out.shape[1] - x0))
    if hh and ww:
        out[y0:y0 + hh, x0:x0 + ww] = img[:hh, :ww]

for x in range(0, w, 5):
    s_ = numeroter(np.ones((18, 40, 4)), x, k=2, fond=(0.15, 0.15, 0.4))
    coller(s_[:18, :(6 * len(str(x)) + 1) * 2], 4, M + x * K)
for y in range(0, h, 5):
    s_ = numeroter(np.ones((18, 40, 4)), y, k=2, fond=(0.4, 0.15, 0.15))
    coller(s_[:18, :min((6 * len(str(y)) + 1) * 2, M - 2)], M + y * K, 0)
dst = os.path.splitext(src)[0] + "_grille.png"
ecrire_image(dst, out)
cols = sorted({"#%02x%02x%02x" % tuple((c * 255).round().astype(int)) for c in a[a[..., 3] > 0][:, :3]})
print(f"GRILLE : {dst}  ({w} x {h} pixels ; x vers la droite, y vers le bas, origine en haut a gauche)")
print("Couleurs du sprite (garde la palette) : " + " ".join(cols))
