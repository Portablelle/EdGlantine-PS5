# Donkey Kong Bananza : retours répétés au démarrage

État au 2 novembre 2026. Programme **040074A01BF12000**, app **PPSA99862**.

## Symptôme et preuve

Le joueur décrit un retour au « starting menu » d’EdGlantine. Les logs montrent
`EDEN_GUEST_FAULT_RETRY` : le frontend relance le jeu dans le même processus.
Dans les premiers relevés, aucun reboot de la PS5 ni crash natif associé n’était établi.
Le second relevé ci-dessous identifie ensuite un crash natif distinct.

Dans le relevé `artifacts/bananza-reboot/`, `Too many open files` apparaît avant
les accès nuls et le saut vers une adresse non mappée :

- 133,260 s : ouverture d’une texture refusée ;
- 133,389 s : ouverture d’une ressource ELink2 refusée ;
- 133,391 s : première lecture nulle ;
- 133,417 s : tentative d’exécution à l’adresse 0 ;
- 134,053 s : première relance automatique, après environ 3,5 s de session.

Quatre relances sont enregistrées, avec le même type de défaillance. Les erreurs
ultérieures de sauvegarde des paramètres/playtime sont aussi des échecs
`Too many open files`. Ne pas les traiter d’abord comme un problème de permissions.
Ne pas commencer par modifier les shaders ou les réglages GPU pour cette séquence.

## Défaut et correction installée

Le port limitait le cache LRU de **chaque** `RealVfsFilesystem` à 512 fichiers
ouverts (amont : 8 192). Le quota du processus est partagé avec les autres VFS,
les logs, les services et les pilotes : ce plafond peut laisser trop peu de marge.
Le quota effectif de la PS5 n’a pas été mesuré ; ne pas l’inventer à partir de
`OPEN_MAX` ou `FOPEN_MAX` des headers SDK. Aucune fuite de descripteurs n’est
encore démontrée par ces seuls logs.

La correction :

1. Borne le cache à **64 fichiers ouverts par VFS**, avec la logique LRU existante
   qui ferme puis rouvre les fichiers selon les besoins.
2. Enregistre spécifiquement les erreurs `EMFILE`/`ENFILE` dès l’échec de `fopen`,
   avant que le logging puisse changer `errno` ; ne confond pas ENOENT/EACCES.
3. Réinitialise ce signal avant chaque lancement. Si une faute guest suit une
   saturation, présente une erreur claire au lieu de recommencer les relances
   automatiques prévues pour des races de démarrage transitoires.

Le marqueur `EDEN_HOST_FILE_POLICY cached_per_vfs=64` doit confirmer la politique
au lancement. Cela ne garantit pas à lui seul que le jeu atteint le gameplay.

## Vérification ciblée

`eden/tests-nx2/check-vfs-file-budget.py` utilise les véritables méthodes de gestion
LRU extraites de la révision embarquée, avec un quota Linux RLIMIT_NOFILE de 96.

- Ancien plafond 512 : saturation EMFILE reproduite.
- Nouveau plafond 64 : 512 lectures/réouvertures de 256 fichiers, contenus vérifiés,
  fermeture finale de tous les descripteurs et classification des erreurs réussies.
- Chemin corrigé vérifié sous ASan/UBSan. La baseline volontairement saturante est
  exécutée sans ASan : l’intercepteur ASan lui-même échoue à créer un pipe lorsque
  tous les descripteurs sont occupés, ce qui invalide ce scénario de test instrumenté.

Ce test ne simule pas toutes les autres consommations du processus PS5. La
validation console reste nécessaire : disparition des erreurs d’ouverture, arrêt
de la boucle et progression effective dans Bananza. Si la saturation persiste,
mesurer les descripteurs et les détenteurs avant d’augmenter le quota ou de
présenter le problème comme résolu.

## Provenance

