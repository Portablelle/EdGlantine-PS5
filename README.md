# EdGlantine-PS5

**00.063.000 installée** : regroupement des pages, propriétaires mémoire et espacements
de textures Eglantine ; compilation/tests ciblés sur build-server réussis. Rollback 00.062.000
conservé. FPS/rendu à mesurer ; application non relancée.

Ce projet dérive de ProsperoEden 1.005.000 et du fork expérimental Eden NX2.
Il ne remplace pas Botty et ne modifie pas son moteur Switch 1.

**État : .062 conserve l’attente après activation : 29 222 lus pour 29 226 attendus. 14 snapshots DMA / 724 octets, aucun sale ; lecture ordonnée sans effet sur cette attente. Producteur/soumission/décodage à poursuivre. Aucun gain FPS du découpage démontré.**
La .017 arrête explicitement la session sur une commande DMA sans moteur lié,
après une erreur FIFO du macro MME 0x18f. La copie possédée ne suffit pas à résoudre
le problème. La .018 sélectionne l’interpréteur pour ce macro avant toute exécution,
avec captures initiales bornées ; les autres macros conservent le JIT.
La .019 reproduit un arrêt DMA avant ce macro. La .020 transporte les préfixes
de soumission avec chaque lot : le bloc change après soumission avant sa lecture,
à adresse device identique. La .021 désactive le report des notifications CPU
pour isoler un problème possible d’ordre des écritures ; elle reproduit la mutation.
La .022 enregistre les écritures du moteur et les notifications CPU sur les blocs
en attente : une relecture de buffer GPU de 4 Ko écrase les commandes.
La .023 limite les copies à la plage demandée, conserve les données GPU voisines
encore modifiées et retire la trace lourde. Cinq cas ciblés passent sur build-server.
La .023 reste jouable dans l’essai observé jusqu’à ~65 s, mais à 6 FPS.
La .024 rétablit le report CPU mais reproduit l’arrêt DMA. La .025 applique
les notifications et invalidations CPU avant la relecture, avec reprise synchrone
sur le thread GPU, mais l’essai reste bloqué sur écran noir avec méthodes compute
hors plage. La .026 revient aux notifications immédiates, retire ces drains et
arrête explicitement les méthodes compute hors banque pour capturer leur bloc.
La .026 atteint l’écran jouable à 6 FPS dans l’essai observé. La .027 groupe les
lectures exactes des pointeurs SSBO avant liaison, avec secours individuel ;
la .027 reste à 6 FPS et les attentes restent comparables. La .028 mesure
les attentes par appelant : DownloadBufferMemory domine avec ~29 400 appels
pour ~3,26 s en cinq secondes. La .029 complète l’origine ReadBlock/FlushRegion
et les volumes : la copie des blocs DMA est le lecteur dominant (~3,34 s sur cinq).
La .030 essaie le réglage DMA Unsafe existant, avec précision GPU haute et
relecture des paramètres indirects conservées : image correcte, 8 FPS puis 3 FPS
plus loin selon l’utilisateur. La .031 réutilise des fenêtres GPU déjà relues lors
de la reprise des paramètres, invalidées à toute écriture GPU recouvrante.
Seuls les octets demandés sont copiés vers le jeu ; gain à mesurer.
Le correctif de gather FP16 est conservé.
La .014 paraît correcte visuellement selon l’utilisateur, mais reste à ~14 FPS.
Un gather FP16 encore refusé a été corrigé dans .015 ; la prochaine capture doit
séparer le coût vidéo de celui du rendu après le menu.
La conversion vidéo 4K est passée de 96,18 à 21,15 ms/image ; sur le même intervalle
vidéo, la cadence est passée de 7,04 à 14,96 images/s. Le menu atteint 59,94 FPS,
mais la .011 présentait des défauts graphiques après validation. La .012 corrige
deux formes de shaders de textures rejetées dans les logs. Les défauts sont réduits
selon l’utilisateur ; d’autres formes sont encore rejetées, le rendu reste à corriger.

