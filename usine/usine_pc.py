#!/usr/bin/env python3
"""Lanceur de l'usine a assets avec les outils de TON PC (ceux de tools/outils.json, comme gate.py) :
Blender Windows et Aseprite dans WSL. Python standard seulement (lance avec `py` ou `python`).

    usine verifier                          -> teste Blender et Aseprite de tools/outils.json
    usine chercher "<sujet anglais + francais>"
    usine obtenir  "<sujet>" <numero>
    usine accessoire recettes/<id>.json [numero]
    usine variantes  recettes/<id>.json
    usine choisir    recettes/<id>.json <numero>
    usine fabriquer  recettes/<id>.json
    usine gabarit <type> <id> [numero]
    usine analyser modeles/<id>/source/<fichier>
    usine modeler  recettes/<id>.json
    usine affiner  recettes/<id>.json
    usine choisir_affinage recettes/<id>.json <numero>
    usine grille   build/sprites/<id>/pixel/<image>.png
    usine variations recettes/<id>.json [n]     -> planche de n versions (silhouettes) d'un asset construit
    usine choisir_variation recettes/<id>.json <numero>
    usine references "<sujet en anglais>" [--pixel] [--famille <f>] -> references libres (+ galerie qualite)
    usine choisir_references "<sujet>" <n> <n>
    usine banc [<id>]                          -> banc d'essai fixe du superviseur (planche avant/apres)
    usine refabriquer                      -> refait TOUS les assets depuis leurs recettes (apres un changement du canon)
Mode d'emploi complet : tools/pixelisation/usine/LISEZMOI.md
"""
import os, sys, json, re, subprocess

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # le projet
USINE = os.path.join(RACINE, "tools", "pixelisation", "usine")
BRUIT = re.compile(r"^(Blender \d|Read |EGL Error|Blender quit|Fra:|Saved:| Time:|Color management|"
                   r"Warning: |INFO |  \(|Draco|Info:|[0-9:. ]+(render|io|blend) |$)|\| INFO")


def outils():
    with open(os.path.join(RACINE, "tools", "outils.json"), encoding="utf-8") as f:
        return json.load(f)


def vers_wsl(p):
    """C:\\Users\\x -> /mnt/c/Users/x (pour un outil lance dans WSL)."""
    p = os.path.abspath(p)
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", p)
    return f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/") if m else p.replace("\\", "/")


def commande(nom):
    """Commande de l'outil, adaptee a la machine (meme logique que gate.py)."""
    c = list(outils()[nom])
    dans_wsl = bool(c) and c[0].lower() in ("wsl", "wsl.exe")
    if dans_wsl:
        reste = c[c.index("-e") + 1:] if "-e" in c else c[-1:]
        if os.name == "nt":
            avant = c[1:c.index("-e")] if "-e" in c else []
            return ["wsl.exe", *avant, "--cd", os.getcwd(), "-e", *reste], True
        return reste, False  # deja sous Linux
    if os.name != "nt" and c and re.match(r"^[A-Za-z]:\\", c[0]):  # kit lance depuis WSL
        c[0] = f"/mnt/{c[0][0].lower()}/" + c[0][3:].replace("\\", "/")
    return c, False