- Captures : `artifacts/bananza-reboot/` (ignorées par Git).
- Politique/signal : `eden/headless/host_file_pressure.h`.
- Adapters IOFile/VFS : `eden/headless/CMakeLists.txt`.
- Décision de relance : `eden/headless/main.cpp`.
- Build isolé sur dedie : `/tmp/edglantine-game-library-20261101`.
- Log du test : `vfs-file-budget-test.log` ; build : `bananza-file-budget-build.log`.

Les corrections et réglages Pokopia sont une investigation distincte, consignée
à côté dans `POKOPIA_RENDERING_INVESTIGATION.md`. Préserver dumps et sauvegardes.

Le correctif a été compilé sur dedie et installé avec backup du binaire précédent.
Artefact/journal : `artifacts/00.065.000-bananza-file-budget/`.
## Essai console après correction du plafond de fichiers

Relevé : `artifacts/bananza-file-budget-retest/20261102-003117/`.
Le marqueur confirme `EDEN_HOST_FILE_POLICY cached_per_vfs=64`. Dans cette
session, plus de `Too many open files` ni de `EDEN_GUEST_FAULT_RETRY` : la
saturation de fichiers observée initialement n'est plus reproduite.

Un **autre échec natif** survient toutefois :
`crash-20261102-004056.txt`, programme Bananza, thread GPU,
`std::bad_alloc`, 44 s après le démarrage de l'app. Le frontend redémarre après
ce crash. Ne pas confondre ce redémarrage avec les anciens retries guest.

- Tas : limite de 3 072 Mio atteinte ; dernier échantillon de mémoire vivante
  3 065 123 283 octets, contre 764 584 367 à `game_loaded`.
- Dernière allocation refusée : **16 777 248 octets**. La console dispose encore
  d'un bloc libre de 6 628 Mio : c'est le budget du tas, pas un épuisement de toute
  la RAM de la PS5.
- Symbolisation avec l'ELF exact encore présent sur dedie : la pile contient
  `VideoCommon::DescriptorTable<Tegra::Texture::TSCEntry>::Refresh` à `0x2358237`,
  puis `GraphicsPipeline::ConfigureImpl` à `0x2553a6d`. Les entrées de pile du
  rapport sont des candidats non validés comme instructions d'appel ; la taille
  refusée correspond aussi à la préallocation de 524 289 entrées de 32 octets.
- Aucun FPS de gameplay exploitable avant l'arrêt. Ne pas annoncer que Bananza
  fonctionne ou que le défaut mémoire est corrigé.

Piste à mesurer avant correction : le cache de lecture VFS conserve jusqu'à
8 blocs de 1 Mio **par fichier**, indépendamment de la fermeture LRU du
descripteur. Le `resize` après lecture ne réduit pas la capacité réservée pour
les petits fichiers. Ce mécanisme peut consommer beaucoup de tas sur un dump
RomFS contenant de nombreux fichiers, mais sa contribution au crash de cette
session n'est pas encore mesurée. L'allocation qui échoue n'identifie pas à elle
seule le principal détenteur de la mémoire. Ne pas augmenter aveuglément le tas
ou attribuer ce crash aux shaders.


## Correction du budget mémoire et prochain essai

Le test `eden/tests-nx2/check-host-memory.py`, exécuté sur dedie, extrait les
vraies méthodes Read/LRU et la table de descripteurs de la révision embarquée.
L'ancien code retient **268 435 456 octets pour 256 fichiers de quelques octets** :
chaque première lecture réserve 1 Mio, le redimensionnement après lecture
conserve cette capacité, et l'éviction du fichier ouvert ne libère pas ses blocs.
Cela démontre un mécanisme de surconsommation ; la part exacte des 3 Gio de la
session console précédente reste inconnue faute de compteurs par catégorie.

La nouvelle gestion :

- Cache VFS borné à **64 Mio pour le processus**, avec réservation atomique avant
  allocation. Au plafond, lecture directe correcte sans création d'une fausse
  entrée de cache ; les lectures futures peuvent revenir au cache.
- Prélecture bornée à la taille restante du fichier ; blocs libérés à l'éviction,
  à la destruction du fichier et à celle du VFS. Le test des 256 petits fichiers
  conserve moins de 1 Kio avec le nouveau code.