Compilation exclusivement sur `build-server`, tests ciblés et progression incrémentale.
Sources et patches sont versionnés ; paquets, dumps, jeux, clés, SDK et copies de
travail des références restent locaux. Résultats : [TEST-REPORT.md](TEST-REPORT.md).

- Titre : `PPSA99862` — **Eden NX2 Prototype**.
- Données, sauvegardes, configuration et caches : `/data/eden-nx2`.
- Entrée du prototype : `/data/eden-nx2/game/exefs/main`, avec `main.npdm`,
  les autres modules ExeFS et le dossier `../romfs` du même jeu.
- Le point d'entrée est lancé s'il existe ; sinon le frontend indépendant s'ouvre.
- JIT MME NX2 graphique et compute activé ; ancien JIT des macros Maxwell désactivé.
- Découpage expérimental des threads GPU désactivé ; placement six cœurs + GPU si la topologie est validée.
- Auto-mise à jour désactivée, payload d'auto-remplacement non fourni.
- Installation séparée sur PS5 autorisée et réalisée le 31 octobre 2026 ; jeu non relancé automatiquement.

Les références exactes figurent dans `prototype.json`. `eden/` contient le port PS5,
les adaptations et les tests. `eden/tools/eden-patches/90-nx2-prototype.diff`
s'applique après les quatre patches source d'origine au cœur Eden épinglé.
`core/` est la copie de travail développée de ce cœur, pas un autre moteur installé.

## Adaptations EglantinePS5 — 00.040.000

Trois adaptations de `heydemoura/EglantinePS5` (`a2c5a908`) : buffers de transfert
Vulkan arrondis par pas de 16 Mio au-delà de 16 Mio, réutilisation selon leur capacité
réelle et libération des seuls buffers terminés/non différés avant une nouvelle
tentative après manque de mémoire ; signalement unique des commandes auto-stubbées
par service/commande, sans élargir la politique de réponse existante ; engagement
du heap par blocs physiques décroissants jusqu’à 2 Mio, avec rollback complet en
cas d’échec partiel et conservation de la continuité virtuelle.

Les tests ciblés s’exécutent avec `bash tests-nx2/run-eglantine-three.sh` sur `build-server`.
La validation hôte ne reproduit pas le pilote PS5. Aucun gain FPS/mémoire ni
correctif du comptoir noir n’est revendiqué. La réduction des mips BCn n’est pas importée.

## Compilation

Toutes les configurations et compilations, y compris les shaders et les tests C++,
s'exécutent sur `build-server`, jamais sur le Mac. La destination SSH se configure dans un fichier local ignoré par Git :

```sh
mkdir -p .local
cat > .local/remote-build.env <<'CONFIG'
EDGLANTINE_BUILD_HOST=build-server
EDGLANTINE_REMOTE_ROOT=/tmp/edglantine-ps5-build
CONFIG
```

`build-server` est un alias d’exemple à remplacer par votre serveur Linux.
Le répertoire distant doit contenir les dépendances préparées ; il est monté
comme `/work` dans le conteneur. `build-remote.sh` y synchronise ce projet.
Après compilation, `bash package-remote.sh` construit le dossier du titre,
réutilise le binaire déjà compilé, vérifie l’isolation du paquet puis récupère l’archive dans
`artifacts/`. Aucun de ces scripts ne contacte la console.
`make install` est désactivé dans ce projet.

Le cache source incorpore le hash du patch NX2 : modifier le patch recrée le cœur
préparé et réapplique les patches PS5 avant de reconfigurer. Les dépendances et
les flags sont ceux de ProsperoEden, épinglés dans `eden/tools/deps.json`.
La copie de l'archive originale du wrapper est conservée dans `sources/`.

## Validation effectuée

Le lien PS5 RADV/OpenGL, l'inventaire du paquet, les imports, l'alignement du SELF
et l'identité indépendante passent. Les tests hérités de chargement, de mémoire,
de JIT CPU, de diagnostic et de durée de vie des threads GPU ont passé après
adaptation de leurs attentes aux six cœurs et aux nouveaux appels NX2.
Les tests spécifiques vérifient les écritures différées concurrentes à six cœurs,
les accès exclusifs, la présence du JIT MME NX2 avec son allocateur PS5 dans le binaire et l'isolation des chemins.
Le test de réservation de 20 Gio avec 6 Mio réellement engagés utilise le backing
Linux, pas les API mémoire d'une PS5.

