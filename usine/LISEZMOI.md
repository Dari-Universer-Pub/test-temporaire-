# Usine à assets pixel art (pour agents IA, même modestes)

Cet outil fabrique des sprites pixel art de **qualité pro** à partir de **vrais modèles 3D CC0** trouvés
automatiquement, pour **n'importe quel projet** : plateforme vue de côté, RPG vu de dessus, isométrique…
Tu n'écris pas de code, tu ne dessines rien et tu ne cherches pas sur le Web toi-même.
Tu tapes des commandes, tu **regardes des images** et tu **réponds par un numéro**.

Prérequis : les outils installés (`/opt/outils-varekh`, voir `INSTALLER_OUTILS.sh`) et un accès Internet.

## 0. Une seule fois par projet : le style commun

Copie `modeles_de_recettes/usine_projet.json` à la racine du projet et règle-le :

| Clé | Valeurs | Conseil |
|---|---|---|
| `palette` | `"auto"`, `"lospec:<nom>"` (ex. `lospec:endesga-32`, `lospec:sweetie-16`), un fichier `.hex`, ou `art/palette.json` (rampes) | La même pour TOUT le projet |
| `vue` | `cote` (plateforme), `rpg` (dessus en 3/4), `dessus`, `iso`, `face`, `trois_quarts` | La même pour TOUT le projet |
| `taille_px` | hauteur du héros en pixels (16 à 64) | Les autres sujets se règlent par rapport à lui |

### Le canon de rendu (recommandé) : la même lumière et la même finition pour tout le jeu

Ajoute `"canon"` dans `usine_projet.json` (avec une palette en rampes, `art/palette.json`). `fabriquer` ne fait alors plus
un rendu « éclairé » puis une moyenne de pixels : il calcule la lumière **par crans dans les rampes** de la palette et
réduit **par couleur majoritaire**. Résultat : pas de damier, teintes justes, mêmes lumières sur TOUS les assets.

```json
"canon": {"lumiere": [-0.6, 0.65, 0.55], "bandes": {"seuils": [-0.1, 0.4], "crans": [-1, 0, 1]},
          "reflet": 0.3, "contour": "selectif", "exposition": 0.65}
```

| Clé du canon | Effet | Valeurs |
|---|---|---|
| `lumiere` | direction de la lumière (x droite, y haut, z vers la caméra) | défaut : en haut à gauche, de face |
| `bandes` | `"doux"` (dégradé) ou des bandes nettes : `seuils` de lumière et `crans` de la rampe (un cran de plus que de seuils) | `{"seuils": [0.05], "crans": [-1, 0]}` = 2 tons (rétro) |
| `reflet` | reflet de bord du côté éclairé (0 = aucun ; 0.3 = fin) | `reflet_crans` : 1 ou 2 |
| `contour` | `"aucun"`, `"selectif"` (bord 2 crans plus sombre dans sa rampe), `"noir"`, `"#rrggbb"` | |
| `exposition` | ton de départ dans la rampe (plus bas = plus sombre) | 0.5 à 0.8 (défaut 0.65) |
| `details` | finition : une partie qui couvre moins de cette part de l'image (yeux, boucle, gemme, serrure) garde son pixel au lieu d'être avalée par la réduction | 0 (aucune) à 0.3 (défaut 0.04) |

`"canon": true` prend ces valeurs par défaut. Le canon est fixé UNE fois par Julien : **ne le change pas pour un seul
asset** (tout le jeu perdrait sa cohérence). Avec le canon, `variantes` ne sert plus (le rendu ne se règle pas par asset).
Après un changement du canon : `usine refabriquer` refait tous les assets depuis leurs recettes.
Mesures de lisibilité ajoutées à `<id>_mesures.json` (`canon` : pixels isolés, traits d'un pixel, contraste entre
parties) et alertes `canon : ...` dans la sortie de `fabriquer`.

## 1. Pour chaque asset : 5 commandes, toujours dans cet ordre