- Tables TIC/TSC : croissance géométrique à partir de 64 entrées, au lieu d'un
  minimum de 524 289 entrées. Aucun plafonnement des indices guest : l'indice
  inclusif maximal demandé reste accessible, dont les indices élevés Pokopia.
- Compteurs `EDEN_HOST_MEMORY` : mémoire réservée VFS et descripteurs, pics et
  lectures de contournement du cache. Émis au lancement, avec les relevés FPS et
  à l'échec d'allocation. Les pics sont ceux du processus, pas réinitialisés à
  chaque lancement de jeu.

ASan/UBSan : baseline reproduite ; lectures réouvertes, EOF, traversées de blocs,
budget plein puis libéré, relecture après fallback, comptabilité à destruction,
indices TIC/TSC inclusifs/élevés, rétrécissement/croissance, invalidation et
transfert par move réussis. Aucune suite générale supplémentaire lancée.

Sources : `eden/headless/host_memory_budget.h`,
`eden/tools/prepare-host-memory.py`, intégration CMake, compteurs main/graphics.
Build isolé : `bananza-host-memory-build.log` ; test : `host-memory-test.log`.
Artefacts locaux : `artifacts/00.065.000-bananza-host-memory/`.
La validation du démarrage effectif et la mesure de la RAM sur PS5 restent à faire.

Compilation et packaging sur dedie réussis ; binaire installé par remplacement
vérifié avec sauvegarde du précédent. Journal :
`artifacts/00.065.000-bananza-host-memory/install-journal.json`.
Prochain essai Bananza sur console en attente ; aucun succès de gameplay encore établi.


## Essai avec budget mémoire : démarrage atteint, rendu incomplet

Relevé : `artifacts/bananza-blue-render/20261102-005151/`.
Le joueur voit le texte, un fond bleu, aucune image. Le jeu reste actif au-delà
uniquement du précédent crash de 44 s ; aucun nouvel échec d'allocation dans
les logs récupérés. Mesures de fin de relevé : cache VFS 23 862 719 octets,
pic 41 119 635, budget 67 108 864, zéro lecture de contournement ; descripteurs
8 684 544 octets. Les derniers agrégats affichent 52–60 FPS, **rendu incomplet** :
ne pas présenter cela comme des performances de gameplay valide.

Nouveau blocage explicite : `DispatchNativeCompute` attrape les exceptions de
traduction et saute les dispatches natifs. Plus de 20 480 rejets à 127,8 s.
Premiers rejets à 80,688 s. Deux familles distinctes observées :

- `native barrier cancellation mode`, instruction `BREAK` opcode 0x942 :
  `00010942 00000000 00800000 000fe200` (ex. programme 0x29eb5fd000,
  offset 0x4720 ; 0x29ec244000, offset 0x2260), et
  `00030942 00000000 03800000 000fe200` (0x29171cbe00, offset 0x9f0).
  Le lowerer valide des formes spécifiques imbriquées ; ne pas supprimer ses
  vérifications ni transformer aveuglément ces barrières en NOP.
- Opcode non pris en charge 0x234, identifié `HSetP2` par la table de décodage
  embarquée : `34007234 30000034 00702800 000fe400`, programme
  0x291659c400, offset 0x2610, suivi de trois instructions du même opcode.

C'est une preuve de calculs GPU omis ; leur responsabilité exacte dans chaque
élément absent reste à valider après traduction correcte. Aucun indice ne
justifie de revenir au cache mémoire non borné pour ce symptôme.

Capture à chaud achevée : 1 draw, scope 0, fin à 191,103 s ; quatre régions
GPU de 64 Kio récupérées pour les programmes ci-dessus. Demande mémoire
7 régions : trois refusées car l'intégralité des 64 Kio n'était pas mappée,
aucun contenu inventé pour elles. Les captures retenues sont
`position-capture-draw-0-memory-{0,2,5,6}-*.bin` dans le relevé.
Elles confirment les mots exacts aux offsets signalés ; le contrôle de flux
et les opérations de comparaison doivent être reproduits avec ces vrais shaders
avant de compiler un correctif. Pas de nouvelle compilation ou installation
pour ce constat.


