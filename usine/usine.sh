#!/usr/bin/env bash
# usine : assets pixel art de qualite pro a partir de modeles 3D CC0, en quelques commandes simples.
#   usine chercher "<sujet en anglais + francais>"     -> planche numerotee de modeles CC0
#   usine obtenir  "<sujet>" <numero>                   -> telecharge + apercu reel + licence
#   usine fabriquer recettes/<id>.json                  -> sprites + planche + mesures + .aseprite + json
#   usine variantes recettes/<id>.json                  -> planche numerotee de reglages
#   usine choisir   recettes/<id>.json <numero>         -> applique le reglage choisi
#   usine accessoire recettes/<id>.json [numero]        -> pose un accessoire par choix numerotes (3 etapes)
#   usine gabarit <type> <id> [numero]                  -> raccourci : meduse/algue/corail/cristal/rocher tout faits
#   usine analyser modeles/<id>/source/<fichier>        -> carte du modele : haut/avant/droite + zones numerotees
#   usine modeler  recettes/<id>.json                   -> modifie ou construit le modele par contraintes (planche + mesures)
#   usine affiner  recettes/<id>.json                   -> 6 essais numerotes pour la valeur {"affiner": [min, max]}
#   usine choisir_affinage recettes/<id>.json <numero>  -> ecrit la valeur choisie
#   usine grille   build/sprites/<id>/pixel/<image>.png -> grille agrandie pour retoucher au pixel pres
#   usine variations recettes/<id>.json [n]            -> planche de n versions (silhouettes) d'un asset construit
#   usine choisir_variation recettes/<id>.json <numero> -> garde la version choisie
#   usine references "<sujet en anglais>" [--pixel] [--famille <f>] -> references libres (+ pixel art, + galerie qualite)
#   usine choisir_references "<sujet>" <n> <n>          -> garde 2-3 references + leurs reperes (couleurs, contraste)
#   usine banc [<id>]                                   -> banc d'essai fixe du superviseur (planche avant/apres)
#   usine refabriquer                                   -> refait TOUS les assets depuis leurs recettes (canon change)
U="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)/usine"
O="${OUTILS:-/opt/outils-varekh}/bin"
B() { "$O/blender" -b --python "$U/$1" -- "${@:2}" 2>&1 | grep -vE "^(Blender |Read |EGL Error|$|Blender quit|Fra:|Saved:| Time:)"; }
case "$1" in
  chercher|obtenir|variantes|choisir|accessoire|gabarit|analyser|modeler|affiner|choisir_affinage|grille|variations|choisir_variation|references|choisir_references) [ -n "$2" ] || { sed -n 2,20p "$0"; exit 2; } ;;&
  chercher)  shift; B chercher.py "$@" ;;
  obtenir)   shift; B obtenir.py "$@" ;;
  variantes) B fabriquer.py variantes "$2" ;;
  choisir)   "$O/python" "$U/choisir.py" "$2" "$3" ;;
  accessoire) B accessoire.py "$2" $3 | grep -vE "^(Fra|Saved|Time)" ;;
  gabarit)   B gabarit.py "$2" "$3" $4 | grep -vE "^(Fra|Saved|Time|INFO|  |Draco)" ;;
  analyser)  B modeler.py analyser "$2" $3 | grep -vE "INFO|Info:|^[0-9:. ]+(render|io)" ;;
  modeler)   B modeler.py modeler "$2" | grep -vE "INFO|Info:|^[0-9:. ]+(render|io|blend)" ;;
  affiner)   B affiner.py "$2" | grep -vE "INFO|Info:" ;;
  choisir_affinage) "$O/python" "$U/choisir_affinage.py" "$2" "$3" ;;
  grille)    B grille.py "$2" $3 ;;
  variations) B variations.py "$2" $3 | grep -E "VARIATIONS_OK|REGARDE : .*variations|Puis|ECHEC|ERREUR|version" ;;
  references) B references.py chercher "${@:2}" | grep -E "_OK|REGARDE|Puis|ERREUR|ATTENTION" ;;
  choisir_references) B references.py choisir "${@:2}" | grep -E "_OK|Sers|ERREUR" ;;
  banc) shift; USINE_BLENDER="[\"$O/blender\"]" B banc_modeleur/banc.py "$@" | grep -vE "^(Fra|Saved|Time|INFO)" ;;
  choisir_variation) "$O/python" "$U/choisir_variation.py" "$2" "$3" ;;
  fabriquer)
    [ -n "$2" ] || { sed -n 2,20p "$0"; exit 2; }
    SORTIE=$(B fabriquer.py fabriquer "$2")
    echo "$SORTIE" | grep -E "FABRIQUE_OK|introuvable|ERREUR|^  - |ATTENTION|KIT|JOURNAL|Error|Traceback|line [0-9]"
    echo "$SORTIE" | grep -q "FABRIQUE_OK" || { echo "ECHEC : rien produit (lis les messages ci-dessus)"; exit 1; }
    ID=$("$O/python" -c "import json,sys;print(json.load(open(sys.argv[1],encoding='utf-8-sig'))['id'])" "$2")
    D=$("$O/python" -c "import json,sys;r=json.load(open(sys.argv[1],encoding='utf-8-sig'));print(r.get('sortie','build/sprites/'+r['id']))" "$2")
    mkdir -p "assets/sprites/$ID" art/source/aseprite
    "$O/aseprite" --batch --script-param dossier="$D" --script-param sortie="assets/sprites/$ID" \
      --script-param source="art/source/aseprite/$ID.aseprite" --script "$U/assembler_aseprite.lua"
    echo "REGARDE la planche : $D/${ID}_planche.png   (mesures et alertes : $D/${ID}_mesures.json)"
    echo "Pour le jeu : assets/sprites/$ID/$ID.png + $ID.json   source : art/source/aseprite/$ID.aseprite" ;;
  refabriquer)  # refait TOUS les assets depuis leurs recettes (apres un changement du canon ou de la palette)
    OK=0; KO=""
    for r in recettes/*.json; do
      [ -f "$r" ] || continue
      if "$O/python" -c "import json,sys;sys.exit(0 if json.load(open(sys.argv[1],encoding='utf-8-sig')).get('modelage') else 1)" "$r"; then
        "$0" modeler "$r" >/dev/null 2>&1 || { KO="$KO $r(modeler)"; continue; }
      fi
      if "$0" fabriquer "$r" >/dev/null 2>&1; then OK=$((OK+1)); else KO="$KO $r"; fi
    done
    echo "REFABRIQUE_OK $OK asset(s) refait(s)"; [ -z "$KO" ] || { echo "ECHEC pour :$KO (relance usine fabriquer <recette> pour lire l'erreur)"; exit 1; } ;;
  *) sed -n 2,20p "$0" ;;
esac