Les journaux de la version MME sont dans `artifacts/mme-jit/`. Le jalon graphique
précède l'activation compute ; son patch est conservé dans `milestones/graphics-mme.diff`.
Le journal `package.log` correspond au build final graphique + compute.

## Correctifs Eglantine — 00.032.000

Le pool du compilateur shader détruit maintenant chaque objet construit, et non
son union de stockage vide (`59047f0`). Les registres indéfinis SPIR-V U1/U32
produisent par défaut faux/zéro pour éviter les couleurs parasites observées
sur AMD dans Eglantine (`bb35360`). Les autres types restent inchangés.

Pour désactiver le correctif AMD sur PS5, créer le fichier vide
`/data/eden-nx2/undef-zero-off.txt`, puis fermer et relancer entièrement
l’application. Le supprimer et relancer réactive le correctif. L’environnement
`EDEN_NX2_UNDEF_ZERO=0` permet aussi sa désactivation avant le démarrage.
Le choix est figé pour le processus et journalisé. Les versions de cache Vulkan
38 (actif) et 39 (désactivé) remplacent la version 37 ; changer de mode rejette
l’ancien cache. Le sel du traducteur natif passe à `0x4f554e4345a00006`.
Aucun gain mémoire/FPS ni correctif visuel PS5 n’est encore mesuré.

## Intégration Eglantine et gather — 00.008.000

Référence Eglantine : `b40ad217ab829226841cb71f6e4c5cb05977a225`.
Correction des suites de pages après remapping, rejet des caches Vulkan tronqués,
notifications docké/portable NX2, métadonnées des dumps, décodage des seules couches
ASTC modifiées et libération des gros scratch CPU. Le chemin ASTC réutilise notre
suivi des pages ; `tex_partial=off` conserve le repli complet. La résidence sparse
sélective et la génération d'images FSR3 ne sont pas activées.

L'écriture atomique du cache était déjà présente dans le générateur PS5 ; elle
est conservée, avec les nouvelles validations de lecture. Les tests RET du fork
sont adaptés à nos contrôles de liaison existants, sans les assouplir.
Voir [l'inventaire d'intégration](milestones/eglantine-update/README.md).

Le correctif gather et l'identification du PANIC vidéo sont coordonnés dans
[milestones/gather-panic/ANALYSIS.md](milestones/gather-panic/ANALYSIS.md).
La requête Welcome Tour identifiée ensuite est H.264, et non VP8 ; son initialisation est corrigée depuis la .009.

## Gestion sparse expérimentale — 00.006.000

Le backend de couches sparse est intégré mais désactivé par défaut. L'opt-in
`EDEN_NX2_SPARSE_LAYERS=1` utilise des allocations par couche, toutes résidentes
avant publication, et des attentes GPU avant binding/libération. Les budgets
sont de 64 Mio par image et 128 Mio cumulés ; les dispositions non prises en
charge reviennent aux images classiques. En cas de fin GPU incertaine, les
allocations sont conservées et l'erreur remonte, sans libération hasardeuse.

Il n'y a pas encore d'éviction sélective des couches ni de gain mémoire mesuré.
Voir `milestones/sparse-layers/README.md` pour les garanties, tests et limites.

## Correctifs shaders — 00.005.000

Les annulations de barrières et les sorties de boucle sont soumises à la preuve
du chemin de sortie ; WARPSYNC doit correspondre à sa jonction. Les nouvelles
formes déjà prises en charge (stores vectoriels RZ, cube-array LOD zéro, RED MIN)
sont vérifiées par leur IR ou leur résultat, en conservant les variantes invalides.
Voir `milestones/shader-fixes/ANALYSIS.md`. Aucun test shader n'est exclu.

## Intégration Eden-NS2 — 00.004.000

Révision importée : `e2f285ab1ecd3a2475c2ccad66f23b06b94ead5c` de
`https://github.com/0x2593/Eden-NS2`. L'inventaire de fusion et les snapshots du
prototype précédent sont dans `milestones/ns2/`.