## Correction ciblée des shaders de calcul

Les quatre programmes récupérés reproduisent les rejets dans le vrai lowerer
sans modifier les captures. `ProgramCaptureState` délimite respectivement
33 040, 23 328, 41 648 et 3 792 octets ; ne pas traduire tout le bloc de 64 Kio,
qui contient aussi des données/programmes voisins.

Désassemblage de contrôle sur dedie avec l'outil NVIDIA nvdisasm 12.6.77,
SM87, paquet officiel dont le SHA-256 a été vérifié :

- `0x234` : `HSETP2.EQ.AND P0, PT, R52.H0_H0, R52.H1_H1, P0`
  (puis mêmes formes P1/P2/P3). Le lowerer prend maintenant en charge la forme
  registre avec swizzles, abs/neg, combinaison du prédicat, H_AND et FTZ.
  Les variantes de champs AND/OR/XOR, H_AND, FTZ, abs/neg ont été confirmées par
  désassemblage. La traduction utilise l'instruction HSETP2 Maxwell existante.
- Aux offsets 0x4720/0x2260, `@P0 BREAK P1, B1`, suivi de
  `@P0 BRA P1, ...` : les deux prédicats doivent être vrais pour quitter la
  boucle. La traduction de BRA conserve déjà ces deux conditions.
- Au 0x9f0 du programme 0x29171cbe00, `@P0 BREAK B3` suivi de
  `@P0 BRA 0xd30` : annule **seulement B3**, rejoint B2 à 0xdc0 après des
  mouvements de registres. B0/B1 restent actifs. L'ancien lowerer exigeait
  l'annulation de tous les scopes internes jusqu'au plus externe.

Le nouvel analyseur `VerifiedParentCancellation` n'autorise l'omission du BREAK
que si la branche suivante sélectionne exactement les mêmes deux prédicats,
sa destination dépasse le join interne, et le nettoyage arrive au BSYNC parent
par des mouvements/IMAD et branches inconditionnelles strictement vers l'avant.
Il marque ce parent comme SSY ; son SYNC élimine le PBK interne annulé en
conservant les scopes plus externes. Les formes non prouvées continuent à être
refusées ou traitées par les validateurs existants. Pas de suppression générale
ou aveugle des barrières.

Tests exécutés sur dedie sous ASan/UBSan :

- Les quatre programmes auparavant rejetés passent intégralement le lowering.
- 1 572 864 cas de comparaison : NaN, infinis, zéros signés, sous-normaux,
  swizzles, abs/neg, prédication, combinaison et alias du prédicat source/destination.
- Exécution du contrôle de flux Maxwell sur une annulation partielle à quatre
  scopes, avec les quatre combinaisons des deux conditions ; conservation des
  scopes parents, refus des chemins à backedge, mauvais token/prédicat ou BSYNC
  interne. Cela n'est pas une validation de rendu sur GPU réel ni de toute l'ISA.
- Non-régression ciblée FSEL : 1 040 vérifications, zéro mismatch corrigé.

Code : `eden/tools/prepare-float-select.py`, cache-tag Bananza `0x200` dans
`native_shader_policy.h`. Les politiques Pokopia FSEL et les protections VFS/tas
restent présentes. Diagnostic borné `NX2_BANANZA_COMPUTE` indique le nombre de
comparaisons/BREAK et le succès de traduction des 12 premiers programmes concernés.
Artefacts prévus : `artifacts/00.065.000-bananza-shaders/` ; compilation isolée
sur le même snapshot dedie que le binaire de l'essai bleu, pour ne changer que
les shaders. Les travaux mémoire/readback du chat parallèle, présents dans le
workspace mais absents de ce snapshot, ne sont pas intégrés silencieusement à
cet essai ciblé. Ne pas remplacer ce binaire cumulatif VFS/tas/shaders par
l'artefact indépendant `artifacts/memory-readback/` qui ne contient pas ces ajouts.
Compilation et packaging réussis sur dedie ; binaire installé par remplacement
vérifié avec backup. Journal : `artifacts/00.065.000-bananza-shaders/install-journal.json`.
L’app était fermée sur confirmation du joueur. Rendu complet et absence des rejets
restent à valider au prochain lancement Bananza.


