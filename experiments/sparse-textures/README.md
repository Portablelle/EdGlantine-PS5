# Résidence sparse des textures : laboratoire PS5 NX2

État : audit et tests host réussis sur `build-server`, bibliothèque de diagnostic
cross-compilée PS5. **Pas d'intégration au moteur, pas d'activation sparse par
couche, pas de déploiement.** Ce document décrit le jalon initial sur 00.005.000. Le gestionnaire intégré ensuite
dans 00.006.000 est décrit par `../../milestones/sparse-layers/README.md` ; il
utilise une résidence complète avant publication, sans dépendre de trous à zéro.

## Résultats vérifiés dans le pilote épinglé

RADV PS5 : `7b59ef27c1b09b9671bc4153c41940c3155c3af2`.
Sources examinées : copie réellement préparée pour le build sous
`/work/mihawk-vulkan-review/.deps/work/radv-src` sur le dédié.
Les hashes des unités testées figurent dans
`../../artifacts/sparse-audit/source-hashes.json`.

- Le winsys renseigne `has_sparse=true`, `has_sparse_cpu_binds=true` et
  `has_sparse_prt=false`. RADV annonce `sparseBinding` et
  `sparseResidencyImage2D` si les queues sparse ne sont pas désactivées.
  Les familles graphics/compute exposent alors le bit de binding sparse.
  Ce sont des conclusions du code épinglé, pas une interrogation de la PS5.
- `shaderResourceResidency` et `residencyNonResidentStrict` restent faux.
  Les plages non liées pointent vers un bloc physique partagé de 2 Mio,
  initialement mis à zéro. Une écriture peut en changer le contenu : il ne
  constitue donc pas une garantie de zéro pour les futures lectures de trous.
- La granularité Vulkan 2D est exprimée en **texels** : 128×128 pour RGBA8,
  256×256 pour BC3, soit 64 Kio par tuile dans les deux cas. Le bind convertit
  ensuite les coordonnées BC en blocs compressés. Il ne faut pas réappliquer
  le facteur 4 du format au résultat Vulkan dans ce pilote.
- Le chemin GFX9+ sépare les couches puis les mips et utilise des mip tails par
  couche. Les offsets/strides/taille réels restent à demander après création de
  chaque image via ses sparse memory requirements ; ils ne se déduisent pas
  seulement des dimensions ou du format.
- Le mapping PS5 impose des multiples de 16 Kio. Les plages virtuelles sont
  réservées par granules de 2 Mio, tandis que les bindings peuvent être plus fins.
- Les bindings CPU attendent les sémaphores fournis avant de modifier les mappings.
  Un mutex de soumission ne remplace pas l'attente de fin des travaux GPU utilisant
  les anciens mappings.
- Les binds ne sont pas transactionnels : un échec sur la seconde rangée peut
  laisser la première liée. Même problème pour un unbind en plusieurs morceaux.
  L'appelant ne peut pas déduire « aucun mapping modifié » d'un résultat d'échec.

## Ce qui a été préparé

`probe.c`/`probe.h` interrogent les capacités physiques, la famille choisie et le
format avec les usages demandés. Le diagnostic distingue disponibilité physique
et activation sur le device logique. Il n'alloue aucune image et ne soumet aucun
travail. La demande expérimentale est explicite ; le cas désactivé est testé.
Pour le premier design qui suppose des trous lisibles à zéro, le diagnostic
bloque lorsque `residencyNonResidentStrict` est faux. Ce n'est pas une affirmation
que tout usage sparse du pilote serait interdit : un design garantissant des
accès uniquement à des sous-ressources résidentes doit être étudié séparément.

`extract-driver.py` extrait les fonctions de production des unités RADV, sans
réécrire leur algorithme. Le harness remplace le device, le winsys et les appels
système par des mocks qui enregistrent les mappings et injectent les erreurs.
Les tests exécutent les calculs et l'ordre des appels réels, sous ASan/UBSan :

- granularités RGBA8 et BC3 ; offsets de couche et de mip ; tuiles de bord ;
- plusieurs rangées, mip tail opaque et unbind ;
- attente avant mapping et refus de mapper si l'attente échoue ;
- erreur après un premier bind et un premier morceau d'unbind ;
- alignement PS5, débordements de plages et indisponibilité du bloc partagé ;
- diagnostic désactivé, fonctionnalités non activées, queue/format refusés,
  absence de garantie de zéro, listes dépassant les bornes du diagnostic.

Tous passent. `run-dedicated.sh` compile aussi `probe.c` avec `prospero-clang`
et crée `libnx2-sparse-probe.ps5.a`. Ce fichier est une bibliothèque de diagnostic,
**pas un ELF à lancer ni une nouvelle version de l'émulateur**. Il n'est lié à
aucun paquet existant. Les tests n'exécutent ni le GPU ni les API mémoire PS5.
Journal et artefacts : `../../artifacts/sparse-audit/`.

## Prochaine tranche de portage

1. Ajouter un planificateur par image/couche à partir des vrais requirements :
   granularité, alignement, memoryTypeBits, mip tails individuels ou partagés,
   metadata et tailles vérifiées sans débordement. Prévoir des plafonds globaux
   adaptés au pool partagé PS5 ; ne pas copier les budgets PC par image.
2. Choisir une sémantique sûre pour les trous. Sans PRT strict, garder l'image
   classique par défaut. Étudier des vues limitées aux couches résidentes et
   rendre résidentes toutes les destinations avant transfert, ASTC compute ou
   rendu. Les échantillonnages et filtrages pouvant franchir une limite doivent
   également être couverts ; une simple liste de couches écrites ne suffit pas.
3. Gérer explicitement le cycle alloué → partiellement lié → lié → en usage →
   retiré → délié → libéré. En cas d'échec partiel, conserver les allocations
   susceptibles de rester mappées jusqu'à récupération prouvée ou destruction
   contrôlée du device. Le `roll_back()` d'Eglantine qui libère après échec de
   BindSparse ne peut pas être copié tel quel.
4. Synchroniser les anciens utilisateurs GPU, le bind, puis les uploads/décodages
   et les nouveaux lecteurs. Traiter aussi les autres queues. Tester remappage,
   destruction et erreurs de fence ; `submit_mutex` seul ne suffit pas.
5. Relier le propriétaire de résidence au tracker NX2 déjà importé, sans doubler
   les notifications de pages. Une fois ces invariants couverts sur le dédié,
   intégrer derrière une option désactivée et compiler une variante distincte.

Aucune modification des flags de capacités du pilote n'est nécessaire à ce stade.
Forcer PRT/strict à true sans implémentation créerait une fausse promesse.
La validation ultérieure sur console devra confirmer les requêtes réelles,
les données lues après bind/remap, les barrières et le rendu sous pression mémoire.
Elle nécessite une tâche autorisant explicitement la console.