Les changements du moteur incluent les shaders natifs, les descripteurs et buffers
GPU, le streaming de textures et les transferts bornés, ainsi que leurs services
NX2 associés (horloge invitée, audio, vidéo et superviseur graphique). Les frontends
PC/Android et le changement Windows de `vfs_real.cpp` ne sont pas importés.
Le décodeur AV1 libgav1 est épinglé à `c1deec657b32b911920c78e078cfd089faa77200`
et utilise les mutex standard, sans exemples ni tests externes.

La génération des sources PS5 préserve les nouveaux chemins de pipelines différés
et de regroupement des buffers. Le suivi des pages partielles est celui de NX2 :
l'ancien suivi PS5 n'est pas superposé, pour ne pas décrémenter deux fois les comptes
de pages. `tex_partial=off` force encore le repli vers les transferts complets ;
les anciens compteurs/vérificateurs `tex_partial_check` ne mesurent plus ce chemin.
Les seuils mémoire PS5 et les allocations natives sont conservés ; le repli PC
vers une autre classe de mémoire hôte n'est pas activé. Le GPU split reste exclu.

Six cœurs applicatifs invités conservent leur identité ; les cœurs virtuels 6, 7
et 63 se traduisent vers le cœur système 3. L’ancien repli SVC modulo six a été retiré : il contredisait la table virtuelle,
perdait le bit 63 et pouvait transformer un identifiant Switch 1 invalide en
identifiant accepté. La validation porte sur les identifiants et masques originaux ;
la conversion physique reste dans le noyau. Les limites de cœur et les unités
d'horloge exposées aux processus hérités restent distinctes. Le test dédié vérifie
les traductions et les files d'écritures des six cœurs sous ASan/UBSan.

`tests-nx2/build-ns2-host.sh` compile les tests du moteur dans un build Linux séparé,
avec une copie indépendante des sources préparées. Les tests masqués de captures
commerciales ne sont pas activés. Cette validation hôte ne remplace pas une
exécution sur PS5.

## Apports Eglantine dans 00.004.000