## Après correction compute : cinématique visible, puis HUD seul

Relevé `artifacts/bananza-hud-only/20261102-010708/`. Le joueur confirme la
cinématique de début, puis le HUD sur une scène noire. Les marqueurs
`NX2_BANANZA_COMPUTE` montrent les formes corrigées avec `lowered=true` ; aucun
nouveau rejet de dispatch compute dans les logs récupérés. Ne pas revenir sur
ces corrections sans nouvel indice. Le cache VFS reste vers 33–35 Mio,
les tables vers 12,4 Mio. Les derniers agrégats tombent vers 17 FPS, toujours
avec scène incomplète ; ne pas les comparer comme FPS de gameplay normal.

Cause explicite du nouveau blocage : à 84,471786 s,
`CreateGraphicsPipeline: Read attribute Generic31Y is not implemented`, suivi
dès 84,473143 s de `Native graphics draw failed`, puis ~949 248 dessins refusés
à 195,27 s. Le pipeline nul est réutilisé ; le premier message donne la cause,
les milliers de messages suivants en sont la conséquence. Pas d'échec mémoire
établi sur cette capture.

Défaut reproduit dans `frontend/ir/attribute.h` : `IsGeneric` compare la borne
haute à **Generic31X** alors que la dernière composante valide est **Generic31W**.
L'enum contient bien X/Y/Z/W, valeurs 156–159, et `NUM_GENERICS=32`. L'erreur
empêche la lecture SPIR-V, mais aussi la collecte et les helpers d'indexation,
de reconnaître Y/Z/W. Corriger seulement l'émetteur SPIR-V ne suffirait pas.

Correction : header dérivé par `attribute_header` dans
`eden/tools/prepare-float-select.py`, partagé via un include prioritaire privé dans la
librairie shader_recompiler et video_core, pour garder une seule définition des
helpers inline. Enum et ABI inchangés. Cache-tag Bananza **0x201**, conservant
les corrections compute, tas et VFS de la version précédente.

Test ciblé sur dedie ASan/UBSan : rejet de Generic31Y/Z/W reproduit dans l'ancien
code ; les 128 composantes génériques passent dans le nouveau, avec index et
composante corrects ; les voisins hors plage restent rejetés et leurs helpers
continuent de lever une erreur. Script :
`eden/tests-nx2/check-generic-attributes.py`.

Artefacts : `artifacts/00.065.000-bananza-attributes/`. Build isolé identique au
précédent, sans intégration des modifications du chat parallèle. Le joueur a
confirmé la fermeture complète pour cette installation. Compilation et packaging réussis sur dedie ; binaire installé avec backup et
remplacement vérifié. Journal :
`artifacts/00.065.000-bananza-attributes/install-journal.json`.
La validation du monde 3D reste à faire sur console.


## Retour suivant : écran noir du lanceur, puis menu très lent

Relevé `artifacts/bananza-attributes-retest/20261102-012122/` : le premier log
moteur est vide, les logs de démarrage s'arrêtent au lanceur, `after_crash=0`,
aucun nouveau rapport natif. Le joueur précise ensuite que le noir est **dès
l'ouverture d'EdGlantine**, avant de sélectionner Bananza, puis que le menu
finit par apparaître mais rame depuis les imports Bananza/Mario Kart.
Ce relevé **ne valide ni n'invalide** la correction Generic31Y en jeu.

