# Analyse des onze échecs shaders — prototype NX2

Périmètre : prototype indépendant PPSA99862, sources Eden-NS2 épinglées à
`e2f285ab1ecd3a2475c2ccad66f23b06b94ead5c`. Compilation et tests sur `build-server`.

## Huit cas de contrôle de flux

Six tests d'annulation de barrières échouaient : sortie de portée interne,
annulation de deux barrières, conservation des parents, deux chemins de nettoyage
séparés et annulation interne à une jonction parent.
Le raccourci de BREAK acceptait l'annulation dès qu'une portée SYNC englobante
existait, avant la preuve du chemin de sortie. Il acceptait donc des variantes
qui changeaient le prédicat ou revenaient vers une portée annulée. Pour deux
BREAK consécutifs, il ignorait le premier sans enregistrer la chaîne validée :
le second était ensuite confronté au mauvais jeton interne et rejeté.
Suppression de ce raccourci : les preuves existantes du chemin linéaire ou du
chemin de contrôle s'exécutent, puis marquent ensemble les annulations validées.
Les tests suivent toujours les deux branches du CFG Maxwell et vérifient les
jonctions, les nettoyages, la terminaison et les chemins qui ne doivent pas être
visités. Les variantes négatives sont conservées.

Le raccourci CALL.REL.NOINC qui saute une branche arrière contournait également
la preuve du nettoyage d'une portée active. Il est désormais limité aux boucles
sans portée, ou au cas déjà explicite d'une jonction immédiate. Dans une portée,
le contrôle existant du nettoyage exclut les retours en arrière, les sorties de
portée et les formes de nettoyage non prouvées.

Enfin, WARPSYNC après BSYNC pouvait devenir un NOP lorsque la cible BSSY ne
correspondait pas à cette jonction. Cette incohérence est rejetée. Le chemin
valide conserve sa barrière mémoire ; les trois jetons testés restent couverts.

Ces corrections rendent la traduction plus conservatrice pour les chemins dont
la validité n'est pas prouvée. Elles n'établissent pas à elles seules la sémantique
de toutes les formes de contrôle Ampere ni la compatibilité d'un jeu complet.

## Trois attentes négatives devenues obsolètes

- AST vectoriel depuis RZ : le traducteur scalarise déjà les composantes pour
  éviter un débordement du numéro de registre. Le test vérifie maintenant les
  deux, trois et quatre attributs consécutifs et leur lecture de RZ dans l'IR.
- TEX cube-array LOD zéro : le chemin TEX général produit déjà un échantillonnage
  à LOD explicite nul. Le test vérifie le type cube-array, le descripteur, le LOD,
  les quatre coordonnées et les copies RGBA vers les destinations séparées.
  L'autre variante négative, registre source mal aligné, est conservée.
- RED.E.MIN U32 : le bit modifié sélectionnait MIN, déjà traduit, et non une
  instruction invalide. Le test exécute maintenant MIN et MAX pour 25 couples
  de valeurs chacun, dont les limites signées/non signées, en contrôlant le
  pointeur 64 bits, la mémoire voisine et tous les registres/prédicats.
  Le pointeur impair et les bits de mode invalides restent rejetés.

Aucun des onze cas n'est exclu par un filtre et aucun test n'est marqué en échec
attendu. Les résultats définitifs et les limites de validation figurent dans
`TEST-REPORT.md` à la racine du prototype.
