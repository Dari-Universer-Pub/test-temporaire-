# Gabarits de formes

Chaque fichier `<nom>.json` est un gabarit : une liste d'operations de `modeler` (souvent une operation `corps`) avec
des **reglages** (`"$cle"` dans les operations, valeur par defaut dans `"reglages"`). Dans une recette :

```json
"modelage": {"gabarit": "humanoide", "reglages": {"carrure": 1.3, "couleur": "#c07040"}, "operations": [ ...suite... ]}
```

Ajouter une famille de formes = ecrire un nouveau fichier ici (aucun code).

`humanoide_squelette.glb` : squelette seul de la Universal Animation Library (Quaternius, **CC0**), sans mannequin ni
animation. Les animations de cette bibliotheque (marche, course, nage, attaques...) s'y branchent avec
`"animations_depuis"` dans la recette de `fabriquer`.

Un gabarit peut contenir plusieurs operations : `humanoide` = le corps (avec sa `tenue` par zones du squelette) puis
les yeux (`corps` avec `"piece": true`, poses sur l'os `Head` : ils le suivent). `usine variations` fait varier les
reglages numeriques d'un gabarit pour proposer 6 silhouettes.