`EDEN_LAUNCHER ... ready_ms=62281`. Les lignes `slow frame` suivantes indiquent
update 293–1 030 ms, draw 0 ms, present 1 ms : le temps mesuré est dans la mise à
jour frontend (y compris input/IO), pas dans son dessin GPU. Le transfert Mario
Kart est simultanément actif dans le chat parallèle ; ne pas l'interrompre ni
modifier son répertoire de staging. Sa responsabilité exacte n'est pas mesurée.

Défaut de parcours confirmé dans le code : `eden_scan_addons` fournit les dossiers
de jeux à `ExternalContentProvider`. Son `ScanDirectory` descend sans exclusion
dans **tous** les sous-dossiers, y compris exefs et romfs des dumps déchiffrés.
Le menu demande ce scan dans `home()` et `games()`. Cela expose chaque lecture de
la bibliothèque à l'ensemble des ressources du dump, sans lien avec le nombre
de jeux. Ne pas attendre du seul plafond de descripteurs qu'il supprime ce coût.

Correction : `eden/tools/prepare-library-scan.py` adapte cette méthode dans le
`registered_cache.cpp` dérivé. En présence de `exefs/main`, la recherche des
add-ons ne descend plus dans les sous-dossiers exefs/romfs. Les packages à la
racine et leurs sous-dossiers updates/DLC restent analysés ; les dossiers cachés
sont ignorés, notamment les transferts encore non publiés. Les lectures de
ressources du jeu lui-même restent celles du VFS normal.

Test ciblé ASan/UBSan sur dedie, vraie méthode de récursion extraite avec VFS
simulé : baseline visite 262 144 ressources et un package de staging ; version
corrigée ne visite que les quatre fichiers add-on attendus. Vérifie aussi une
extension NSP majuscule, DLC imbriqué, package à côté du dump, et dossier nommé
romfs appartenant à un jeu sans exefs/main (toujours parcouru). Script
`eden/tests-nx2/check-library-scan.py`. Ce test ne mesure pas le temps réel PS5
ni toutes les causes possibles des frames lentes.

Binaire cumulatif prévu : `artifacts/00.065.000-library-scan/`, compilé sur le
snapshot dedie conservant les corrections shaders, attributs et VFS/tas. Le joueur
a confirmé la fermeture complète pour l'installation. Compilation et packaging réussis sur dedie ; binaire installé par remplacement
vérifié avec backup. Journal : `artifacts/00.065.000-library-scan/install-journal.json`.
Temps d’ouverture du menu et rendu 3D Bananza restent à valider sur console.


## Essai après exclusion des payloads dans la recherche d'add-ons

Relevé `artifacts/bananza-library-scan-retest/20261102-013203/`.
Le joueur confirme une ouverture plus rapide, mais des pauses intermittentes du
menu, puis un écran noir au lancement Bananza. `EDEN_LAUNCHER ready_ms=7312`,
contre 62281 au relevé précédent ; comparaison indicative, conditions IO non
identiques. Les pauses restantes mesurées sont toujours en update (139–1401 ms),
draw 0 ms, present 1 ms. Leur sous-étape n'est pas instrumentée : ne pas attribuer
sans mesure ces pauses à la lecture des préférences, au pad ou à un scan précis.

Pour Bananza, les deux relevés du log moteur restent vides et aucun FPS n'est
émis : il n'a pas encore atteint le rendu. La dernière étape de boot est
`dump.romfs.begin` à +46860 ms après ouverture de l'app, après le chargement des
NSO. L'inspection du code montre `ReadRomFS -> CreateRomFS -> RomFSBuildContext`
pour fabriquer l'image virtuelle depuis le dump loose. Le fait que la trace
s'arrête là ne prouve pas un deadlock ni un nouveau défaut de shader.

Le joueur a refermé l'app car le chargement ne terminait pas. Le transfert Mario
Kart simultané arrive bientôt à son terme. Prochain contrôle décidé : relancer
EdGlantine/Bananza **après** sa fin, avec le binaire actuel, afin de distinguer la
contention de ressources d'un défaut persistant. Aucun nouveau build ou réglage
appliqué sur la seule base de cette attente. Les corrections Generic31Y/Z/W et
le rendu 3D restent non validés sur console tant que le chargement n'aboutit pas.


