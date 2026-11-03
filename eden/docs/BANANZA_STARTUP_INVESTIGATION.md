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


## Essai du build transferts partiels + PGO : 10 FPS, chutes à 4, zones noires

2 novembre 2026, binaire `10b01c1f4135b33887b302b9d15b35a3453efe9dc8716ff9081c3a74914b373e`.
Le joueur confirme Bananza lancé, environ **10 FPS**, avec des **zones noires
persistantes**, puis des chutes à **4 FPS quand il y a beaucoup de mouvements**.
Le nouveau build ne constitue donc pas une correction du rendu confirmée.
Il n'y a pas de mesure avant/après dans la même scène permettant d'isoler PGO
ou les transferts partiels.

Relevé : `artifacts/partial-textures-pgo/bananza-retest/`, journaux récupérés
successivement pendant la session ; `measurement.json` conserve les agrégats.
Les FPS confirment une fenêtre de 5,064683 s à **3,554 FPS** (18 frames), ainsi
que des fenêtres vers 8–16 FPS. Les anciens passages vers 60 FPS de cette même
session peuvent être du chargement ou de la cinématique : ne pas les mélanger
avec le résultat de gameplay rapporté.

Réglages effectifs : Docked, résolution 1x, filtre Bilinear, sortie 1440p/60 Hz,
ASTC recompressé en BC3, shaders async désactivés, DMA non unsafe, reactive
flushing activé. Aucun réglage n'a été modifié pendant ce relevé.

- Aucun rejet natif graphics/compute ni `VK_ERROR` dans le log moteur récupéré.
  Les marqueurs Bananza compute indiquent `lowered=true`. Les anciens rejets
  de traduction ne sont pas reproduits ici ; les zones noires restent distinctes.
- **26 lignes `Unmapped Device ReadBlock`**, notamment pour des lectures de
  36 864/69 632 octets. Leur appelant et leur lien éventuel avec les zones noires
  ne sont pas établis. Ne pas les transformer en preuve de cause sans corrélation.
- Un relevé `Texture cache last 600 frames` compte **3 536 uploads / 759 Mio**,
  plus gros upload 18 Mio, zéro par couche. C'est un compteur d'intervalle du
  moteur, pas une mesure d'utilisation GPU ou un débit sur cinq secondes.
  Les logs courants n'identifient pas séparément l'activation du nouveau chemin
  sparse-partiel : ne pas lui attribuer un gain ou un défaut sur ce seul chiffre.
- Pas de `bad_alloc` ni de `Too many open files` dans les fichiers récupérés.
  Cache VFS environ 23,7 Mo, pic 41,1 Mo, limite 64 Mio, zéro fallback ; tables
  de descripteurs 13 026 816 octets dans les derniers échantillons. Aucune preuve
  de retour de l'ancienne saturation de fichiers ou du tas.
- Les compteurs de temps par phase draw/configuration sont nuls dans le relevé,
  et le contrôle d'horloge CPU worker est invalide. Ces données ne permettent
  pas de départager CPU, GPU et transferts dans les chutes de FPS.

Prochaine investigation utile : mesurer les phases sur une scène active qui
reproduit la chute et attribuer les lectures non mappées à leur appelant avant
un nouveau correctif. Aucun essai négatif ancien répété, aucun nouveau build ni
changement de réglage appliqué à partir de ce seul retour.


## Candidat ciblé : soumettre le décodage ASTC avant l'encodage BCn