def blender(script, *args):
    cmd, _ = commande("blender")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([*cmd, "-b", "--python", os.path.join(USINE, script), "--", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    sortie = (r.stdout or "") + (r.stderr or "")
    for l in sortie.splitlines():
        if not BRUIT.match(l):
            print(l)
    return sortie


def aseprite(*args, script=None):
    cmd, wsl = commande("aseprite")
    if script:
        args = (*args, "--script", vers_wsl(script) if wsl else script)
    r = subprocess.run([*cmd, "--batch", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(((r.stdout or "") + (r.stderr or "")).strip())
    return r.returncode


def recette_infos(chemin):
    with open(chemin, encoding="utf-8") as f:
        r = json.load(f)
    return r["id"], r.get("sortie", f"build/sprites/{r['id']}")


def main():
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help", "aide"):
        print(__doc__); return
    c = a[0]
    besoin = {"chercher": 2, "obtenir": 3, "accessoire": 2, "gabarit": 3, "analyser": 2, "modeler": 2, "affiner": 2,
              "choisir_affinage": 3, "grille": 2, "variantes": 2, "choisir": 3, "fabriquer": 2,
              "variations": 2, "choisir_variation": 3,
              "references": 2, "choisir_references": 3}
    if c in besoin and len(a) < besoin[c]:
        print(f"ERREUR : arguments manquants pour '{c}'.\n"); print(__doc__); sys.exit(2)
    if c == "verifier":
        print("Blender  :", (blender_version := subprocess.run([*commande("blender")[0], "--version"],
              capture_output=True, text=True, errors="replace").stdout.strip().splitlines() or ["ECHEC"])[0])
        aseprite("--version")
    elif c == "chercher":
        blender("chercher.py", *a[1:])
    elif c == "obtenir":
        blender("obtenir.py", *a[1:])
    elif c == "accessoire":
        blender("accessoire.py", *a[1:])
    elif c == "gabarit":
        blender("gabarit.py", *a[1:])
    elif c == "analyser":
        blender("modeler.py", "analyser", *a[1:])
    elif c == "modeler":
        blender("modeler.py", "modeler", a[1])
    elif c == "affiner":
        blender("affiner.py", a[1])
    elif c == "choisir_affinage":
        subprocess.run([sys.executable, os.path.join(USINE, "choisir_affinage.py"), a[1], a[2]])
    elif c == "grille":
        blender("grille.py", *a[1:])
    elif c == "variations":
        blender("variations.py", *a[1:])
    elif c == "choisir_variation":
        subprocess.run([sys.executable, os.path.join(USINE, "choisir_variation.py"), a[1], a[2]])
    elif c == "banc":
        os.environ["USINE_BLENDER"] = json.dumps(commande("blender")[0])
        blender(os.path.join("banc_modeleur", "banc.py"), *a[1:])
    elif c == "references":
        blender("references.py", "chercher", *a[1:])
    elif c == "choisir_references":
        blender("references.py", "choisir", *a[1:])
    elif c == "variantes":
        blender("fabriquer.py", "variantes", a[1])
    elif c == "choisir":
        subprocess.run([sys.executable, os.path.join(USINE, "choisir.py"), a[1], a[2]])
    elif c == "fabriquer":
        sortie = blender("fabriquer.py", "fabriquer", a[1])
        if "FABRIQUE_OK" not in sortie:
            print("ECHEC : rien produit (lis les messages ci-dessus)"); sys.exit(1)
        ident, dossier = recette_infos(a[1])
        if not os.path.exists(os.path.join(dossier, "images.json")):
            print("ECHEC : rien produit (lis les messages ci-dessus)"); sys.exit(1)
        os.makedirs(os.path.join("assets", "sprites", ident), exist_ok=True)
        os.makedirs(os.path.join("art", "source", "aseprite"), exist_ok=True)
        aseprite("--script-param", f"dossier={dossier}".replace("\\", "/"),
                 "--script-param", f"sortie=assets/sprites/{ident}",
                 "--script-param", f"source=art/source/aseprite/{ident}.aseprite",
                 script=os.path.join(USINE, "assembler_aseprite.lua"))
        print(f"REGARDE la planche : {dossier}/{ident}_planche.png   (mesures et alertes : {dossier}/{ident}_mesures.json)")
        print(f"Pour le jeu : assets/sprites/{ident}/{ident}.png + {ident}.json   source : art/source/aseprite/{ident}.aseprite")
    elif c == "refabriquer":  # refait TOUS les assets depuis leurs recettes (apres un changement du canon)
        import glob
        ok, ko = 0, []
        for r in sorted(glob.glob(os.path.join("recettes", "*.json"))):
            if json.load(open(r, encoding="utf-8-sig")).get("modelage"):
                if subprocess.run([sys.executable, __file__, "modeler", r], capture_output=True).returncode:
                    ko.append(r + " (modeler)"); continue
            p = subprocess.run([sys.executable, __file__, "fabriquer", r], capture_output=True, text=True, errors="replace")
            if "FABRIQUE_OK" in p.stdout:
                ok += 1
            else:
                ko.append(r)
        print(f"REFABRIQUE_OK {ok} asset(s) refait(s)")
        if ko:
            print("ECHEC pour : " + ", ".join(ko) + " (relance usine fabriquer <recette> pour lire l'erreur)"); sys.exit(1)
    else:
        print(f"commande inconnue : {c}\n"); print(__doc__); sys.exit(2)


main()