## Lot upstream surface/query/profondeur/audio

Le joueur a autorisé les quatre adaptations issues de l'audit zortos293.
Voir `milestones/eglantine-update/README.md`, section intégration des quatre
correctifs, et patch `92-nx2-surface-query-depth-audio.diff`. Tests ciblés, compilation native et packaging sur
dedie réussis. Binaire installé avec backup ; journal dans
`artifacts/00.065.000-four-fixes/install-journal.json`. Les corrections précédentes sont
conservées, dont le skip de payloads dans la recherche d'add-ons et Generic31W.
Aucun lien établi entre ce lot graphique et l'attente précédente dans
`dump.romfs.begin` ; ne pas annoncer que le chargement ou le rendu est réparé
avant le prochain essai console. Dernier état confirmé par le joueur : app fermée.


## Revue Cubic avant commit/push

Deux points P2 de la revue locale ont été corrigés :

- La bibliothèque délègue maintenant la validation et l'extraction du programme
  au `FileSys::ProgramMetadata` canonique ; le NSO est identifié par
  `AppLoader_NSO::IdentifyType`. La détection Switch 2 ne parse plus deux fois
  le NPDM avec deux implémentations différentes. Le test de bibliothèque exécute
  le vrai parser et ses structures, avec fichiers simulés, sous ASan/UBSan.
- Patch `93-nx2-read-cache-ownership.diff` : l'allocateur du vecteur de bytes
  possède la réservation globale du cache. La destruction, le remplacement par
  move et l'unwind la rendent automatiquement ; aucun hook de destruction VFS
  n'est nécessaire pour tenir les compteurs. L'éviction continue de vider les
  blocs froids. Tests VFS/budget/déplacement/swap/exception et descripteurs PASS
  sur dedie sous ASan/UBSan.

Ces changements de revue ne sont pas déployés dans le binaire quatre-correctifs
installé précédemment. La première vérification native des changements NPDM/RAII a réussi sur dedie.
Leur contrôle Cubic et la préparation du binaire final sont requis avant publication.


La seconde revue a aussi demandé :

- Bornes explicites des indices et des cibles signées dans
  VerifiedParentCancellation avant tout accès au span. Le cas où un setup et
  une branche négatifs pouvaient mener à code[-1] est testé sous ASan/UBSan,
  avec les quatre vrais shaders Bananza et les tests de prédicats existants : PASS.
- Une seule implémentation du comportement de capture : patch
  `94-nx2-bounded-position-capture.diff`, header `video_core/position_capture_gate.h`
  dans le core. Le réécriteur `prepare-position-capture.py` et son overlay CMake
  ont été supprimés. Le filtre/déduplication/budget/reset passent sous ASan/UBSan.

Le joueur a demandé de déployer aussi la version finale une fois finalisée.
Le candidat final rassemble les patches 90–94, notamment le readback CPU/GPU
préparé séparément, pour correspondre au commit complet. Le journal
`artifacts/00.065.000-final-review/install-journal.json` établira le remplacement
vérifié du binaire ; le rendu sur console reste à tester par le joueur.

### Final source ownership review

The cumulative candidate includes core patches 90–97. The native half predicates, verified barrier cancellation, FSEL option and full generic-attribute bounds live in core patch 95, with only PS5 title/cache policy in the platform adapter. Patch 93 owns bounded VFS allocation and direct-read fallback in ordinary core builds as well as the frontend. Patch 94 gives capture state renderer lifetime and accounts for requested skipped draws in its bounded observation window. Patch 96 owns optional startup trace hooks in core. Loose-dump metadata also retains supported language flags; the non-Vulkan native configuration does not invoke Vulkan-only adapters. These structural checks do not establish an improvement in hardware rendering.

Patch 97 owns unaligned GPU-written uniform readback in the canonical buffer cache. Descriptor-table metrics are independent of VFS types. Each captured draw retains its own bounded TIC/TSC snapshot, including in-place updates and table-limit changes.