Nouvel indice du 2 novembre : [Eglantine a407703f](https://github.com/Djihads80/Eglantine/commit/a407703f6d29a5ab73328b4ededb12cf29b2758d),
postérieur à notre premier audit, rapporte du flashing en BC3 sur RADV. Le chemin
`TranscodeAstcToBcn` était le seul à passer `Target.wait=false` et à sortir du
décodeur avant sa politique de soumission. L'amont constate que la soumission
avant encodage supprime son défaut visuel, tout en précisant que cela masque
une race dont la cause profonde n'est pas identifiée. Ce résultat AMD desktop
n'est pas une validation sur le pilote PS5.

Le binaire testé par le joueur possède exactement cette omission. Le relevé
Bananza utilise BC3 ; cela justifie un essai ciblé, contrairement à une répétition
sans nouvel indice des anciens réglages globaux de synchronisation shader.
Les 26 lectures non mappées ne sont pas attribuées à cette omission : leur
appelant et leur responsabilité éventuelle restent ouverts.

Patch `99-nx2-bcn-decode-submit.diff` : demande la politique normale du décodeur
avant l'encodage BC1/BC3 (`wait=true`). Le port utilisait déjà `scheduler.Flush()`
par défaut pour les textures natives ; ce patch ne remplace pas ce comportement
par un `Finish()` bloquant. Les barrières, la copie finale et la conservation du
temporaire jusqu'au tick après encodage sont préservées. Un marqueur unique
`NX2_BCN_DECODE_SUBMIT before_encode=1 policy=decoder-default` permettra de
confirmer l'utilisation de ce chemin au prochain essai.

Le test `tests-nx2/check-bcn-decode-submit.py` compile sur dedie la vraie méthode
`TranscodeAstcToBcn` et la vraie fin de `ASTCDecoderPass::AssembleInto`, avec un
scheduler enregistreur, sous ASan/UBSan. Il compare l'ancien appel sans soumission
au nouveau : décodage/barrière → soumission → encodage → copie finale, avec le
tick de conservation après encodage. BC1 et BC3, natif et ancien layout, deux
mips conservés après trimming, deux couches, réglage ASTC_FLUSH absent/0/1 : PASS.
Le chemin natif par défaut n'appelle pas Finish. Ce test vérifie l'orchestration,
pas les pixels ni la race du GPU réel.

Build dédié incrémental isolé : `/tmp/edglantine-partial-pgo-20261102`,
`bananza-astc-submit.log`. PGO, patches précédents, réglages et données du jeu
conservés. Artefacts prévus : `artifacts/bananza-astc-submit/`.
Compilation, packaging et résultat console consignés après achèvement. Le joueur
a confirmé la fermeture d'EdGlantine pour préparer ce correctif ; aucun résultat
FPS ou rendu nouveau n'est encore établi.


### Installation du candidat ASTC → BCn

Compilation native et packaging réussis sur dedie, ainsi que les tests ciblés
sous ASan/UBSan et les contrôles des headers/isolation PPSA99862. PGO conservé.
Les 69 fichiers d’accompagnement correspondent à ceux installés : seul eboot.bin
a été remplacé, avec staging vérifié et backup. Journal :
`artifacts/bananza-astc-submit/install-journal.json`.
Binaire installé : `6a9ac5c1454466eccb58ba3a6258543466c11d889ac05585daf5fdd726e7cdcc`.
Backup précédent : `/data/ps5-diag/edglantine-bananza-astc-29e2b3ad6fec/eboot.bin`.

Le joueur avait confirmé EdGlantine fermé. Aucun lancement automatique ni
modification de réglages, de sauvegardes ou de données de jeu. Prochain essai
Bananza à faire par le joueur, dans une scène comparable avec mouvements :
confirmer le marqueur, l’état des zones noires et les FPS. Aucun gain ni rendu
corrigé sur PS5 n’est annoncé à ce stade.

La revue Cubic n’a pas relevé de défaut dans ce lot BCn ; elle propose une
séparation de responsabilités dans le bookkeeping du patch 98 (restauration des
références de pages / consommation des plages dirty). C’est un point structurel
du lot précédent, sans défaut fonctionnel reproduit par ce retour ; il n’est pas
mélangé à cet essai d’ordonnancement ASTC. Aucun push effectué.


## Retour « tout pareil » et profilage de la scène active

Le joueur ne constate aucun changement après le candidat ASTC→BCn. Relevé :
`artifacts/bananza-astc-submit/retest/`. Les logs montrent encore des fenêtres
vers 3–12 FPS, dont 3,257 FPS sur 5,219683 s ; zones noires toujours rapportées.
Aucun rejet natif shader ni `VK_ERROR` dans les snapshots récupérés.

**Rectification de l'essai précédent :** `main.cpp` force
`AstcDecodeMode::CpuAsynchronous` en Vulkan lorsque les textures sont gardées en
BC3. Le chemin GPU modifié dans le patch 99 n'est donc pas le chemin utilisé par
ce mode. Le marqueur `NX2_BCN_DECODE_SUBMIT` est absent, et les logs comptent des
décodages asynchrones CPU. Il fallait vérifier cette sélection avant l'installation.
L'essai ne démontre pas une amélioration et ne justifie pas de répéter le patch
GPU sans changement du chemin effectivement utilisé.

Une demande runtime unique `profile-refresh.request` a déclenché la capture
bornée existante. Activation confirmée :
`NX2_PROFILE_REFRESH epoch=2 mono_ns=2269628166989`.
Les durées détaillées et timestamps GPU sont activés pendant 20 s ; les rapports
agrégés reprennent leur fenêtre bornée normale. Aucun réglage graphique modifié,
aucun nouveau binaire installé pour cette capture.

Sur 20,044195876 s entre les premiers et derniers rapports retenus :

- configuration CPU des dessins : **4,563161674 s** ;
- callback CPU-write/cohérence : **3,888683586 s** ;
- timestamps de buffers GPU terminés : **1,945259480 s**, 55 059 buffers ;
- attente de queue : 0,619863655 s ; drainage des fences : 0,621245007 s.

Ces mesures ne sont pas des contributions exclusives : les phases peuvent être
imbriquées et les threads se recouvrir. Ne pas les additionner, ni convertir les
timestamps de buffers en taux d'utilisation GPU global. Les fenêtres de gameplay
et de mouvement ne sont pas appariées à un ancien build. Les fichiers
`stderr-profile.log`, `heap-profile.log`, `engine-profile.log` et
`profile-measurement.json` conservent les limites et données.

## Défaut reproduit dans le vrai chemin CPU asynchrone

Le test sur dedie de la vraie orchestration QueueAsyncDecode / WriteMemory /
TickAsyncDecode reproduit un résultat périmé qui écrase du contenu plus récent :
une conversion A reste en attente, la texture est mise à jour et publiée avec B,
puis A termine et est uploadée sans vérifier que l'image a changé. Le worker
unique ne protège pas contre une mise à jour synchrone CPU ou un write GPU entre
la mise en file et la publication. Il ne s'agit pas d'une preuve que ce défaut
explique toutes les zones noires du joueur.

Patch `99a-nx2-async-decode-generation.diff` :

- génération de conversion par image, détenue sous le verrou du cache ; chaque
  job emporte seulement sa valeur et sa copie d'entrée, jamais une référence à
  l'image lue par le worker ;
- invalidation de la génération sur write CPU, remap, nouvelle préparation de
  contenu, modification GPU ou invalidation complète ;
- nouvelle conversion : annule les jobs précédents pour cette même identité
  d'image. Le worker peut sauter un job remplacé avant allocation/conversion ;
- publication : refuse une génération dépassée, et ne retire pas le flag de
  décodage appartenant à un job plus récent ; la vérification de cancellation
  reste avant l'accès à une image potentiellement supprimée ;
- cancellation atomique parce qu'elle est maintenant aussi lue par le worker.
  Les résultats et contextes restent détenus jusqu'à la publication de completion
  avec la synchronisation existante.

Test `tests-nx2/check-async-decode-generation.py`, sur dedie ASan/UBSan : ancien
écrasement reproduit ; version corrigée préserve une mise à jour synchrone et une
modification GPU, rejette un résultat déjà calculé devenu périmé, garde le flag du
job courant, supporte suppression et cancellation concurrente, et ne convertit
que le dernier de 200 jobs successivement remplacés. Le test de suivi sparse et
ses 192 comparaisons avec le vrai décodeur passent aussi. Ces tests utilisent une
file contrôlée et un backend mémoire enregistreur ; ils ne valident pas les pixels
PS5. Le marqueur `NX2_ASYNC_DECODE_VERSIONING active=1` identifiera le vrai chemin
CPU lors du prochain essai.

Build/package : en préparation sur dedie dans le répertoire isolé existant ;
artefacts `artifacts/bananza-async-generation/`. Pas de nouvelle installation
pendant la session active. Résultat console encore inconnu.


Compilation native et packaging du lot génération asynchrone : **PASS** sur dedie.
Contrôles des headers et isolation PPSA99862 : PASS. Les tests des 200 jobs et
des transferts partiels passent sous ASan/UBSan. La revue Cubic ne relève pas de
nouveau défaut dans ce lot ; la note structurelle déjà consignée sur le patch 98
reste distincte. Aucun push effectué. Paquet et ELF récupérés dans
`artifacts/bananza-async-generation/`. Installation en attente de confirmation
de fermeture de l’application active ; aucun résultat de rendu/FPS nouveau.


### Installation du lot génération CPU asynchrone

Le joueur a confirmé la fermeture complète après la session de profilage. Les
69 fichiers d’accompagnement sont identiques au paquet : seul eboot.bin a été
remplacé via staging vérifié, préservation des permissions et rename.
Journal : `artifacts/bananza-async-generation/install-journal.json`.
Binaire installé : `613bdc159e8a584defe03f0daf555af097e3ce6b687fbe1c80216deae7fb6fec`.
Ancien binaire : `6a9ac5c1454466eccb58ba3a6258543466c11d889ac05585daf5fdd726e7cdcc`, conservé dans
`/data/ps5-diag/edglantine-bananza-async-63435ca74e68/eboot.bin`.

Réglages, PGO, données, sauvegardes et caches conservés. Aucun lancement
automatique. Le défaut de publication périmée est reproduit/corrigé dans le test
hôte ; son impact sur les zones noires et les FPS Bananza reste à confirmer par
le prochain essai.


## Retour après génération CPU asynchrone : noir et FPS inchangés

Le joueur rapporte « c’est pareil pour le noir et fps ». Relevé :
`artifacts/bananza-async-generation/retest-20261102-125359/`, avec `measurement.json`. Le marqueur
`NX2_ASYNC_DECODE_VERSIONING active=1` apparaît à 69,175415 s : cette fois, le
chemin corrigé est effectivement utilisé. Les derniers agrégats vont de 4,603 à
15,519 FPS selon les intervalles ; le joueur ne perçoit pas d’amélioration et
aucune comparaison de scène identique ne permet d’en déduire un gain isolé.

Aucun rejet natif shader, `VK_ERROR`, `bad_alloc` ou saturation de fichiers dans
les logs récupérés. 27 lignes `Unmapped Device ReadBlock`, toujours sans appelant
attribué. Réglages effectifs inchangés : 1x, Bilinear, 1440p/60 Hz, BC3 CPU
asynchrone ; shaders async off, DMA non unsafe, reactive flushing on.

Le défaut de publication périmée reste reproduit/corrigé dans le test hôte ;
cet essai console ne confirme aucune correction du noir ni des performances.
Ne pas répéter ce même lot en attendant un résultat différent. Aucun nouveau
build, réglage ou remplacement appliqué pendant ce relevé. La prochaine
localisation doit distinguer surfaces/ombres noires et géométrie absente, puis
corréler les ressources ou l’état de dessin avec une zone réellement incorrecte.

## Crash natif après capture de quatre dessins (2 novembre)

Le joueur précise que les surfaces sont présentes mais noires. Pour examiner
leurs constantes, demande bornée `position-capture.request` : `512 4 0`.
Quatre dessins 1440 × -810 récupérés, 360 fichiers / 12 019 485 octets, dans
`artifacts/bananza-async-generation/retest-20261102-125359/draw-capture/`.
Cette capture effectue des téléchargements synchrones des constant buffers ;
sa proximité avec le crash interdit de la considérer comme passive ou de
conclure à un crash spontané du jeu. Aucun nouvel essai de capture lancé.

Le joueur signale ensuite un retour au lanceur. Rapport exact
`crash-20261102-140849.txt` (MLSD UTC 13:08:49), récupéré avec ses logs dans
`artifacts/bananza-async-generation/crash-20261102-130010/` :
SIGSEGV code 2, trap 12 / error 0x7 (écriture sur page protégée), thread
GPUFencingThread, destination 0x8186200000, copie 4096 octets. Le backing invité
est 0x8000000000 sur 12 GiB, CRAM actif, scan on, fine/dedup off. Pas d’EMFILE
ni d’échec d’allocation CRAM dans le relevé. Dernière capture journalisée à
507,479 s ; crash vers 510 s. Le redémarrage du frontend vient du handler natif.

Symbolisation avec l’ELF exact du binaire 613bdc… sur dedie : premier candidat
0x2fa30 = BufferCache::PopAsyncFlushes ; désassemblage confirme une instruction
call indirecte de copie immédiatement avant ce retour. Les autres candidats
sont MasterSemaphore::Wait, proxy FenceManager et thread_start ; une recherche
sur pile reste une liste de candidats, pas une pile déroulée certifiée.
Le chemin PopAsyncBuffers écrit les résultats GPU via WriteBlockUnsafe.

Nouvel indice et défaut reproduit : HandleGuestWriteFault comptait toutes les
fautes consécutives à la même adresse dans la durée de vie du thread, même quand
la promotion précédente avait réussi. Après 16 promotions/libérations valides,
la 17e est refusée avant même de consulter l’état du slot. Un scanner qui rend
un slot nul peut donc transformer une écriture valide ultérieure en SIGSEGV.
Le rapport ne conserve ni l’état du slot ni son compteur par thread : cette
cause précise du crash console reste à confirmer, malgré la compatibilité du
site et de l’adresse.

Correction : compter seulement les retours sans transition depuis SlotOwn ;
remise à zéro lors d’une promotion ou d’une attente d’un autre propriétaire.
Le refus après 16 essais sans progrès reste actif, verrou libéré avant refus.
Test `check-guest-write-retries.py` exécuté sur dedie : vraie fonction extraite,
signal SIGSEGV réel sur mmap/mprotect, backend de promotion simulé. Ancienne
fonction : refus reproduit à la 17e écriture valide. Correction : 100 écritures
protégées à la même adresse passent ; refus sans progrès, attentes,
Shared/Fine et échec de promotion sont vérifiés sous UBSan. Ce test ne reproduit
pas les appels de mapping PS5. Compilation native/package en cours ; aucune
nouvelle installation ni validation des zones noires/FPS à ce stade.

Compilation native et packaging du correctif CRAM : **PASS** sur dedie, PGO
conservé. Contrôles headers et isolation PPSA99862 : PASS. Artefacts :
`artifacts/bananza-cram-retries/`, ELF exact conservé pour symbolisation.
SHA256 du nouvel eboot :
`2fc612464e198872837d483308ca3d5c9332014080ee87af61686560ab7e3db1`.
Le joueur confirme ensuite la fermeture complète, lanceur compris ; installation
par remplacement vérifié avec sauvegarde de l’ancien exécutable.

Installation CRAM terminée : 69 fichiers d’accompagnement identiques ; seul
`/data/homebrew/PPSA99862/eboot.bin` remplacé. Journal
`artifacts/bananza-cram-retries/install-journal.json`, status installed.
Ancien binaire 613bdc… conservé dans
`/data/ps5-diag/edglantine-bananza-cram-8c01bce6536b/eboot.bin`.
Données, sauvegardes, paramètres et caches conservés. Aucun lancement automatique.
Stabilité console et rendu/FPS encore non validés par le joueur.

## Crash au lancement après le lot nxnative/nightly : constantes JIT

Rapport `crash-20261102-155047.txt`, MLSD UTC 14:50:47, 22 s après le début
de l'application, Bananza 040074A01BF12000. Binaire installé
`04859f5b6a06bda8724e43c5174229d92c4d57cf0870e98c512e5f2d33e7e8d5`.
Preuves : `artifacts/upstream-opt-20261102/bananza-startup-crash/`.

SIGSEGV code 2, trap 12 / erreur 0x7, thread **CPUCore_0**, destination
`0x1150000010`. `EDEN_JIT_MEMORY code=1150000000` place cette adresse dans le
cache JIT, hors du backing guest CRAM. Environ 10 052 Mio encore libres ; pas
d'EMFILE ni de bad_alloc dans ce relevé. Compteurs draw/gather à zéro avant le
crash. Ne pas l'assimiler au précédent défaut de retry CRAM ou à un crash GPU.

Symbolisation avec l'ELF exact `b17cac…` : `eboot+0x558ed` est
`Dynarmic::Backend::X64::ConstantPool::GetConstant`. L'instruction fautive
`movq %rdi,(%rdx,%rax)` écrit le premier mot de la constante, avec
rdx=0x1150000010 et rax=0. La suivante écrit le second mot. Le code de la
nouvelle optimisation n'a pas été redirigé vers l'alias writable : l'ancien
`jit-alias.cmake` remplaçait seulement `target_constant = constant;` et ne
reconnaissait plus `pool[it->second] = u128{lower, upper};`. La substitution
silencieuse laissait donc une écriture directe dans la vue protégée.

Correction : `jit-constant-pool.cmake`, inclus par le vrai générateur natif,
reconnaît les deux écritures connues et les redirige par `writableAddress` sans
changer les adresses des opérandes dans la vue RX. Un store absent, inconnu ou
dupliqué fait maintenant échouer CMake au lieu de produire un binaire incorrect.
Les optimisations de hash/indices et la vérification explicite de capacité sont
conservées ; aucune protection mémoire n'est relâchée.

Le test antérieur utilisait le source brut et une allocation writable simulée,
et manquait donc cette adaptation spécifique PS5. Le test est remplacé sur ce
point : il exécute le véritable helper CMake puis les méthodes générées, sur deux
vues partagées réellement RW/RX. Sous ASan/UBSan sur dedie : ancienne écriture
SIGSEGV reproduite, alias corrigé et valeurs 128 bits exactes, adresses RX
conservées, écriture directe RX toujours refusée, capacité et doublons vérifiés.
Les formes CMake inconnue/dupliquée sont refusées. Les régressions texel/VP9 et la
continuité viewport passent aussi. Aucun succès de lancement PS5 encore établi.

L'utilisateur a confirmé EdGlantine fermé. Compilation/package sur dedie :
**PASS**, PGO conservé, headers sparse/multiplayer et isolation PPSA99862 vérifiés.
Cubic : zéro signalement, sans erreur. Les 69 fichiers d'accompagnement sont
identiques ; seul eboot.bin a été remplacé par staging vérifié et rename.
Artefacts et journal : `artifacts/upstream-opt-jit-alias-fix/`.
SHA256 installé : `022b4cecd994f0a918a90cef05ba46788e8a42202df28770e64960c5efa9b526`.
Backup : `/data/ps5-diag/edglantine-jit-alias-fix-4e7040e21045/eboot.bin`.
Pas de changement de jeu, sauvegarde, paramètres ni cache, ni de lancement
automatique. Le défaut est reproduit/corrigé sur hôte ; le lancement et les FPS
sur PS5 restent à retester.

## Retest JIT : lancement confirmé, vidéo du tunnel noir

Le joueur confirme le lancement avec l'eboot `022b4cec…`, puis signale toujours
des assets noirs et peu de FPS. Sa vidéo PS5 a été récupérée sans modification
de la console : `artifacts/upstream-opt-jit-alias-fix/gameplay-retest/`, fichier
`20261102_160710_00938730.webm` (8,71 s). Dans « Explorez le tunnel minier ! »,
Donkey Kong, les objets dorés et la fumée s'affichent, alors que de grandes
parties du sol et des parois sont noires. Un rectangle beige sans contenu est
également visible en bas à droite. Le HUD varie approximativement de 8 à
20 FPS dans la vidéo. Cette capture ne permet pas de distinguer à elle seule
une passe couleur absente d'une surface rendue noire.

Les logs récupérés lors de cette session, avant la vidéo, donnent 135 images
sur les cinq derniers intervalles (25,474388 s), soit **5,299 FPS**. Ce n'est
pas une comparaison à scène identique. Dans cette fenêtre : 87 524 submits
(2,220 s), 79 942 semaphore_wait (5,017 s), 75 378 buffer_sync (4,529 s),
8 555 guest_fence (0,894 s). Ces durées peuvent se recouvrir : ne pas les
additionner. Pas de compilation de pipeline/shader dans cette fenêtre ; les
marques CPU détaillées sont désactivées. Les compteurs gather/scatter/reuse
restent tous nuls : le nouveau cache de gathers n'est pas sollicité dans ce
relevé. Aucun gain de performances n'est établi.

Nouvel indice pour le rendu : nxnative, commit
`e5620b1a05a5b7374e0135d6312d3e90994eab81`, décrit dans
`docs/reference/shaders.md` / « Global memory at an address loaded from memory »
un tunnel Bananza noir, avec objets/personnage visibles, causé par les stores
indirects manquants du vertex shader `c9a56f796ea4a4cd` qui réinitialise les
commandes du terrain. Notre log contient aussi des avertissements
`Storage buffer failed to track, using global memory fallbacks` au chargement
du cache. Notre fallback SPIR-V parcourt seulement les SSBO suivis, avec les
bases/tailles NVN lues en cbuf ; il ne fournit pas la table générale de pools
utilisée par nxnative pour les pointeurs chargés depuis la mémoire. C'est une
piste concrète, **pas une cause reproduite sur notre shader de terrain**.
Les clés nxnative incluent contrôle et code via SHA256, contrairement à notre
clé FNV du code : ne pas comparer directement ces identifiants. Les anciens
quatre draws capturés ne suffisent pas à identifier le draw de reset de
96 points décrit en amont. Aucun nouveau readback GPU, réglage, cache effacé
ou binaire déployé lors de cette collecte.

## Candidat ciblé : réinitialisation des commandes indirectes

Après autorisation de correction, le joueur ferme EdGlantine. Le cache
`/data/eden-nx2/user/cache/shader/040074a01bf12000/vulkan.bin` est récupéré en
lecture seule (17 422 988 octets). Le lecteur hors console suit les 752 entrées
jusqu'à la fin exacte ; il relève 743 codes distincts, majoritairement déjà
abaissés en Maxwell et conservant la table d'adresses native (native_count=0).
Ne pas prendre ce champ nul pour une absence de shaders natifs.

Un seul vertex program contient exactement cinq STG : code abaissé complet
384 octets, index FNV privé `511f87db997612db`, présent dans quatre pipelines
(vertex + fragment). Il charge VertexID, calcule `c0[0x110] + VertexID * 8`,
charge le pointeur 64 bits à cette adresse et écrit les cinq mots
`{0,1,0,0,0}`. Le cache conserve c0[0x110/114] comme pointeur de storage,
mais pas de descripteur direct pour les pointeurs chargés depuis cette table.
C'est bien la forme de reset décrite par nxnative ; l'identité avec sa clé
SHA256 contrôle+code n'est pas établie par comparaison de hashes.

Le patch `99d-native-indirect-reset.diff` ajoute un traitement **ciblé**, pas
une table générale de mémoire globale : reconnaissance des 48 mots exacts
(header sans sortie position, code, exit et address map inclus) à la création
du ShaderInfo, puis rétablissement cohérent des stores avant le draw normal.
Le draw Vulkan et ses queries restent exécutés. Pas de saut fondé sur un
hash, une adresse du jeu ou son title ID. Le chemin est réservé au prototype
PS5 natif, draw direct non indexé, une instance, first vertex=0, points, sans
autre étage pré-raster, transform feedback ou rendu conditionnel. La
rasterization peut rester activée : les quatre pipelines du cache incluent
un fragment shader et le draw normal est conservé.

Le traitement lit le cbuf et la table par ReadBlock cohérent puis prévalide
**toutes** les destinations avant le premier WriteBlock cohérent de 20 octets.
Limite 1 024 records ; plages non mappées, wrap, pointeur nul/non aligné,
chevauchements partiels entre records et alias avec table/cbuf sont refusés.
Les doublons exacts sont permis. Aucune invalidation globale ni exploration de
tous les pools ; seuls les records adressés sont touchés. Les shaders
arbitraires à pointeurs indirects restent une limite du fallback général.

Tests dédiés sur dedie ASan/UBSan : match du code récupéré, mutation de chaque
bit des 48 mots refusée, 96 records remis à zéro avec instanceCount=1 et
voisins inchangés, remise à zéro après un résultat de culling simulé,
prévalidation sans écriture partielle et lecture cohérente plutôt qu'un
shadow CPU périmé : PASS. La compilation native vérifie aussi le code après
adaptation PS5 ; les anciennes substitutions monolithiques du profiler sont
scindées pour conserver le nouveau bloc. Artefacts de travail :
`artifacts/bananza-global-memory/`. Ces tests ne confirment pas encore le rendu
ni un gain de FPS sur console.

Validation finale : tests 96 et 1 024 records, pointeurs 64 bits traversant une
frontière de 4 Gio et code après adaptation PS5 : PASS. La validation de mapping
vérifie explicitement les deux bornes de l'espace GPU avant IsFullyMappedRange.
Compilation/package sur dedie, headers sparse/multiplayer et isolation : PASS,
PGO conservé. Deux revues Cubic locales sans signalement ni erreur ; contexte
dépôt distant indisponible, revue locale effectuée.

Installation après confirmation de fermeture : 69 fichiers d'accompagnement
identiques, remplacement du seul eboot par staging vérifié/rename, status
`installed`. SHA256 :
`8e5bcad01289df27f98934ce75abab1cf46504eb0260ccc990b85061722c64b7`.
Ancien binaire 022b4cec… conservé sous
`/data/ps5-diag/edglantine-indirect-reset-47dc5a87e960/eboot.bin`.
Journal, paquet et ELF exact : `artifacts/bananza-global-memory/`.
Sauvegardes, réglages, caches et app distincte Botty préservés. Pas de lancement
automatique. Au prochain passage dans le tunnel, vérifier le marqueur
`NX2_INDIRECT_RESET draws=1 records=96 coherent=1`, puis l'évolution du terrain
et des FPS. **Rendu et performances console restent non validés** ; la présence
du marqueur seule ne constitue pas une correction visuelle confirmée.

## Retest suivant : apparition différée du terrain

Le joueur rapporte d'abord aucun changement, puis précise : « ils ont apparus
 d'un coup, plus de noir ». La disparition visuelle du noir est donc confirmée
par le joueur **après un délai**, sans nouveau déploiement entre ces deux
retours. Un gain de FPS n'est pas confirmé. Ne pas attribuer encore toute la
transition au traitement ciblé sans relever son activation : le snapshot de
logs récupéré juste avant le second retour ne contient aucun
`NX2_INDIRECT_RESET`, ni succès ni rejet.

Snapshot : `artifacts/bananza-global-memory/retest/`. Le lancement indique
`Resolution 1x, Bilinear, output 1440p`, mais les images réellement présentées
par Bananza sont **2880x1620**, et `wsi/videoout` enregistre des framebuffers
**3840x2160**. Le libellé de configuration 1440p ne décrit donc pas à lui seul
les dimensions effectives de cette session. L'image présentée peut inclure
l'upscaler du jeu : la résolution 3D interne avant cette passe n'est pas établie.

## Check-up après passage en mode portable, puis essai 0,5×

Le joueur ressent un gain important et demande un check-up puis 720p, avant de
confirmer EdGlantine fermé. Snapshot borné des logs et paramètres :
`artifacts/bananza-handheld-check/`. Le profil et le lancement confirment
**Handheld / 1×**. Cependant les images présentées par le jeu restent
**2880×1620**, avec des framebuffers videoout 3840×2160. Le passage en portable
ne permet donc pas d'annoncer un 1080p effectif ; il faut corriger cette cible
précédemment supposée. La résolution de la scène avant upscaling reste inconnue.

Les cinq derniers intervalles donnent **596 images en 25,136684 s = 23,710 FPS**,
avec des moyennes d'intervalle entre 22,732 et 24,722 FPS. L'ancien relevé
5,299 FPS n'est pas apparié à la même scène : amélioration observée, sans gain
isolé attribuable à la résolution ou au mode portable. Dans cette fenêtre,
les deltas cumulatifs donnent submit 1,673 s, semaphore_wait 4,888 s,
guest_fence 1,152 s, buffer_sync 4,050 s ; pas de compilation pipeline/shader.
Ces temps peuvent se recouvrir. Les marques CPU détaillées sont désactivées.
Pas de VK_ERROR, bad_alloc ou échec de draw natif dans le snapshot ; 22 erreurs
Unmapped Device ReadBlock et 20 avertissements de suivi storage subsistent.

L'activation du reset est maintenant **confirmée dans ce relevé** :
`draws=1 records=997` à 82,213 s, puis `draws=600 records=96` à 115,870 s et
`draws=1200 records=96` à 141,148 s, tous `coherent=1`. Cela complète le
snapshot antérieur pris avant l'apparition différée ; le rôle causal de ce
traitement et du mode portable n'est toujours pas isolé par un A/B identique.

Le réglage existant ne propose pas le ratio 4/9 nécessaire à 1280×720 depuis
2880×1620. Après explication, le joueur choisit explicitement **« Tester 810p
maintenant »**. Seuls les paramètres Bananza sont modifiés : console_mode
`handheld` conservé, resolution `1x` → `0.5x`. Cible si l'image actuelle est
redimensionnée : **1440×810**, pas 720p. Les critères de mise à l'échelle des
images et l'upscaler du jeu empêchent de certifier la résolution 3D de toutes
les passes avant le prochain relevé. Pas de nouveau binaire, réglage global,
cache ou sauvegarde modifié. Configuration précédente sauvegardée sous
`/data/eden-nx2/config/prosperoeden.json.before-bananza-810p-ce6513b8b4`.
Journal : `artifacts/bananza-810p/journal.json`. Le joueur peut relancer et
comparer le même passage une fois les assets apparus ; résultat encore attendu.

## Relevé après relance portable / 0,5×

À la demande du joueur, collecte passive du lancement et de deux fenêtres de
logs, sans modification de configuration ni demande de readback GPU. Preuves :
`artifacts/bananza-810p/retest/`, deuxième fenêtre dans `later/`, calcul dans
`measurement.json`. Profil JSON **handheld / 0.5x**, marqueurs de lancement
**Handheld / Resolution 0.5x** : confirmés. Images guest toujours **2880×1620**,
videoout **3840×2160** ; toutes deux au ratio **16:9**. Ces dimensions guest
précèdent l'éventuelle réduction des cibles GPU. Les logs ne donnent pas leur
taille après rescale : **1440×810 effectif non directement confirmé**. Le code
ImageCanRescale reste sélectif (rescaleable/downscaleable et aliases), donc le
choix 0,5× ne permet pas de garantir la définition de toutes les passes.

Première fenêtre de gameplay, encore en chargement : 15,150 FPS sur les quatre
derniers intervalles. Deuxième fenêtre : **229 images en 25,347417 s = 9,034 FPS**,
intervalles 14,759 / 7,694 / 7,311 / 7,560 / 7,829 FPS. Comparaison descriptive
avec les 23,710 FPS de l'essai 1× : ce n'est pas une scène appariée, et les
phases de streaming diffèrent. Aucun gain du 0,5× démontré ; ne pas conclure à
une régression causée uniquement par le rescale.

Deltas API sur la deuxième fenêtre : submit 2,198 s, semaphore_wait 6,154 s,
buffer_sync 5,928 s, guest_fence 0,673 s. Pas de compilation de pipeline/shader
sur cette fenêtre. Timings potentiellement imbriqués, marques CPU détaillées
désactivées. Aucun VK_ERROR, bad_alloc ou échec de draw natif ; 23 Unmapped
Device ReadBlock, 20 avertissements storage non suivis dans le snapshot.

Point concret nouveau : le reset exact est reconnu, mais des listes de
**1470, 1480, 1482 records** sont refusées à 72,252–72,813 s. Le helper impose
`count > 1024` → refus, dont le message générique « unsafe table/range » ne
permet pas de distinguer ce plafond d'un mapping invalide. Un reset accepté
à 77,478 s comporte 1018 records. La borne de travail choisie à l'implémentation
est donc inférieure aux listes réellement rencontrées. Cela justifie une
correction du plafond et de son diagnostic ; le lien exact avec la dégradation
FPS et le délai d'apparition nécessite encore validation. Pas de nouveau
binaire ni de retour automatique à 1× pendant ce check-up.

## Retour au mode télé natif et correction du budget de reset

Le joueur quitte le jeu, demande de corriger le défaut puis précise **mode
 télé, comme au tout début**. Profil Bananza rétabli à `console_mode=docked`,
`resolution=1x` ; options globales et autres jeux inchangés. Configuration
précédente conservée dans
`/data/eden-nx2/config/prosperoeden.json.before-bananza-native-4335ebfa82`.
Journal : `artifacts/bananza-reset-cap-fix/settings-journal.json`.
Le joueur confirme ensuite l'application et son lanceur complètement fermés.

Le patch `99e-native-indirect-reset-budget.diff`, après le patch initial 99d,
relève le budget à **65 536 records** : les deux tableaux temporaires sont
bornés à 1 Mio au total. Les listes réellement observées de 1470/1480/1482
records ne sont plus écartées par le plafond de 1024. Ce n'est pas une
suppression de la prévalidation : toutes les adresses, mappings, alignements,
alias avec les sources et chevauchements partiels restent contrôlés avant le
premier store. Une liste dépassant le nouveau budget est refusée avant lecture
ou allocation des tableaux. Le nombre de destinations reste borné.

Le résultat détaille maintenant le motif de refus : empty_draw, work_budget,
constant_buffer, pointer_table, record_mapping_or_alignment, source_overlap ou
partial_record_overlap. Les logs indiquent motif, taille, budget et nombre total
de refus, d'abord quatre fois puis tous les 600 refus. Les resets acceptés
indiquent aussi le budget. Le draw Vulkan normal reste conservé.

Validation sur dedie ASan/UBSan : ancienne fonction extraite du patch 99d,
refus de 1482 records reproduit avant toute lecture ; nouvelle fonction,
96/1024/1025/1470/1480/1482/1600/65536 records corrects et voisins conservés.
Les refus invalides restent sans écriture partielle ; raisons distinctes,
budget excessif sans lecture, reset du motif après succès, adresses 64 bits,
code exact/mutations et code après adaptation PS5 : PASS. Native build/package,
headers sparse/multiplayer et isolation PPSA99862 : PASS, PGO conservé. Cubic
ciblé : zéro signalement et aucune erreur (contexte dépôt distant indisponible).

Installation terminée après confirmation : 69 accompagnements identiques,
seul eboot.bin remplacé par staging vérifié puis rename. SHA256 installé :
`de2d747415fc470256bf798aca2e33967b5c91aa3a09f4a32059c8b0bf061529`.
Ancien binaire 8e5bcad0… sauvegardé sous
`/data/ps5-diag/edglantine-reset-cap-fix-0bdbfb82bfd3/eboot.bin`.
Paquet, ELF exact, revues et journaux : `artifacts/bananza-reset-cap-fix/`.
Aucun cache, jeu ou sauvegarde modifié ; pas de lancement automatique.
Le défaut de plafond est reproduit et corrigé sur hôte. L'effet sur le délai
d'affichage et les FPS, maintenant en docked/1×, reste à mesurer après relance.

## Noir disparu, FPS encore faibles : commandes DMA et readback

Après le build budget corrigé, le joueur confirme ne plus observer de noir,
puis signale des FPS toujours mauvais. Relevés passifs et profilage :
`artifacts/bananza-reset-cap-fix/fps-retest/`. Lancement Docked / 1× confirmé.
Reset accepté avec **1525 records** puis **1062 records**, budget 65536, aucun
rejet relevé. Aucun VK_ERROR, bad_alloc ou échec de draw natif ; les lectures
Device non mappées persistent (25 dans le premier snapshot). Des fenêtres de
gameplay descendent à 4,476–6,782 FPS ; un relevé ultérieur donne **7,269 FPS
sur 25,314261 s**. Les fenêtres à ~60 FPS des menus ne sont pas du gameplay.

Le chemin du marqueur indiqué par l'ancien skill était périmé : le source
réel utilise RuntimeControl avec Eden::AppFile, et non le data root. La demande
non consommée est déplacée (même nonce) de `/data/eden-nx2/profile-refresh.request`
vers `/data/homebrew/PPSA99862/profile-refresh.request`. Activation confirmée :
`NX2_PROFILE_REFRESH epoch=2 mono_ns=16165433599361`. Les marques détaillées
restent bornées à 20 s, indépendamment de la visibilité du HUD ; le skill a été
corrigé sur ces points. Pas de réarmement répété ni de readback de capture.

Sur cette fenêtre, préparation des dessins **5,106 s**, dont lecture ressources
1,118 s, binding 1,924 s et descripteurs 1,709 s ; marques imbriquées à ne pas
additionner. Pointer-sync : 0,097 s. Les compteurs readback cache restent nuls.
Les sites d'attente sont symbolisés avec l'ELF exact de2d7474… et l'ancre du log
(0x291bc60 vs ELF0x251bc60, relocation0x400000) : principal ReadBlock depuis
DmaPusher::DispatchCalls, puis FlushRegion/BufferCacheRuntime::Finish ; distinguer
le FenceManager sur son autre thread. Les compteurs epoch1 cumulatifs ne sont
pas présentés comme des coûts exclusifs de la fenêtre epoch2.

Piste testée : le cache de fenêtres GPU existant était admis seulement dans
RefreshParametersImpl. Les snapshots cohérents de commandes natifs passaient
par le loader sûr sans ce scope, d'où l'absence de cache dans ce profil.
`99f-native-command-readback-cache.diff` ajoute une admission explicite autour
des petites lectures de commandes **contiguës, de 1 à 4096 octets**. Le scope
est terminé avant le parsing, ses writers et ses acquires suspendus ; les
commandes restent copiées et possédées. Le chemin solo et le helper split
conservent leur ordre et la sélection cohérente/unsafe existante.

Pour ces commandes, fenêtre spéculative bornée à **4 Kio**, au lieu des 64 Kio
des paramètres ordinaires. Seuls les octets demandés et réellement GPU-dirty
sont publiés en RAM CPU. Le cache existant reste invalidé par le dirty ledger
à chaque écriture GPU. Lectures grandes/non contiguës/non mappées et demandes
traversant une fenêtre gardent le chemin cohérent normal. Pas de suppression
 de synchronisation requise ni de conservation de spans directs vers l'invité.

Sur dedie, ASan/UBSan : helper et cache de production, séquence simulée de
64 lectures d'un producteur : **64 attentes anciennes → 1 attente mise en cache**.
Comparaison des octets identiques, invalidation par nouveau producteur, voisins
CPU conservés, écriture CPU plus récente, snapshot possédé immuable, fallback
sparse/large/cross-window, unsafe/dirty split et restauration TLS après exception :
PASS. Cette fixture ne simule pas le pilote PS5 et ne prouve aucun gain FPS.
Compilation native/package, headers sparse/multiplayer et isolation : PASS,
PGO conservé. Cubic ciblé : zéro signalement, sans erreur (contexte distant
indisponible).

Le joueur a fermé l'application. 69 accompagnements identiques ; seul eboot
remplacé par staging vérifié et rename. Nouveau SHA256 :
`02a4957ed94eac4dab51e212281aec767c5e67794779dd13410f3458c86457ff`.
Ancien de2d7474… conservé sous
`/data/ps5-diag/edglantine-command-readback-c58225a139b9/eboot.bin`.
Paquet, ELF exact, revue, tests et journal : `artifacts/bananza-command-readback/`.
Mode télé / 1×, paramètres et données inchangés. Résultat console de cette
optimisation encore attendu ; vérifier hits/misses/fills/invalidations du cache
et FPS dans le même passage après relance.

## Cache actif sans gain global établi, puis essai GPU rapide

Le joueur relance et constate « tout pareil », puis ferme l'application.
Preuves : `artifacts/bananza-command-readback/retest/`. Le cache est bien
sollicité : premier snapshot 76 692 hits / 6 996 misses (~91,6 %). Un nouveau
profilage, justifié par cette activation réelle après le précédent patch,
confirme la réutilisation ; deltas des rapports agrégés disponibles après
réarmement : **235 033 hits / 16 800 misses (~93,3 %)**, 14 343 invalidations,
2 157 clears et 336 évictions. Augmenter la capacité ne répond donc pas au
motif principal des misses. Ces deltas agrégés couvrent les rapports disponibles
après réarmement, pas nécessairement les seules 20 s de marques détaillées.

Dernière fenêtre gameplay : **219 images / 25,284365 s = 8,661 FPS**, intervalles
9,155 / 8,440 / 7,917 / 5,119 / 12,715. Deltas API : submit 0,852 s,
semaphore_wait 1,887 s, buffer_sync 0,688 s, guest_fence 1,254 s. Les scènes ne
sont pas appariées ; pas de gain global revendiqué contre le retour joueur.
Marques détaillées : configuration des dessins 4,880 s, lecture 1,088 s,
bindings 1,823 s, descripteurs 1,610 s ; ces coûts sont imbriqués. Les timers
racine peuvent continuer après la fenêtre détaillée : ne pas additionner leurs
totaux aux sous-phases. Cache actif ne signifie pas problème FPS résolu.

Le joueur choisit explicitement **« Tester GPU rapide »** après explication du
compromis de précision. Le réglage est `fast_gpu=true` → GPU accuracy Low.
Audit préalable : Default DMA dérive son choix sûr de la précision GPU ; Low
rendait donc les snapshots de commandes optimistes, et RefreshParametersImpl
sautait les arguments natifs, y compris lorsqu'ils venaient d'un producteur GPU.

Le patch `99g-native-default-dma-coherence.diff` conserve, pour les commandes
natives Low+Default, le contrôle dirty sur le propriétaire des caches : lecture
cohérente si un producteur GPU a modifié la plage, copie possédée ordinaire si
elle est propre. High et la politique explicitement Unsafe des snapshots
restent inchangés ; le chemin split garde son helper existant. Les paramètres
MME natifs Low+Default restent rafraîchis au moment de leur consommation.

Cubic a identifié un P1 dans une version intermédiaire **non installée** :
ProcessMacro utilisait encore sa pile pour les appels Low de <=64 mots, alors
que RefreshParametersImpl écrit dans macro_params. Correction : le même cas
native+Default est exclu de ce raccourci, conservant un vecteur modifiable
pendant l'exécution. Le test initial de la seule méthode ne couvrait pas cette
interaction ; il est étendu aux deux vraies méthodes de production.

Sur dedie ASan/UBSan : ancien snapshot Low+Default périmé reproduit, nouvelle
politique lit les octets GPU frais ; chemin propre, High, explicitement Unsafe,
cache et ordre split conservés. Test des vrais ProcessMacro/RefreshParametersImpl :
incompatibilité intermédiaire pile/vecteur détectée, puis appels complets
1/64/65 mots et appels fragmentés 2+3, pour toutes les combinaisons High/Low,
natif/legacy et Default/explicite : PASS. Stockage, paramètres rafraîchis,
nettoyage et restauration du scope vérifiés. Compilation/package natifs,
headers et isolation : PASS ; PGO conservé. Revue Cubic finale : zéro
signalement, sans erreur, après correction du P1 (contexte distant indisponible).

Installation : accompagnements identiques (69), seul eboot remplacé après
fermeture. SHA256 :
`dae8638c99652d3c7d11920eadf021e22d1b1f98639ac775e69cb4dd2fc7aeb4`.
Ancien 02a4957e… sous
`/data/ps5-diag/edglantine-fast-gpu-5b18dd78990d/eboot.bin`.
Puis activation uniquement dans le profil Bananza de `performance.fast_gpu=true` ;
mode télé / 1× maintenu, options unsafe CPU/DMA et paramètres globaux inchangés.
Ancienne configuration :
`/data/eden-nx2/config/prosperoeden.json.before-bananza-fast-gpu-a357d13ad8`.
Paquet, ELF exact, revues et journaux : `artifacts/bananza-fast-gpu/`.
Ni lancement automatique ni gain FPS annoncé. Cet essai réduit la précision
graphique ; vérifier au prochain lancement `fast GPU on`, mode Docked/1×,
fluidité et absence de nouveaux défauts visuels dans le même passage.

## Retest GPU rapide : activation et rendu confirmés

Le joueur relance, puis confirme explicitement **« Oui, rendu correct »** pour
le terrain et les objets. Logs : `artifacts/bananza-fast-gpu/retest/`, seconde
fenêtre dans `later/`, résultats `measurement.json`. Lancement confirmé :
**Docked / 1×, fast GPU on, unsafe CPU off, unsafe DMA off**, async shaders off,
reactive flushing on, skip invalidation off, speed limit100 %. Les options
« block list on » sont également rapportées ; ce relevé ne les isole pas.

Premières fenêtres gameplay : 12,657 / 15,754 / 18,585 FPS, soit 15,665 FPS sur
15,129095 s. Après une courte observation supplémentaire, cinq derniers
intervalles : **396 images en 25,118886 s = 15,765 FPS**, moyennes de fenêtre
15,171 / 16,995 / 9,976 / 19,312 / 17,346. Meilleur que les 8,661 FPS du dernier
relevé High, mais les scènes/activités ne sont pas strictement appariées :
amélioration observée, pas de gain isolé chiffré ni de 1% low déduit.

Le cache reste actif : total 292164 hits / 22059 misses (~93 %), fenêtres de
4 Kio. Reset accepté à 1525, 125 et 1446 records ; aucun rejet dans le relevé.
Pas de VK_ERROR, bad_alloc ou échec de draw natif ; pas d'avertissement natif
compute dans le premier snapshot. Les Device ReadBlock non mappés persistent
(26 dans le second snapshot). Deltas API sur les 25,118886 s : submit1,181 s,
semaphore_wait2,525 s, guest_fence1,529 s, buffer_sync1,060 s. Pas de compilation
pipeline/shader dans cette fenêtre ; durées potentiellement imbriquées.

Le profil Bananza GPU rapide / télé / 1× est conservé après ce retour joueur.
Aucun réglage ni binaire modifié pendant les relevés, aucune capture GPU
synchrone demandée. Activation et rendu validés pour cette session ; fluidité
encore basse, généralisation et stabilité prolongée non établies.