Révision examinée : `6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba`,
`https://github.com/Djihads80/Eglantine`.
Deux adaptations sont retenues : statistiques vides avant initialisation et
notifications regroupées des grandes pages GPU (les petites pages l'étaient déjà).
Le nettoyage QMD inspiré de `6e7edd7` a été rejeté : la suite native_semaphore
montre qu'une suppression de l'historique fait rejouer un descripteur terminé
sur une action 2. Le comportement Eden-NS2 conserve cet historique.

Les tests dédiés exécutent les vraies méthodes de mise à jour des tables avec un
backend enregistreur et le véritable ordonnanceur QMD sous ASan/UBSan : plages
vides, inchangées, disjointes et longues ; conservation de l'historique
de complétion et des dépendances. Ils ne simulent pas le pilote graphique.

La piste de résidence sparse par couche est suivie dans [ROADMAP.md](ROADMAP.md).
La résidence sélective correspondante reste à porter (les uploads ASTC par couche
sont intégrés en 00.008) : ces modifications couplent l'allocateur Vulkan, les capacités du pilote, le suivi des blocs GPU
et les uploads ASTC. Les chiffres PC publiés dans les commits ne sont pas des
mesures PS5. Le split GPU, les adaptations MoltenVK et les changements du frontend
SDL ne sont pas importés.

## Caches ARM et placement à six cœurs — 00.003.000

`eden/headless/cpu_policy.h` définit 256 Mio pour le cœur invité 0 et 96 Mio pour
chacun des cœurs 1 à 5, pour ARM64 comme pour ARM32. Total : 736 Mio par architecture
active, contre 688 Mio dans le prototype précédent (+48 Mio de capacité).
Les instances hors des six cœurs restent à 16 Mio et le JIT nul à 8 Mio.
L'allocateur existant conserve son allocation progressive lorsque le backend
l'autorise. Ces budgets sont un point de départ, pas une optimisation mesurée sur jeu.

Le placement sonde les CPU autorisés avec CPUID et vérifie chaque changement
d'affinité. Il exige sept cœurs physiques distincts pour les six CPU invités et le
GPU. Les tâches auxiliaires utilisent un cœur physique supplémentaire lorsqu'il
est disponible, sinon les frères SMT des CPU invités ; le frère SMT du GPU est
exclu. Les threads connus `HostTiming` et `VSyncThread` suivent aussi cette règle,
même s'ils naissent sur un thread déjà épinglé.

Une topologie masquée, incohérente, insuffisante ou un refus de sonde laisse le
placement au système. L'ancien test de temps sur seulement trois CPU ne sert plus
à déduire une topologie complète. Si un pin individuel est refusé, le thread tente
de reprendre le masque initial du processus. Aucune disposition matérielle de la
console de l'utilisateur n'a été supposée ni interrogée.

Les journaux de cette version sont dans `artifacts/six-core-cpu/`. Les tests de
`tools/check-worker-affinity.py` exécutent le code de production avec des API
natives simulées : sept workers, permutations APIC/CPU, masques hérités, CPU
supplémentaires, exclusion du frère GPU, refus et restauration vérifiée.
Les contrôles des deux wrappers générés vérifient qu'ils utilisent la politique
commune, tout en conservant le petit cache du JIT nul. Les diagnostics CPU ciblés
acceptent maintenant les cœurs 0 à 5 et distinguent correctement le GPU (index 6).

## Portage MME

`core/src/video_core/macro_jit_ps5_allocator.h` utilise les fonctions de mémoire
directe du port : une vue RW/NX et une vue RX. Le Xbyak déjà adapté conserve les
adresses RX pour ses labels et tables de sauts, et écrit via la vue RW, y compris
lors des agrandissements. Aucun repli vers un mmap desktop exécutable/écrivable.
Chaque tampon est limité à 16 Mio ; le total des tampons est limité à 64 Mio,
hors métadonnées et pages d'en-tête, en comptant les remplacements en cours.

Un programme n'est publié qu'après sa génération et sa relocalisation complètes.
Un refus d'allocation ou de mapping fait utiliser le chemin sans JIT pour cette
génération de macros. Il n'y a pas de nouvelle tentative jusqu'à un changement de
génération ou une nouvelle instance. Une erreur après le début de l'exécution
reste une erreur : les commandes déjà émises ne sont pas rejouées.
Le GPU reste propriétaire unique de l'exécution ; le split-front reste exclu.

`tests-nx2/run-mme.py` compile sur le dédié les tests différentiels contre
l'interpréteur réel : arithmétique, branches/boucles, lectures de registres,
écritures/lectures de RAM MME, callbacks, FIFO qui se réalloue, erreurs,
AutoGrow avec table relocalisée, invalidation par génération, refus d'allocation
et d'alias, limites et libération. Le backend de test utilise des mappings Linux
RW/RX réels ; il ne simule pas l'exécution complète d'un jeu ni le matériel PS5.

Le binaire avec symboles et sa carte de lien restent dans le cache isolé du dédié
(`cache/ps5-eden-headless.c9cb1134b201/native-local/bin/`) pour un diagnostic futur.

## Limites

Compiler ne valide pas un jeu. Les services NX2 restent partiellement simulés et
les stages graphiques non implémentés par le fork restent absents. Le layout invité
réserve 12 Gio plus 8 Gio pour le serveur graphique ; le backing PS5 à la demande
est conservé, mais la mémoire réellement occupée doit encore être mesurée sur la
console. Les seuils du cache propres au pool partagé PS5 sont conservés.
Le HUD hérité présente encore quatre colonnes de charge CPU ; le moteur, ses files
et ses compteurs internes ont été adaptés à six cœurs.

Les fichiers du paquet ne doivent pas être copiés sur le titre de Botty ou de
ProsperoEden. L'identité séparée PPSA99862 a été enregistrée sur la console. La mise à jour
00.007.000 conserve cette inscription ; la fiche système peut encore indiquer
00.006.000. Le paquet actif est désormais 00.031.000 ; consulter `prototype.json` pour le rollback conservé.
