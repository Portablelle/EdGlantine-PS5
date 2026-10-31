# EdGlantine-PS5

Ce projet dérive de ProsperoEden 1.005.000 et du fork expérimental Eden NX2.
Il ne remplace pas Botty et ne modifie pas son moteur Switch 1.

**État : 00.012.000 installée et testée sur PS5, rendu encore partiellement incorrect.**
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

## Compilation

Toutes les configurations et compilations, y compris les shaders et les tests C++,
s'exécutent sur `build-server`, jamais sur le Mac. Le répertoire dédié est
`/tmp/ps5-nx2-prototype-20261030`, monté comme `/work` dans le conteneur de build.
Il contient des copies indépendantes des dépendances et du cache de compilation.
`build-remote.sh` synchronise uniquement ce prototype vers ce répertoire.
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
00.006.000. Le paquet actif est désormais 00.012.000 ; consulter `prototype.json` pour le rollback conservé.
