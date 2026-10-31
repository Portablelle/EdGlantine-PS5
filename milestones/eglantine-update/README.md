# Eglantine — intégration PS5 00.008.000

Source examinée : Djihads80/Eglantine, `b40ad217ab829226841cb71f6e4c5cb05977a225`.
Diff depuis notre référence `6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba` ;
optimisation ASTC issue de `97ce27ab35153884d2fd05c278433928e429cd91`.
Les patches source sont conservés ici pour provenance ; ce ne sont pas des
patches à réappliquer sur le prototype final.

## Adaptations

- Fin des suites de pages physiques contiguës lors d'un map/unmap ; remise à
  zéro des compteurs des pages remplacées, y compris mapping sans suivi et trou.
  Le backing CPU du port et les générations de traduction restent conservés.
- Cache Vulkan : rejet d'un en-tête tronqué, écriture temporaire dans le cœur.
  Le port PS5 avait déjà une écriture atomique générée : elle reste conservée,
  avec attente du worker de sérialisation et sauvegarde uniquement si nécessaire.
  Une erreur de sauvegarde conserve l'ancien fichier valide.
- Notifications docké/portable : événement de rafraîchissement réservé NX2,
  propagation depuis ApplySettings, détection des vrais changements de mode.
  L'interprétation de la commande 210 reste celle, expérimentale, du fork.
- Dumps ExeFS : lecture du NACP et des icônes dans le dossier du jeu, y compris
  l'arborescence updates/title-id/exefs ; version NACP prioritaire. À défaut,
  repli sur ResourceSizeTable.Product.NNN du RomFS voisin, heuristique qui ne
  distingue pas nécessairement les hotfixes ; aucun parsing du nom du dossier.
- ASTC : sélection des couches touchées à partir de notre suivi des pages sales,
  restauration des compteurs de pages une seule fois, décodage Vulkan par couche
  et par mip, staging par lots visant 32 Mio (une couche peut dépasser ce budget).
  Les images >=64 Mio éligibles utilisent cette optimisation ; les autres chemins
  conservent le transfert complet. Les transcodages ASTC vers BC, images rescalées,
  décodages asynchrones, images sans backing ou à mapping sparse invité sont exclus.
  Les niveaux conservés après suppression des grands mips sont respectés.
- Libération à la frame suivante des scratch CPU d'upload dépassant 64 Mio et
  compteurs des volumes d'upload pour les comparaisons futures.
- Tests RET R0/R55 du fork adaptés à notre validation explicite du mot haut du
  registre de retour ; la correction RET elle-même était déjà dans notre moteur.

Le suivi ASTC utilise le même réglage `tex_partial` que les transferts partiels
existants : le désactiver rétablit les uploads complets. Les allocations Vulkan
restent résidentes ; aucune hypothèse de lecture à zéro des trous n'est ajoutée.
Les budgets sparse de 00.006 sont inchangés et restent opt-in.

## Hors intégration

- « FSR3 » et génération d'images : implémentation expérimentale présentant des
  problèmes de gestion de l'historique ; pas importée.
- Forcer le type d'une vue Vulkan 2D/3D différent de celui attendu par le shader :
  contournement MoltenVK insuffisant pour garantir la validité du sampling PS5.
- UI Qt/Android et scan de bibliothèque Qt : non utilisés par le frontend PS5.
- Résidence sparse sélective et allocation paresseuse des régions GPU : demandent
  une adaptation propre au pilote PS5 ; non activées par cet import.
- Nettoyage de l'historique QMD : rejet précédent conservé.

Le correctif gather Welcome Tour et la trace du refus de codec vidéo sont
coordonnés avec l'autre chat ; voir ../gather-panic/ANALYSIS.md. Cette version
ne fournit pas de décodeur VP8 et n'est pas annoncée comme corrigeant le PANIC.

## Validation

Compilation et tests exclusivement sur `build-server`, copies isolées sous
`/tmp/ps5-nx2-prototype-20261030`. Image native : `botty-standalone-build` ;
image des tests moteur Linux : `nx2-host-tests-build` (contient OpenSSL).
Validation finale : 395 cas / 1,877,310 assertions réussis, contrôles natifs
et du paquet réussis. Voir `../../artifacts/eglantine-update/TEST-REPORT.md`.