```bash
usine chercher "crab crabe"                  # sujet en anglais ET en français
```
→ **REGARDE** `recherche/<sujet>/planche.png`. Choisis le numéro **le plus proche du sujet**. À égalité, prends
le même créateur que tes autres assets (cohérence de style). Une vignette de pack (plein de modèles) est normale :
le nom du modèle est écrit dans la liste. Évite les modèles marqués `[LOURD : …k faces]` (scans très lourds, lents et
peu lisibles en pixel art) s'il existe un autre choix.

```bash
usine obtenir "crab crabe" 3                 # le numéro choisi
```
→ **REGARDE** `modeles/<id>/apercu.png` (face, profil, dessus, 3/4). Si ce n'est pas le bon sujet, ou si le
message dit **GRIS**, reviens à l'étape précédente et prends un autre numéro. Note le `fichier` et les `animations` affichés.

```bash
cp <usine>/modeles_de_recettes/<le plus proche>.json recettes/crabe.json
```
Remplace seulement `CHANGE_MOI` par l'`id`, `FICHIER` par le fichier affiché, et les noms d'`action` par des
noms de la liste `animations`. Sans animation dans le modèle, garde une animation `procedural` :

| Sujet | `procedural` |
|---|---|
| poisson, anguille, serpent, ver | `onde` |
| méduse, cœur, créature molle | `pulsation` |
| arbre, plante, herbe, drapeau | `balancement` |
| slime, gelée, créature qui sautille | `rebond` |
| pièce, gemme, objet à ramasser | `rotation` |
| tout ce qui flotte (bulle, fantôme, objet dans l'eau) | `flottement` |
| tout être immobile mais vivant | `respiration` |

```bash
usine variantes recettes/crabe.json          # puis REGARDE la planche numérotée
usine choisir   recettes/crabe.json 4        # le numéro le plus net et le plus lisible
usine fabriquer recettes/crabe.json
```
→ **REGARDE** `build/sprites/<id>/<id>_planche.png` : en haut le rendu 3D, en dessous le pixel art sur 3 fonds.
Le jeu reçoit `assets/sprites/<id>/<id>.png` + `<id>.json` (tags = noms des animations), et la source est
`art/source/aseprite/<id>.aseprite`.

## 2. Si `fabriquer` affiche une alerte : la correction est toujours la même

| Alerte / ce que tu vois | Ce que tu changes dans la recette |
|---|---|
| `moins de 6 couleurs`, sprite plat | `usine variantes` puis un numéro plus contrasté, ou `"rampes_max": 6` |
| `sprite gris` | `"couleurs": {"<nom de matériau>": "#rrggbb"}` (les noms sont dans `infos.json`) |
| `ne remplit pas sa case` | `"taille_selon": "max"` ou une autre `vue` |
| `animation figée` | un autre nom d'`action` de la liste, ou un `procedural` |
| le sujet regarde vers la gauche ou le mauvais côté | `"rotation_z": 90`, `180` ou `-90` |
| le sujet est trop petit ou trop grand par rapport au héros | `"taille_px"` |
| couleurs trop claires ou trop sombres | `"contraste": 1.2` (plus fort) ou `0.9` (plus doux) |
| un accessoire manque (casque, arme, bouteilles…) | `usine chercher` l'accessoire, puis `usine modeler` (section 5 : `importer` + `poser` ou `englober`) |
| le modèle ne convient pas tel quel (forme, pièce en plus, autre animation) | `usine modeler` (section 5) |
| des pièces en trop (socle, arme, sol) | `"cacher": ["nom d'objet"]` (les noms sont dans `infos.json`) |
| `cle inconnue ... veux-tu dire ...` | corrige le nom de la clé (faute de frappe : la clé était ignorée) |
| `l'animation ... est VIDE` ou `vient d'un autre squelette` | une autre `action` de la liste donnée, ou `reprendre` dans `modelage` |
| `ce modele change d'echelle quand il est anime` (modeler) | un autre numéro de `chercher` (ou ce modèle sans `modelage`) |

Une seule modification à la fois, puis `fabriquer` et regarder. Jamais deux changements sans regarder entre les deux.

## 3. Ce que l'usine fait toute seule (n'y touche pas)

- Licence : seulement des sources **CC0** ; preuve dans `modeles/<id>/licence.html` et `provenance.json`
  (URL, auteur, SHA-256).
- Réparation des textures perdues (chemins de l'auteur, noms approchés, couleurs de matériaux).
- Couleurs de sommets, matériaux composés ou procéduraux : « cuits » en texture pour que le sprite ait les vraies couleurs.
- Formats lus : glb/gltf, blend, fbx, obj, dae, stl, ply, usd/usdz, x3d, abc. Si un fichier ne s'ouvre pas, `obtenir`
  essaie les autres fichiers 3D du même modèle.
- Caméra orthographique et cadrage commun à toutes les images de toutes les animations (pas de sautillement).
- Pixelisation par blocs, palette du projet, conservation de la teinte, contour sélectif, nettoyage des pixels
  isolés, mesures chiffrées et alertes.

## 4. Si `chercher` ne trouve rien

Dans cet ordre, sans sauter d'étape :
1. Autres mots : synonymes simples en anglais (`jellyfish` → `medusa`, `squid`, `octopus`) et en français.
2. Sketchfab : si `usine_jetons.json` contient un jeton (rempli par l'humain), `chercher` y cherche aussi.
3. Un sujet PROCHE, puis `usine modeler` pour le transformer (section 5) : couper, ajouter, peindre, déformer.
4. Construire de zéro avec `usine modeler` (section 5, sans "base"). `usine gabarit` reste un raccourci pour
   méduse, algue, corail, cristal, rocher.
Jamais de dessin par code (Pillow, numpy) d'un sujet : tout passe par un modèle 3D, téléchargé ou construit ici.

## 5. Modeler : modifier un modèle ou en construire un, par CONTRAINTES

Tu ne donnes JAMAIS de coordonnées devinées. Tu nommes des zones et des contraintes ; l'usine calcule les nombres
exacts sur la vraie surface, puis MESURE le résultat (pièce enfoncée ? flottante ? symétrique ?).

**Étape 1 — la carte du modèle** : `usine analyser modeles/<id>/source/<fichier>`
→ REGARDE `modeles/<id>/analyse.png` : vue 1 = FACE (le sujet te regarde), 2 = son côté DROIT, 3 = son DOS, 4 = 3/4.
Les points rouges numérotés sont les zones (la liste numéro → nom est affichée). Si la vue 1 montre son dos,
mets `"retourner": true` dans `"modelage"`.

**Étape 2 — la recette** : ajoute `"modelage"` à `recettes/<id>.json` :
```json
"modelage": {"base": "modeles/<id>/source/<fichier>",
             "operations": [ {"faire": "...", ...}, {"faire": "...", ...} ]}
```
Sans `"base"` : on construit de zéro (sujet de 1 m). Toutes les longueurs sont des **fractions de H** (la hauteur
du sujet : `0.3` = 30 % de sa hauteur). Positions `[droite, avant, haut]` depuis le centre du sujet. Angles en degrés.
Directions : `haut`, `bas`, `avant`, `arriere`, `droite`, `gauche` (droite = SA droite), combinables (`avant-droite`),
ou `[droite, avant, haut]`. Zones : celles de `analyser` (`tete`, `dos`, `main_d`…, `os:<nom d'os>`, `haut`, `avant`…).
Squelette aux noms inhabituels : `"zones": {"main_d": "os:Palm.R"}` dans `"modelage"`.

**Étape 3** : `usine modeler recettes/<id>.json` → REGARDE `modeles/<id>/<id>_modelage.png` (4 vues, puis gros plan
de chaque pièce, puis la pose la plus forte de chaque animation créée) et lis les MESURES/ALERTES. Corrige UNE
opération, relance, regarde. Quand c'est bon : `usine variantes` / `usine fabriquer` comme d'habitude
(la recette pointe déjà sur le nouveau modèle, clé `"modele"`).

### Construire de zéro : les gabarits et l'opération `corps`

**Le plus simple : partir d'un gabarit** (`usine/gabarits/*.json`), puis ajouter tes opérations :

```json
"modelage": {"gabarit": "humanoide", "reglages": {"carrure": 1.3, "membres": 1.1, "couleur": "#c07040"},
             "operations": [ {"faire": "peindre", "quoi": "corps", "couleur": "#3a2a1c", "pres_de": "main_d"} ]}
```

| Gabarit | Pour | Réglages principaux |
|---|---|---|
| `humanoide` | humain, elfe, nain, chevalier, zombie | `carrure`, `membres`, `tete`, `mains`, `pieds`, `ecart_jambes` ; tenue : `couleur` (peau), `haut`, `bas`, `gants`, `bottes`, `ceinture`, `yeux` |
| `quadrupede` | loup, chien, cheval, cerf, félin | `carrure`, `pattes`, `museau`, `queue`, `couleur` |
| `serpent` | serpent, ver, anguille, tentacule | `epaisseur`, `couleur` |
| `arbre` | arbre, buisson, corail, bois de cerf | `longueur`, `rayon`, `niveaux`, `branches`, `angle`, `graine`, `feuillage`, `feuilles` |
| `maison` | maison, cabane | `largeur`, `profondeur`, `hauteur`, `toit`, `mur`, `couleur_toit`, `porte` |
| `coffre` | coffre, caisse, malle | `largeur`, `hauteur`, `bois`, `metal` |

Le gabarit `humanoide` utilise le squelette d'une bibliothèque d'animations : ses animations (marche, course, nage,
attaques…) s'y branchent avec `"animations_depuis": "<fichier de la bibliothèque>"` dans la recette de `fabriquer`.
Les autres corps reçoivent un squelette créé depuis leurs lignes (animations procédurales ou `animation`).

**L'opération `corps`** (ce qu'il y a dans les gabarits, utilisable directement) : des **lignes** de points avec une
**épaisseur à chaque point** donnent UNE peau continue (jamais de cubes ni de sphères visibles), avec son squelette.

```json
{"faire": "corps", "nom": "corps", "couleur": "#8a6a50",
 "lignes": [{"famille": "colonne", "points": [[0, -0.3, 0.55], [0, 0, 0.58], [0, 0.3, 0.6]], "rayons": [0.13, 0.14, 0.13]},
            {"famille": "patte_av_g", "points": [[0.1, 0.24, 0.56], [0.1, 0.26, 0.3], [0.1, 0.24, 0.05]], "rayons": [0.07, 0.05, 0.04]}]}
```
- `points` : [droite, avant, haut] en fractions de H ; `rayons` : un par point (l'épaisseur à cet endroit).
- `famille` : chaque membre a SA famille (deux jambes = deux familles, sinon elles se collent).
- `epaisseurs` : `{"famille": facteur}` ; `epaisseur` : facteur global ; `squelette`: false pour une forme sans os.
- `ramifier` (au lieu de `lignes`) : arbre, corail, bois — `{"longueur", "rayon", "niveaux", "branches", "angle", "graine"}`,
  et `feuillage` : `{"couleur", "rayon"}` pour des masses de feuilles au bout des branches.
- Pour les formes à **arêtes nettes** (murs, toits, caisses) : `piece` `bloc`, `lame` (avec `"lisse": 0`), `tour`, puis
  `soustraire` pour les ouvertures.

- `tenue` : couleurs par ZONES du squelette, `[{"os": ["hand"], "couleur": "#6e4a2c"}, {"os": ["calf", "foot"], "couleur": "#3a2e27"}]`
  (chaque face prend la DERNIÈRE règle dont un mot est dans le nom de son os ; `sauf` : mots exclus). Gants, bottes,
  ceinture, pantalon, manches : sans pièce en plus.
- Un point peut être un os : `{"os": "Head", "bout": "tete"|"queue", "decalage": [d, a, h], "ecarter": 0.02}`
  (`ecarter` éloigne le point de l'axe du corps, de côté). Une ligne peut imposer son os parent : `"parent": "<famille>"`.
- **Ajouter une forme au corps** (yeux, cornes, oreilles, crête) : un 2e `corps` avec `"piece": true` dont les points
  sont des os : la pièce SUIT cet os (la tête tourne, les yeux suivent).

**Choisir plutôt que régler** : `usine variations recettes/<id>.json` construit 6 versions (proportions tirées autour
des réglages ; la 1 = la recette actuelle) et fait une planche en **silhouettes noires** (face, côté) + couleur.
Choisis la plus lisible et la plus caractéristique : `usine choisir_variation recettes/<id>.json <numero>`.
`"variations_figees": ["tete"]` dans `modelage` = réglages à ne pas faire varier ; `"graine_variations"` = autre tirage.

**Références** (avant de construire un sujet que tu ne connais pas bien) : `usine references "<sujet en anglais>"`
→ planche de 10 images libres (source et licence dans `sources.json`), puis
`usine choisir_references "<sujet>" 2 5` → `references/<sujet>/choix.json` avec leurs repères (couleurs dominantes,
contraste). Sers-t'en pour la forme, les proportions et les couleurs ; **ne copie jamais une image**.
Si `usine_projet.json` contient `"galerie_qualite": "<dossier>"` (exemples du niveau visé, privés), ses images
s'ajoutent à la planche en numéros jaunes : c'est le niveau à atteindre. Ne les copie jamais dans le projet.
La galerie est rangée en sous-dossiers par famille (`personnages`, `creatures`, `decors`, `tuiles`, `fonds`, `effets`,
`interface`) : ajoute `--famille <f>` (celle de ton asset) pour voir les bons exemples (8 au plus).
`--pixel` ajoute jusqu'à 4 exemples **pixel art** libres (numéros bleus) : seulement pour voir comment on simplifie
le sujet (un œil en 2 pixels, un reflet). Il y en a souvent peu ou pas : la forme vient des images réelles, le style
vient du canon du projet.

### Les opérations (`"faire"`)

| faire | sert à | clés |
|---|---|---|
| `piece` | créer une pièce | `nom`, `forme` + ses clés (ci-dessous), `couleur`, `emission` (lumière), `alpha` (transparence), `a` [d, a, h] (position) |
| `importer` | prendre un autre modèle téléchargé comme pièce | `nom`, `fichier`, `couleur` ; puis REGARDE `piece_<nom>_6_cotes.png` et ajoute `avant_piece`, `haut_piece` (numéros des côtés) |
| `poser` | poser une pièce SUR une surface (contact sans enfoncement) | `quoi`, `sur` (`sujet` ou une pièce), `zone` ou `point`, `cote`, `taille`, `haut_vers`, `avant_vers`, `tourner`, `incliner`, `decaler`, `enfoncer`, `symetrique` + `ecart`, `os` |
| `englober` | coiffer une zone (casque sur la tête) | `quoi`, `zone`, `marge` (0.35), `decaler` ; mesure : % de la zone couvert |
| `placer` | mettre le centre d'une pièce à une position | `quoi`, `a`, `taille`, `haut_vers`, `avant_vers` |
| `symetriser` | copie miroir (patte droite → gauche) | `quoi`, `nom` |
| `couper` | couper en deux par un plan | `quoi`, `normale`, `hauteur` (0 = bas, 1 = haut) ou `point`, `noms` [bas, haut], `couleur_coupe` |
| `fusionner` | souder des pièces en UNE surface lisse | `quoi` [noms], `nom`, `couleur`, `finesse` |
| `soustraire` / `intersecter` | creuser / garder le commun | `quoi`, `outil` |
| `deformer` | étirer, gonfler, effiler, plier, tordre une région | `quoi`, `selon`, `de`, `a`, `etirer`, `gonfler`, `effiler`, `plier` + `vers`, `tordre`, `decaler`, `fondu` |
| `peindre` | colorer une région | `quoi`, `couleur`, `emission` + règles : `selon`/`de`/`a`, `normales_vers` + `seuil`, `interieur`, `pres_de`, `materiau` |
| `couleur` / `cacher` | recolorer / cacher une pièce ou un objet | `quoi`, `couleur` |
| `repartir` | N copies le long d'un bord, ou sur une zone (dents, écailles, pics) | `quoi`, `nombre`, `sur`, `le_long` {`normale`, `hauteur`, `retrait`} ou `zone` + `rayon`, `haut_vers`, `seulement` + `seuil`, `taille`, `ancre`, `enfoncer` |
| `charniere` | une pièce tourne sur un bord (couvercle, mâchoire, porte, aile) | `quoi`, `nom` (de l'os), `bord`, `axe`, `ouvre_vers`, `segments` (2 à 8 : la pièce se PLIE en n charnières en chaîne, os `<nom>`, `<nom>_2`… ; dans une clé, `{"<nom>": {"ouvrir": deg, "replier": deg}}` replie tous les plis suivants : aile qui se replie, queue qui s'enroule, cape, nageoire, feuille) |
| `squelette` | os le long des tubes + peau automatique | `chaines` [noms de tubes], `peau` [pièces] |
| `lier` | une pièce suit un os | `quoi`, `os` (sinon le plus proche) |
| `animation` | animation par poses clés | `nom`, `images`, `duree_ms`, `cles` [{`t` 0..1, `os` {…}, `racine` {`haut`, `avant`, `droite`, `tourner`, `grossir` (échelle : 1 = normal ; impact, saut, gonflement), `ecraser` (0.05–0.15 : plus bas et plus large, volume gardé)}, `tenir`: durée (la pose reste figée : impact)}], `anticipation` (0.2–0.4 : avant chaque grand geste, la pose part d'abord à l'opposé), `ondes` [{`chaine`, `amplitude`, `axe`, `decalage`}] |
| `reprendre` | reprendre l'animation d'un AUTRE modèle humanoïde | `fichier`, `action`, `nom`, `images` |
| `tissu` | cape, drapeau, voile qui flottent (vraie simulation) | `quoi` (une `lame` d'`epaisseur` 0, déjà posée), `fixer` {`selon`, `de`, `a`}, `raideur`, `poids`, `sur` |

**Formes de `piece`** : `tour` (`hauteur`, `rayon`, `profil` [[t, r]…] : bouteille, tonneau, cône, casque),
`tube` (`points` [[d, a, h]…], `rayons` : corps, cou, queue, membre, tentacule, langue), `masse` (`dimensions`
[l, p, h], `bosses` : tête, ventre, slime, rocher), `bloc` (`dimensions`, `arrondi` : caisse, machine),
`lame` (`contour` [[d, h]…], `epaisseur` : aile, nageoire, feuille, lame d'épée, cape).

**Poses d'un os dans `animation`** (`os` : nom d'os ou de zone) : `plier` (lever/baisser, autour de la droite du sujet),
`virer` (tourner gauche/droite), `rouler` (sur lui-même), `ouvrir` (charnière), `vers` (pointer EXACTEMENT vers une
direction), `atteindre` (le bout de l'os touche un point `[d, a, h]` ou `{"zone": ...}`, le coude plie tout seul ;
`coude_vers` : direction du coude).

**Détail fin : `relief`** (après la forme) : `{"faire": "relief", "quoi": "corps", "type": "plis", "zones": ["Leg", "Arm"],
"force": 0.008, "echelle": 0.035}`. Types : `bosses` (pierre, écorce, peau rugueuse), `plis` (manches, pantalon, cape :
anneaux autour de `selon`), `stries` (bois, écailles allongées). `zones` = noms d'os (seulement la peau de ces os) ou
région `de`/`a` le long de `selon`. `force` et `echelle` en fraction de la taille du sujet. Un relief trop fin pour la
taille du sprite disparaît : regarde le sprite, pas seulement le modèle.

**Gabarits de familles** : `humanoide`, `quadrupede`, `dragon` (volant : ailes à charnière `aile_d` / `aile_gauche`),
`serpent`, `arbre`, `coffre`, `maison`.

Le gabarit `humanoide` fournit l'animation `debout` (bras le long du corps) : `"animations": {"debout": {"action": "debout", "images": 1}}` pour une image fixe sans pose en T. `dragon` fournit `vol` et `repos` (ailes repliées).

Gestes qui claquent (tout squelette) : `"anticipation"` sur l'animation, `"tenir"` + `"ecraser"` sur la clé d'impact, et dans la recette `"animations": {"<tag>": {"action": ..., "trainee": true, "boucle": false}}` : sur un geste rapide la forme s'étire entre deux images. Exemple : `attaque` du gabarit `humanoide`.

**Blender ne fait PAS** : tuiles, fonds (parallaxe), interface, menus, icônes, effets. L'agent les fait avec l'outil de son choix.

**Une valeur de goût ?** Remplace-la par `{"affiner": [min, max]}` (une seule à la fois) → `usine affiner
recettes/<id>.json` → REGARDE `modeles/<id>/affinage.png` (6 essais numérotés) → `usine choisir_affinage
recettes/<id>.json <numéro>`. Recommence avec un intervalle plus étroit si besoin.

### Exemples complets

Plongeur (base téléchargée + bouteilles construites + casque téléchargé) :
```json
{"faire": "piece", "nom": "bouteille", "forme": "tour", "hauteur": 0.3, "rayon": 0.045,
 "profil": [[0, 0], [0.03, 0.9], [0.08, 1], [0.82, 1], [0.92, 0.7], [1, 0.3]], "couleur": "#e0b020"},
{"faire": "poser", "quoi": "bouteille", "zone": "dos", "symetrique": true, "ecart": 0.05},
{"faire": "importer", "nom": "casque", "fichier": "modeles/divers_helmet/source/Diving_Helmet.obj", "avant_piece": 3, "haut_piece": 5},
{"faire": "englober", "quoi": "casque", "zone": "tete", "marge": 0.4}
```
Mimic (un coffre téléchargé qui devient un monstre) :
```json
{"faire": "couper", "quoi": "sujet", "normale": "haut", "hauteur": 0.62, "noms": ["caisse", "couvercle"]},
{"faire": "peindre", "quoi": "caisse", "couleur": "#6a1426", "interieur": true},
{"faire": "charniere", "quoi": "couvercle", "nom": "machoire", "bord": "arriere-bas", "axe": "droite"},
{"faire": "piece", "nom": "dent", "forme": "tour", "hauteur": 0.12, "rayon": 0.035, "profil": [[0, 1], [1, 0]], "couleur": "#f0ead0"},
{"faire": "repartir", "quoi": "dent", "nombre": 7, "sur": "couvercle", "le_long": {"normale": "haut", "hauteur": 0.03, "retrait": 0.05}, "haut_vers": "bas", "seulement": "avant"},
{"faire": "animation", "nom": "mordre", "images": 8, "cles": [{"t": 0, "os": {"machoire": {"ouvrir": 5}}},
  {"t": 0.5, "os": {"machoire": {"ouvrir": 60}}, "racine": {"haut": 0.15}}, {"t": 1, "os": {"machoire": {"ouvrir": 5}}}]}
```
Créature de zéro (sans `base`) : des `tube` pour le corps, le cou, la queue et les pattes, des `masse` pour la tête,
`symetriser` les pattes, `fusionner` le tout, `peindre` le ventre, `lame` + `charniere` pour les ailes,
`squelette` sur les tubes, puis `animation` (pattes : `plier` ; queue : `ondes`).

### Matières : comment chaque partie prend la lumière

`"matiere"` sur `piece`, `corps`, `couleur`, `peindre`, `importer` (et dans un `"feuillage"`) ; `"matiere_tenue"` sur
un `corps` habillé (défaut `tissu` ; `metal` pour une armure). Toujours dans le canon du projet (mêmes rampes, mêmes crans) :

| matière | rendu | pour |
|---|---|---|
| `mat` (défaut) | lumière simple | bois, cuir, carton |
| `metal` | cœur sombre + éclat blanc franc | armure, épée, ferrures, casque |
| `brillant` | petit éclat | écailles, yeux, verre, corne, vernis |
| `tissu` | ombre douce, jamais d'éclat | vêtements, voiles, cape |
| `peau` | ombres adoucies | peau, chair, fourrure courte |
| `rugueux` | la lumière se brise en plaques | pierre, écorce, croûte, crépi |

Ce qui a `"emission"` reste clair (pas d'ombre). Les ombres de contact (une partie sur l'autre, creux) sont
automatiques ; `"ombre_contact": 0` dans le canon les coupe, `"matieres": false` revient au rendu d'avant.

## 6. Sorties pour le moteur (clés de la recette, pour `fabriquer`)

| Clé | Effet |
|---|---|
| `"directions": 4` (ou 8) | le même sujet vu de 4/8 côtés ; tags `<anim>_face`, `_droite`, `_dos`, `_gauche`… |
| `"normales": true` | carte de normales (éclairage dynamique) : `assets/sprites/<id>/<id>_normales.png` |
| matériau avec `emission` | masque de lumière émise : `assets/sprites/<id>/<id>_emission.png` |
| `"points": {"main": "main_d", "bouche": "os:Jaw"}` | position de ces points sur CHAQUE image |
| `"boites": {"coup": "os:hand_r", "corps": "<objet>"}` | boîte de chaque zone sur chaque image (hitbox, hurtbox) |
| `"evenements": {"pas": {"contact": "pied_d"}, "coup": {"images": [3]}}` | images où l'événement a lieu (`contact` : un point de `points` ou une zone comme `pied_d`) |
| `"duree_ms"` dans une animation | durée de chaque image (aussi dans le fichier Aseprite) |
| `"secondaire": [{"chaine": "queue", "retard": 0.08, "force": 1}]` | mouvement secondaire : les os dont le nom commence par `chaine` (queue, cheveux, oreilles, sac, tentacule) traînent derrière le corps puis rattrapent ; `retard` en part du cycle par os, `force` 0..1 |

| `"elan": 0.6` dans une animation | la préparation dure plus longtemps, le coup part vite (attaque, saut) ; 0 = régulier |
| `"boucle": false` dans une animation | animation qui ne boucle pas (attaque, mort) : pas de contrôle d'à-coup de boucle |

Contrôles d'animation (mesures `animation` de `fabriquer`) : **mouvement** (part de la silhouette qui bouge ; alerte
sous 3 %) et **saut de boucle** (dernière image → première, comparé à un pas normal ; alerte au-dessus de 2,5).
Un fond à 3 plans = 3 recettes du même gabarit : le plan lointain plus petit, plus sombre et moins saturé.

Tout est écrit dans `assets/sprites/<id>/<id>_donnees.json` (origine au sol, boîte visible, points, boîtes,
événements, durées), en pixels du sprite.

## 7. Retouche au pixel près (en dernier, et peu)

`usine grille build/sprites/<id>/pixel/<image>.png` → REGARDE `<image>_grille.png` (x en haut, y à gauche).
Puis dans la recette : `"retouches": [{"image": "<tag>_<nn>", "pixels": [[x, y, "#rrggbb"], [x, y, "transparent"]]}]`
et `usine fabriquer`. Garde les couleurs listées par `grille`. Au-delà de 5 % des pixels d'une image, l'usine
alerte : c'est le modèle ou la recette qu'il faut corriger, pas le dessin.

## 8. Si une commande plante ou bloque

Une commande qui plante (`Traceback`, `Error`) ou un résultat faux que la recette ne corrige pas après des essais
honnêtes : note-le dans `BUGS_USINE.md` à la racine du projet (commande exacte, 15 dernières lignes du message,
fichier ou modèle en cause, opération de la recette, ce que tu as essayé, ce que tu as fait à la place), puis
continue autrement : un autre numéro de `chercher`, une autre opération, ou l'asset mis de côté. Ne modifie jamais
le code de l'usine : l'humain transmet ce fichier pour qu'elle soit corrigée.
