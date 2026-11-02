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
