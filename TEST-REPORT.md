# 00.063.000 — paquet et installation Eglantine pages/textures

Version intégrée au binaire reconstruite sur `build-server` : PASS ; contrôles natifs et
paquet : PASS. Le contrôle d'isolation a été actualisé pour le split disponible
mais non armé au démarrage (demande explicite nécessaire), sans changer ce comportement.
70 fichiers vérifiés dans le staging en mode SELF brut avant publication.
Application fermée confirmée par l’utilisateur. Installation complète, sans relance.
Rollback intégral de la 00.062.000 : `/data/ps5-diag/nx2-rollback-062-20261101-eb9d8c35`.
Journal local : `artifacts/00.063.000/install-journal.json`.
Jeux, sauvegardes et réglages préservés. FPS et rendu à tester sur console.

---

# Intégration Eglantine pages/textures — 1er novembre 2026

Trois adaptations ciblées de zortos293/Eglantine (`badc91e`, `11a1108`) :
regroupement des pages partielles, propriétaire ASID courant et espacements
couches/lignes des transferts de textures. Changements préexistants préservés ;
seules trois sections du patch moteur ont été remplacées à partir de leur état
courant sauvegardé.

Compilation native PS5 sur `build-server` : PASS, contrôles intégrés : PASS.
Tests ciblés des méthodes réelles sous ASan/UBSan : PASS (A→B→A, comptage
exactement une fois sur 2 000 plages, couches/mips/padding/alignements).
Les décodeurs sont enregistrés dans le fixture : validation des paramètres de
transfert, pas des pixels ni de RADV.

Trois contrôles hérités ont été adaptés aux changements GPU déjà présents
(dix workers, hook de chargement, dépendances split des attentes).
Le test DMA a révélé une ancienne substitution CMake devenue inopérante :
la boucle pouvait ignorer l'arrêt. La garde d'arrêt est rétablie sans retirer
les contrôles d'erreur ni les traces NX2, avec ancres désormais obligatoires.
Le test d'arrêt sans signal et de remontée d'erreur du backend passe.

Binaire et journaux : `artifacts/eglantine-pages-textures/`.
Aucun déploiement, commit ou push. Version du titre inchangée ; aucun gain FPS
ni résultat graphique PS5 mesuré pour cette intégration.
Détails : [jalon](milestones/eglantine-pages-textures/README.md).

---

# 00.062.000 — snapshot DMA natif sur le propriétaire du cache

Build incrémental build-server et installation PS5 réussis. En split natif, copie des
nouveaux blocs sur le backend après travail antérieur ; test exact de saleté,
ReadBlock cohérent si dirty/safe, Unsafe si propre. Tampon possédé retenu à la
reprise d’acquire, solo et réglages inchangés. Compteurs snapshots/bytes/dirty.

Test utile build-server ASan/UBSan, vrai GpuSplit + helper de production : PASS. Écriture
mise en file, stale20 contre coherent99 ; propriétaire, plage/voisins, clean sans
readback, safe forcé et snapshot stable après mutation. Observateur/lifecycle
conservés. Risque de fraîcheur corrigé dans le code ; cause du gel console et coût
restent à mesurer.
Console : canal3, current29222 required29226 constants sur vingt samples.
14 snapshots DMA / 724 octets, dirty0, aucun nouveau snapshot après sample1.
La copie ordonnée ne résout pas cette attente observée ; aucun header sale capturé.
Aucun gain FPS revendiqué.
Aucun commit/push/Cubic. Détails : artifacts/profile-062/CHANGE.md.

---

# 00.061.000 — producteurs de calcul et état avant découpage

Build incrémental build-server et installation PS5 réussis. Baseline atomique depuis le
démarrage du worker et sérialisée avant activation. QMD signal/état/releases prévues,
callbacks natifs programmés (20) puis écrits (21 ou 1 pour addition). Les releases
max et reductions directes sont couvertes sans activer le CSV ni changer le jeu.

Test ciblé build-server ASan/UBSan PASS : baseline, QMD signal/état/plan, callback queue/write,
compteurs, correspondances et sérialisation, capture gate, fichier indépendant et
cycle de vie. Dernières valeurs approximatives, tous producteurs non couverts.
Console : baseline CPU0x1000 dernier write14924 ; après activation canal3 GEQUAL
minimum14928 mais14924 constant sur vingt samples. Un seul request/write
supplémentaire, CPU0x2020. Dernier QMD inspecté flags7 (loaded/scheduled/completed),
zéro dépendance/différé ; compteurs QMD inchangés après activation. Ceci ne prouve
pas que tous les QMD sont terminés. Producteur attendu non observé après passage
de relais ; aucun correctif du gel ni gain FPS revendiqué.
Aucun commit/push/Cubic. Détails : artifacts/profile-061/CHANGE.md.

---

# 00.060.000 — valeurs d’attente et reports de libération

Build incrémental build-server et installation PS5 réussis. Observateur dédié enrichi :
canal/ASID/adresses GPU et CPU, valeurs lue/attendue, opération, polls ; requests,
written, invalidated, unsynced des reports natifs, dernier report et correspondance
GPU/ASID ou alias physique. Aucun contournement de Matches, aucune activation du
CSV ni attente supplémentaire. Capture limitée à vingt samples indépendants.

Test utile build-server ASan/UBSan PASS : vrai observateur + hook de query, sortie relue,
compteurs et correspondances, capture désactivée, fichier indépendant et lifecycle.
Champs approximatifs et compteurs cumulatifs ; tous les producteurs ne sont pas
couverts.
Console : vingt samples complets, 53 381 polls. Canal 3/ASID 1, GEQUAL GPU
0x11d4940000/CPU 0x1000, valeur constante 16 953, minimum attendu 16 957.
Aucun report correspondant capturé ; seul request/write sur GPU 0x11d4941020,
CPU 0x2020, valeur 6479. Cela ne prouve pas l’absence de tous les producteurs ni
des releases antérieures. Aucun gain FPS revendiqué.
Aucun commit/push/Cubic. Détails : artifacts/profile-060/CHANGE.md.

---

# 00.059.000 — fiabiliser la sortie de l’observateur

Build incrémental build-server et installation PS5 réussis. Fichier dédié en append,
open/write contrôlés, écritures partielles/EINTR gérées. prepared avant création,
entered à l’entrée du thread, puis samples/complete et joined à l’arrêt. Erreurs
de première écriture explicites avant backend ; erreurs ultérieures conservées.
Démarrage toujours désarmé. Le gel n’est pas revendiqué corrigé.

Test utile ASan/UBSan build-server PASS : sortie dédiée malgré stderr entièrement bufferisé
et verrouillé, échantillons lus avant déverrouillage, ouverture/écriture défaillantes,
récupération, append, arrêt rapide et reprise.
Console : prepared/entered puis vingt samples et complete récupérés. Positions
publiées/consommées progressent à environ 13k mots/s ; backend surtout en attente
de travail, dernier callback toujours ReadNativeSemaphoreWord, symbolisé avec
l’ELF exact (biais 0x400000). Pas de verrou permanent de la file. Adresse, valeur
et libération du sémaphore non capturées ; même fonction ne prouve pas même adresse.
Aucun commit/push/Cubic. Détails : artifacts/profile-059/CHANGE.md.

---

# 00.058.000 — mesure indépendante des deux workers

Build incrémental build-server et installation PS5 réussis. Observateur natif distinct,
vingt instantanés atomiques à ~1 seconde d’intervalle, sans verrous des workers ni
logger ; écriture directe sur le descripteur stderr. Arrêt/join propre, nouvelle
instance à la reprise. Démarrage désarmé ; activation distante après lancement.

Test ciblé du vrai code sur build-server ASan/UBSan PASS : snapshot pendant callback
backend retardé et drain frontend, puis émission malgré stderr FILE verrouillé
alors que les deux workers attendent ; complétion, réveil, arrêt rapide et reprise.
Instantanés approximatifs des derniers jalons, sans stack ni garantie de cohérence
entre champs. Console : activation et backend prêts, 32 premières entrées terminées, gel confirmé.
Aucun instantané observateur retrouvé après 23 secondes. Écriture brute sur fd 2
non vérifiée ; exécution/sortie de l’observateur non établie. Le test hôte ne
valide pas la redirection console. Appel bloqué toujours inconnu ; aucun gain FPS.
Aucun commit/push/Cubic. Détails : artifacts/profile-058/CHANGE.md.

---

# 00.057.000 — capturer l’attente après activation du découpage

Build incrémental build-server et installation PS5 réussis. Trace bornée après une seconde
d’attente : frontend drain/espace, backend sans travail, dernière entrée exécutée,
positions et ancre de symbolisation. Attente DMA également signalée. Aucune
synchronisation contournée ; démarrage toujours désarmé.

Test ciblé ASan/UBSan build-server PASS : snapshot de callback retardé, backend vide,
complétion et réveil après timeout, arrêt et réarmement. Stress inchangés non répétés.
Activation console confirmée : backend prêt et 32 premières entrées terminées.
Aucun timeout drain/espace/idle/DMA émis, malgré marqueurs présents dans l’ELF
exact ; l’allocateur continue à logger. Appel bloqué non localisé. État visuel
après activation en attente de confirmation ; aucun gain FPS revendiqué.
Aucun commit/push/Cubic. Détails : artifacts/profile-057/CHANGE.md.

---

# 00.056.000 — démarrage sans découpage, activation distante en jeu

Build incrémental build-server et installation PS5 réussis. Démarrage sur le chemin à
propriétaire unique ; armement explicite via split-enable.request une fois le
personnage contrôlable. Marqueur de profilage indépendant, armement réinitialisé
sur nouvelle session. Corrections de complétion et hook de chargement conservés.

Test ciblé ASan/UBSan build-server PASS : démarrage désarmé, activation explicite puis
stress du vrai pthread, propriétaire, ordre, attente, données, erreurs et reprise.
Console avant activation : personnage contrôlable, 21 FPS, image correcte. Après
activation : requête consommée, backend prêt, premières 32 entrées terminées, puis
aucun nouveau relevé et stderr inchangé entre deux captures. Gel confirmé par l’utilisateur ; appel bloqué au-delà de la trace bornée encore
non identifié. Aucun gain mesuré. Aucun commit/push/Cubic.
Détails : artifacts/profile-056/CHANGE.md.

---

# 00.055.000 — progression du chargement sur le thread de rendu

Build incrémental build-server et installation PS5 réussis. Versions précédentes et .050
jouable conservées. Aucun commit/push/Cubic. Correction de complétion .054 conservée.

Le port avait désactivé le chargement côté frontend sans le transférer. Le backend
exécute maintenant Eden::LoadingTick pendant l’attente, avec timeout 1 ms seulement
pendant le chargement. Le frontend ne touche pas le renderer quand le split est
actif. Après présentation du jeu, attente normale sans polling de chargement.

Test ciblé du vrai split sur build-server ASan/UBSan : PASS, initialisation différée
terminée par le hook backend sans commande supplémentaire, propriétaire vérifié,
avec tests d’ordre, wrap, owned payload, offsets, réveils/erreurs/arrêt/reprise.
Compilation native réussie ; pas de répétition du test de complétion inchangé.
Détails : artifacts/profile-055/CHANGE.md. Résultat console : blocage à 99 %, sans nouvelle commande après les premières entrées terminées.

---

# 00.054.000 — corriger le cycle d’acquittement / file pleine

Build incrémental build-server et installation PS5 réussis. Versions précédentes et .050
jouable conservées. Aucun commit/push/Cubic. Le callback bloqué de .053 est
SignalCommand, symbolisé avec l’ELF exact (voir profile-053/block-observation.json).

Nouveau completion_lock indépendant de write_lock ; le producteur relâche son
verrou après enqueue avant d’attendre la complétion. Le backend peut acquitter
même si un autre producteur conserve write_lock sur une file pleine.

Tests ASan/UBSan build-server : ancien cycle reproduit ; code corrigé valide file pleine
et 100 courses de complétion. Test d’annulation du producteur sur code PS5 généré :
PASS. Compilation native PS5 réussie. Détails : artifacts/profile-054/CHANGE.md.

Résultat console .054 : toujours bloqué à 91 %. La trace confirme maintenant
end=28 : le callback SignalCommand retourne, mais aucune nouvelle entrée ne suit.
Le correctif de verrou est conservé ; il ne suffit pas au lancement. La progression
de chargement Vulkan était désactivée sur le frontend après activation du split,
sans être transférée au backend. .055 restaure ce service sur le propriétaire du
renderer pendant l’attente précédant la première image ; cause du blocage à confirmer.

---

# 00.053.000 — trace bornée des premiers callbacks du backend

Build incrémental build-server et installation PS5 réussis ; .052 et dernière version
jouable .050 conservées. Aucun commit/push/Cubic. Instrumentation seulement,
compilation native réussie ; pas de répétition du stress de file inchangé.

Trace begin/end des 32 premières entrées, type/position/cible de callback, ancre
pour le décalage ELF exact. .052 atteint ready et first_batch_words=20 puis bloque
à 91 % : le problème est postérieur à l’initialisation et au réveil du backend.
Détails : artifacts/profile-053/PROFILE.md. Capture .053 : entrées 0–27 terminées,
entrée 28 (pos 79, callback) sans sortie. Ancre runtime 0x27f1390 / ELF 0x23f1390,
décalage +0x400000. Cible 0x29d4590 / ELF 0x25d4590 = thunk RunWorker $_4,
SignalCommand. Désassemblage exact confirme la branche bloquante sous write_lock.
Le test de file pleine reproduit le cycle de verrouillage de l’ancien code ;
.054 sépare le verrou de complétion du verrou producteur.

---

# 00.052.000 — attentes bloquantes et backend prêt

Build incrémental build-server et installation PS5 réussis ; rollback .051 conservé,
ainsi que les versions jouables antérieures. Aucun commit/push/Cubic.

Corrige un risque de famine du backend : Drain/espace et attente de travail PS5
utilisent des condition_variables après un bref spin, avec notifications de
progression, arrêt et erreur. Handshake ready après enregistrement du thread et
traces bornées entry/named/ready/first_batch. La cause du blocage .051 à 91 %
reste à confirmer sur console ; pas de stack live disponible.

Test ciblé build-server ASan/UBSan : PASS, frontend <20 ms de CPU pour backend retardé
100 ms, plus stress 1,2 M méthodes, wrap, owned payload, offsets, propriétaires,
sync, erreurs, arrêt et reprise. Build PS5 natif réussi. Le test hôte ne valide
pas le démarrage console. Détails : artifacts/profile-052/CHANGE.md.

Résultat console .052 : blocage à 91 % à nouveau. Traces entry/named/ready et
first_batch_words=20 confirmées : le thread initialise correctement et commence
sa première séquence. Le blocage survient ensuite, pas avant ready. La cause
précise reste inconnue ; la modification des attentes n’a pas rétabli le lancement.
.053 ajoute la trace bornée begin/end des premières entrées et cibles de callbacks.

---

# 00.051.000 — premier portage PS5 du découpage CPU

Build incrémental sur build-server et installation PS5 réussis ; rollback .050 conservé.
Aucun commit/push/Cubic. Mode 1 activé : frontend de décodage, backend des moteurs,
MME JIT PS5, HLE indirect et renderer. Macros sur miroir frontend mode 2 non portées.
Précision GPU haute et instantanés de commandes possédés conservés ; lectures de
sémaphores/fences sur backend, ordre GEQUAL High conservé. Raccourci SSBO retiré.

Backend pthread PS5, pile 1 MiB, garde globale cohérente, contrôle du propriétaire,
propagation des exceptions, drain normal et join. Placement avec cœur physique
libre si disponible dans la topologie vérifiée, repli autorisé sinon. Animation
frontend suspendue une fois le backend propriétaire du renderer.

Tests utiles build-server sous ASan/UBSan : PASS. Vrai split cpp/header en branche pthread,
1,2 M méthodes, wrap, paramètres copiés/offsets, owner, sync après reset, changement
de précision DMA, exception, redémarrage et arrêt. Test de placement simulé : PASS.
Compilation PS5 native réussie. Ces tests hôte ne valident pas encore le rendu PS5.

Détails et harness : artifacts/profile-051/CHANGE.md et host-harness.
Essai console .051 : blocage au chargement à 91 %, jeu non lancé. Le cache de
358 pipelines est chargé (504 ms), puis seule la création du backend est annoncée.
Aucune erreur explicite dans les logs récupérés. Backend vivant/exécution non
établis ; diagnostic de famine d’ordonnancement possible, pas confirmé par stack.
Le debugger existant est indisponible (TCP 744 refusé), pas d’attachement effectué.
La .052 remplace les attentes actives/atomic.wait natives par des CV bloquantes
et ajoute un handshake ready ainsi que des étapes de démarrage. Aucun gain .051
revendiqué et aucun 30 FPS établi.

---

# 00.050.000 — réutiliser la préparation CPU des vues SSBO

Build incrémental build-server et installation PS5 réussis ; rollback .049 conservé.
Aucun commit/push/Cubic. Les vues read-only d’un même groupe peuvent reprendre son
buffer déjà préparé dans le dessin, si les sources CPU sont propres et les gardes
key/taille/offset/alignment valides. Écritures sources et libérations invalident le
raccourci. Le premier passage garde synchronisation et usage sur toute la plage.
Écritures, CPU dirty, groupe absent/invalide : chemin complet. Batch réinitialisé
à chaque dessin. NX2_PREPARED_STORAGE expose demandes/hits des candidats propres.

Test ciblé sur build-server sous ASan/UBSan des véritables méthodes frontend/runtime,
avec queue/allocations simulées : PASS (alias, invalidations, dirty CPU, writes,
formes/offsets/alignment et reset du dessin). Détails : artifacts/profile-050/CHANGE.md.
Résultat utilisateur .050 : 21 FPS, image correcte. Sur 20,099 s : 760925 demandes
de reprise, zéro hit. host_storage 1,675 s, proche des 1,625 s .049 ; aucun gain.
Ce raccourci n’est pas utilisé dans la scène ; retrait prévu au prochain build
fonctionnel. Les gains sampler et gathered des versions antérieures restent utiles.
Audit en lecture seule du fork PokeDinner : artifacts/pokedinner-source-audit.json.
Aucun patch externe ni nouvelle version installés pendant cet audit.

---

# 00.049.000 — retrait du cache sans hit et détail des liaisons

Build incrémental build-server et installation PS5 réussis ; rollback .048 conservé.
Aucun commit/push/Cubic. Le memo des mots handles est retiré (zéro hit) ; lecteur
u32 direct rétabli. Memo samplers et garde du diagnostic désactivé conservés.

Trois sous-compteurs dans la fenêtre CPU existante : host_uniform, host_storage,
host_texel. Ils sont inclus dans host_stage_bind, sans attente ni changement
d’ordre des opérations. Compilation native réussie ; pas de suite supplémentaire
pour ce retrait et ces compteurs. Détails : artifacts/profile-049/CHANGE.md.

Résultat utilisateur .049 : 21 FPS, image correcte. Fenêtre CPU fine vingt secondes :
host_storage 1,625 s, host_uniform 0,666 s, host_texel 0,038 s (inclus dans
host_stage_bind 2,505 s avec le coût de mesure). Stage_resources 1,346 s, fill_views
1,119 s, push_images 1,038 s. Pas de gain FPS visible sur .048 ; le retrait du cache
handles ne change presque pas les phases. La préparation SSBO devient la cible .050.

---

# 00.048.000 — lectures de ressources répétées dans un dessin

Build incrémental build-server et installation PS5 réussis ; rollback .047 conservé.
Aucun commit/push/Cubic. Tables bornées de 64 entrées à clés complètes pour handles
u32 et IDs samplers, recréées à chaque ConfigureImpl. Sur miss, lecteur typé original.
CaptureNativeSampler évite l’état TLS lorsque les diagnostics sont désactivés.
Compteurs NX2_DRAW_MEMO : requests/hits séparés pour handles et samplers.

Test ciblé du véritable header sur build-server sous ASan/UBSan : PASS, 200000 lectures,
collisions, zéro, exceptions, nouvelle instance au dessin suivant et IDs sampler.
Détails : artifacts/profile-048/CHANGE.md. Résultat utilisateur : 21 FPS, image correcte.
Sur 25,114 s : samplers 68622825 demandes / 67886784 hits (98,93 %), handles
68622825 demandes / zéro hit. Fenêtre CPU fine vingt secondes : stage_resources
1,466 s (contre 3,855 s en .047, avec davantage de dessins), fill_views 1,086 s,
host_stage_bind 2,243 s, push_images 1,039 s. Le cache sampler est très utile ; le
cache de handles sans réutilisation est retiré en .049. Les gains du memo sampler
et de la garde du diagnostic sont regroupés dans ce résultat, pas isolés.

---

# 00.047.000 — sous-compteurs CPU ciblés

Build incrémental build-server et installation PS5 réussis ; rollback .046 conservé.
Aucun commit/push/Cubic. Compteurs seulement, aucune optimisation revendiquée.
Sept composants sous la fenêtre CPU réarmable existante de vingt secondes :
synchronisation des pointeurs, ressources par stage, liaisons SSBO, image views,
liaisons de buffers par stage, descripteurs images et acquisition de leur file.
Les liaisons SSBO sont incluses dans les ressources par stage : durées imbriquées,
pas une somme de coûts exclusifs. Détails : artifacts/profile-047/PROFILE.md.

Compilation native incrémentale réussie ; pas de suite supplémentaire pour ces
compteurs. Capture console récupérée : stage_resources 3,855 s (incluant liaisons
SSBO 0,271 s), fill_views 0,993 s, synchronisation pointeurs 0,169 s ; host_stage_bind
1,961 s, push_images 0,914 s, acquisition descripteurs 0,023 s. Fenêtre fine de vingt
secondes, durée entre rapports 25,173 s. Le premier candidat CPU est la résolution
des ressources de shaders hors liaisons SSBO. FPS .047 non précisés par l’utilisateur.

---

# 00.046.000 — préparation CPU des tableaux de textures

Build incrémental build-server et installation PS5 réussis ; rollback .045 conservé.
Aucun commit/push/Cubic. Garde les correctifs .044/.045 qui ont donné 18 FPS utilisateur.

Validation de racine/taille/mapping une fois par descripteur et par dessin, exclusions
sur la même racine locale ; contenu et racine relus au dessin suivant. Scratch CPU
thread_local vidé chaque ConfigureImpl ; capacité des trois vecteurs réutilisée.

Test ciblé du véritable lecteur buffer_source sous ASan/UBSan sur build-server : PASS.
1024 éléments, nouvelle racine au dessin suivant et contrôles de rejet conservés.
Détails : artifacts/profile-046/CHANGE.md. Résultat utilisateur : toujours 18 FPS.
La mesure confirme des phases inchangées : configuration 9,878 s / vingt secondes
fines, lecture des ressources 5,112 s et descripteurs 2,907 s. Gather 21,28 Go/s,
scatter 11,02 Go/s, réutilisations 270,71 Go/s de payload évité. Aucun gain .046
observé. Cette optimisation ne touche pas le chemin coûteux observé ; .047 sépare
les composants CPU avant le prochain correctif. État visuel non précisé.

---

# 00.045.000 — invalidation des SSBO gathered dans le bon sens

Build incrémental build-server et installation PS5 réussis ; rollback .044 conservé.
Aucun commit/push/Cubic. SynchronizeBuffer renvoie true sans upload et false
après upload : BindMultiRangeStorage invalide maintenant dans le second cas.
Les invalidations exactes sur écritures et le suivi des propriétaires .044 sont
conservés. Aucun changement du gather/scatter des groupes writable.

Test ciblé de la véritable fonction sur build-server sous ASan/UBSan : PASS. Sources propres,
upload, puis 10000 liaisons inchangées ; polarité réelle du point d’intégration vérifiée.
Voir artifacts/profile-045/CHANGE.md. Résultat console utilisateur : 18 FPS (contre 8).
Sur 25,154 s : 65194 gather et 836726 réutilisations (~92,77 %), gather 21,35 Go/s,
scatter 11,05 Go/s et ~271,42 Go/s de payload recopié évité à ce rythme.
Temps couvert par timestamps GPU : 6,530 s sur 25,154 s (les intervalles incluent
les attentes internes). Fenêtre CPU fine de vingt secondes : configuration 9,863 s,
dont lectures des ressources 5,062 s et descripteurs 2,959 s. Le coût CPU ressort
nettement après suppression des copies redondantes. État visuel .045 non précisé.

---

# 00.044.000 — réutilisation des SSBO fragmentés en lecture seule

Build incrémental build-server et installation PS5 réussis ; rollback .043 conservé.
Aucun commit/push/Cubic. Test ciblé ASan/UBSan build-server : PASS, 200000 cas et retrait
correct d’un propriétaire gathered. Détails : artifacts/profile-044/CHANGE.md.

Réutilise les copies gathered des groupes en lecture seule jusqu’à une écriture
source recouvrante. Invalidation sur shaders, uploads/copies, fills et queries,
avec suivi des propriétaires gathered. Groupes writable conservateurs inchangés.
Compteurs des volumes gather/scatter/réutilisés et échantillons GPU des copies
ajoutés pour vérifier le mécanisme et le coût qui manque aux mesures .043.

Résultat console : 8 FPS, image correcte. Sur 25,327 s : 3,555 To de gather,
134,215 Go de scatter, zéro réutilisation. Soit ~140,36 Go/s de payload gather
(hors double trafic lecture/écriture). La condition d’invalidation est inversée :
SynchronizeBuffer=true signifie qu’aucun upload n’était requis. Cette condition
ancienne empêche toute réutilisation ; corrigée en .045. Aucun gain .044 observé.

---

# 00.043.000 — profilage CPU et opérations GPU ciblées

Build incrémental sur build-server et installation PS5 réussis ; rollback .042 conservé.
Aucun commit/push/Cubic. Les changements .040–.042 restent intégrés.

Le marqueur existant active vingt secondes de phases CPU et d’échantillonnage GPU
(dessins 1/64, compute 1/8), avec shaders et dimensions réelles des passes.
Lecture des requêtes sans WAIT, aucune soumission ajoutée, ring borné sans réutilisation
d’une paire encore en vol. Test ciblé ASan/UBSan de la véritable implémentation
sur build-server : PASS (ticket traversant une soumission, NOT_READY, saturation, désactivation).
Les intervalles GPU peuvent recouvrir du travail antérieur : pas de somme exclusive.

Capture console récupérée au contrôle du personnage. Sur vingt secondes de phases fines : configuration 5,238 s, dont lecture des ressources 2,596 s et descripteurs 1,685 s. Dessins GPU échantillonnés courts ; travail hors dessins non encore attribué. Aucun gain revendiqué.
Voir artifacts/profile-043/PROFILE.md et le test ciblé conservé avec le paquet.

---

# 00.042.000 — conserver les copies shadow entre les passes

Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .041 conservé. Aucun commit/push/Cubic.

Retire l’émission anticipée des snapshots à chaque fin de passe. Une simple fin
ou un changement de passe ne modifie pas les arguments ; les requêtes restent
annulables et groupables jusqu’à une soumission, une écriture source conflictuelle,
une lecture CPU, une libération ou la limite de capacité. Les autres gardes et
les améliorations .040 restent conservés. Aucune attente CPU ajoutée.

Test ciblé ASan/UBSan sur build-server : PASS. Vraies méthodes scheduler et garde d’upload,
262144 événements mixtes précédents plus deux cas explicites : 100 changements
de passe suivis d’annulation produisent zéro copie ; 100 requêtes survivantes entre
passes produisent une commande multi-régions à la soumission. Pas de suite générale.

Retour utilisateur : FPS inchangés. Fenêtre PS5 de 5,107 s : 47520 requêtes,
42458 annulations (89,35 %), 5062 régions dans 132 commandes / 118 lots,
40 conflits d’écriture, aucune soumission spéciale shadow et aucune relecture CPU
shadow. Le regroupement fonctionne mais ne donne pas de gain de fluidité observable.
Temps GPU de commandes : 4,506 s ; API WaitSemaphores : 2,348 s (40 appels),
QueueSubmit : 0,585 s (307 appels). Ces temps se recouvrent et ne s’additionnent pas.
L’appelant des longues attentes de retrait est FenceManager::WaitFence, symbolisé
avec l’ELF exact .042 et son décalage de chargement. Le temps GPU englobe aussi
les attentes internes ; il ne démontre pas une saturation des unités de calcul.

---

# 00.041.000 — copies shadow différées, annulables et groupées

L’autre agent a terminé ; améliorations .040 de staging, services et heap conservées.
Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .040 conservé. Aucun commit/push/Cubic.

Suppression du suivi par génération du buffer entier et des soumissions spéciales
pour les snapshots. Requêtes différées, bornées à 4096, annulées si le shadow est
entièrement réécrit avant émission. Les copies survivantes sont groupées par paire
source/destination, avec plusieurs régions et une paire de barrières par lot.
Emission dans le buffer principal à une frontière naturelle, avant une écriture
qui croise la source, avant libération, lors d’une observation CPU ou à la limite.
Les écritures hors des arguments ne déclenchent pas le lot. Les uploads CPU qui
croisent une lecture encore en attente restent après elle dans le buffer principal.
Pas d’attente CPU ajoutée pour les conflits ; staging réservé et source conservée
jusqu’à achèvement. Les anciennes protections géométrie, ABI et shadow demeurent.

Test ciblé sur build-server sous ASan/UBSan : PASS. Vraies méthodes du Scheduler et garde
d’upload extraites des sources de production, modèle ordonné GPU : annulation,
plages exactes, écriture/copie/réutilisation, frontières, libération, regroupement,
chevauchements de destination, capacité et 262144 événements mixtes. Pas de suite
générale ; code géométrie et ledger shadow inchangé, anciens tests non rejoués.

Essai .041 : fluidité inchangée. Capture : aucune soumission shadow spécifique
ni lecture CPU shadow ; mais 34107 lots pour 47472 demandes en ~5,057 s, sans
conflit d’écriture. L’émission à chaque fin de passe reste trop fréquente.

---

# 00.040.000 — transferts Vulkan, logs auto-stub et heap fragmenté

Source : heydemoura/EglantinePS5, `a2c5a9084c5d4c1d2a79db6d87480b0fe44b8f2b`.
Adaptation des trois pistes retenues ; aucune réduction des mips BCn importée.

Tests ciblés sur build-server, ASan/UBSan avec détection des fuites : PASS.
- Staging : seuil 16 Mio, 341 → 352 Mio au lieu de 512 Mio, capacité réelle,
  conservation des entrées différées ou encore utilisées, remise à zéro des curseurs.
- Heap : plage virtuelle continue avec blocs physiques bornés, échec de mapping
  à chaque bloc, mémoire épuisée, scratch saturé, alignement et dépassement d’adresse ;
  restitution complète des acquisitions partielles. Le helper de production est exercé
  avec un backend simulé ; les appels noyau PS5 ne sont pas exécutés sur l’hôte.
- Services : premier signalement par service/commande, répétitions silencieuses,
  politique désactivée conservée et concurrence de huit threads.

Le chemin natif lit explicitement `use_auto_stub.GetValue()` ; la conversion implicite
refusée au premier build a été corrigée. Build natif, contrôles intégrés et paquet
(version, imports, alignement et isolation PPSA99862) : PASS.
Installation PS5 réussie après confirmation de fermeture : 70 fichiers vérifiés
en staging, publication complète, rollback .039 conservé dans
`/data/ps5-diag/nx2-rollback-039-20261031-f330a829`. Application non relancée.
Aucun gain FPS/mémoire mesuré.
Archive : `artifacts/00.040.000/Eden-NX2-PS5-prototype-00.040.000.tar.gz`.
Logs de build/tests et paquet conservés dans ce même dossier.

---

# 00.039.000 — regroupement des copies shadow hors des passes de rendu

Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .038 conservé. Aucun Cubic, commit ou push.

Les copies shadow sont enregistrées dans le buffer de transfert exécuté avant
le buffer principal, sans interrompre la passe de rendu pour chaque copie. Si des
écritures principales de la source sont déclarées, elles sont d’abord soumises
sans attente CPU. Suivi des écritures shader, copies/remplissages et écritures de
requêtes ; distinction des uploads déjà ordonnés dans le buffer de transfert.
Les générations d’écriture ne dépendent pas d’un tick de déclaration, car la
préparation peut soumettre un contexte avant d’enregistrer le dessin. Les
barrières de transfert et les règles de lecture CPU shadow restent conservées.
Le réglage disable_buffer_reorder conserve le chemin principal précédent.

Test ciblé sur build-server, ASan/UBSan : PASS. Modèle de file asynchrone (upload avant
principal), réécritures GPU/CPU, répétitions en lecture seule, soumission pendant
préparation et 524288 événements ordonnés, comparés aux valeurs logiques attendues.
Les tests géométrie et suivi shadow précédents concernent du code inchangé et ne
sont pas rejoués. Un en-tête de compteurs manquant a été corrigé au build natif ;
la reprise incrémentale a réussi. Pas de suite générale.

Regroupement effectif, FPS et rendu PS5 .039 en attente. Aucun gain revendiqué.

---

# 00.038.000 — dessin indirect natif et suivi shadow différé

Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .037 conservé. Aucun Cubic, commit ou push.

La .037 n’utilisait jamais le HLE : shadow=1 (TrackWithFilter) déclenchait tous les
replis. La .038 conserve les gardes de code/SDK, topologie, adresses, CB0 et alias,
mais admet Track et TrackWithFilter avec un suivi différé des registres firstIndex,
indexCount, drawBegin et drawEnd, ainsi que de leurs copies shadow.

Copies GPU immuables de 20 octets avant réutilisation des arguments ; staging
réservé par moteur (1024 emplacements, au plus 64 propriétaires). Historique borné
à 8192 événements. Les comptes nuls conservent correctement les anciennes valeurs.
Une lecture réelle/relecture Replay ou une limite de capacité matérialise l’état ;
les réécritures CPU complètes annulent l’attente. Les écritures de valeurs identiques
à un ancien cache CPU restent prises en compte. Barrières transfert/CPU et attente
avant lecture ; staging réservé jusqu’à destruction après achèvement GPU.
Replay lui-même conserve l’ancien chemin de macro.

Tests ciblés sur build-server avec ASan/UBSan : PASS. Trace réelle et 4096 comparaisons
géométrie/bases ; suivi différé sur 524288 événements mixtes, comptes nuls,
réécritures partielles, observation, annulation complète, copies immuables et limite
de capacité. Pas de suite générale. Compilation native et packaging réussis.

Essai utilisateur .038 : 8 FPS, pas de nouveau défaut visible face à .037.
Capture : 148068 appels HLE acceptés, aucun repli, 148068 copies shadow, zéro
relecture CPU shadow et 1504 annulations par réécriture. Chemin GPU donc actif,
mais faible gain FPS. Copies par dessin : interruption de passe de rendu encore
présente dans cette version.

---

# 00.037.000 — première macro native remplacée par dessin indirect GPU

Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .036 conservé. Aucun Cubic, commit ou push.

Macro 0x1e7 : topologie + cinq arguments déjà au format Vulkan indexé indirect.
Pour le SDK reconnu et les formes admises, le dessin consomme directement les
arguments GPU sans RefreshParameters CPU. Gardes avant toute écriture : code et
SDK exacts, paramètres sales, topologie triangle à jour côté CPU, adresses mappées
et contiguës, shadow passthrough, liaison CB0 compatible et absence de chevauchement
physique avec ses constantes. Autres cas : chemin existant. Aucun rejeu après dessin.
Les bases shader utilisent les substitutions HLE existantes ; leurs constantes et
registres non temporaires finissent à zéro. ABI SDK reconnue pour les registres de
dessin temporaires. Admission native indirecte réservée au mode HLE Vulkan.
Trace générique de .036 retirée du chemin d’exécution.

Test ciblé sur build-server, ASan/UBSan : PASS. Trace MME réelle, 4096 comparaisons
aléatoires des géométries et de la remise à zéro des bases ; comptes nuls,
boucles d’instances, bases signées, rejets de code et d’adresses. Pas de suite générale.
Une erreur de nom de type dans l’adaptateur a été corrigée lors du build natif ;
la compilation incrémentale a ensuite réussi. Sémantique du test inchangée.

Essai utilisateur : 7 FPS avec chutes à 3. Capture : accepted=0, state_fallback=232762,
code_fallback=source_fallback=0 ; shadow=1 (TrackWithFilter) bloque tous les appels.
Le nouveau chemin GPU n’a donc pas été exercé. Le comptoir
noir reste non résolu ; aucun gain ni objectif 30 FPS validé à ce stade.
Désactivation possible par `/data/eden-nx2/native-draw-hle-off.txt`, puis relance
complète du prototype. Aucune modification des sauvegardes/réglages de jeu.

---

# 00.036.000 — ciblage des macros natives de dessin

Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .035 conservé. Aucun test supplémentaire,
Cubic, commit ou push. Pas encore de remplacement GPU ni de gain FPS revendiqué.

Le chemin natif Turing appelle RefreshParameters avant le JIT/interpréteur et
contourne les anciennes HLE Maxwell. Compteurs par méthode : appels, appels sales,
temps de relecture et nombre de paramètres. Après réarmement en contrôle réel,
capture bornée de quelques méthodes les plus coûteuses : code, paramètres,
adresses sources, registres, RAM avant/après et événements d’écriture/lecture.
Limites : 16 échantillons par exécution, 4096 événements par échantillon.
Capture PS5 récupérée : macro 0x1e7 dominante, code/état/trace sauvegardés.
Le test ciblé de .037 réutilise cette capture.

---

# 00.035.000 — capacité du cache ciblé de paramètres

Build incrémental sur build-server et installation PS5 réussis après fermeture confirmée.
70 fichiers vérifiés en staging ; rollback .034 conservé. Pas de tests
supplémentaires, Cubic, commit ni push.

Cache : 64 fenêtres de 64 Kio au lieu de 4, soit au maximum 4 Mio retenus.
Motivation : mesure .034 en contrôle effectif, 93,6 % des remplissages
remplacent une entrée valide. Les invalidations à chaque écriture GPU et les
copies des seuls octets demandés/modifiés restent inchangées. Essai utilisateur :
7 FPS en contrôle réel ; aucun gain FPS établi. Dernière fenêtre ~5,113 s :
11 707 succès, 1 185 remplissages, zéro éviction de capacité, 1 194 invalidations
GPU et zéro vidage. Attentes Vulkan de sémaphore ~2,595 s dans cette fenêtre ;
les durées CPU/GPU peuvent se recouvrir.

L’utilisateur voit des zones noires attachées aux mêmes surfaces du décor.
Aucun refus shader capturé ; cause visuelle non établie, pas de correctif visuel
revendiqué pour ce changement de capacité.

---

# 00.034.000 — mesures relançables pendant le contrôle du personnage

Build natif incrémental sur build-server et installation PS5 réussis, après fermeture
confirmée. 70 fichiers vérifiés en staging ; rollback .033 conservé.
Pas de tests supplémentaires, Cubic, commit ni push.

Marqueur `/data/eden-nx2/profile-refresh.request` : un nonce distinct relance
les fenêtres bornées des compteurs GPU/API et des sites d’attente. Les états par
thread sont réinitialisés hors des scopes actifs. Compteurs légers du cache de
paramètres : succès, échecs, remplissages, octets, évictions, invalidations et
vidages. Les agrégats restent cumulatifs et leurs durées peuvent se recouvrir.
Aucun changement de politique du rendu/cache. Essai utilisateur : contrôle du
personnage atteint, zones noires dans le décor. Réarmement epoch=2 confirmé.
Sur 5,039 s : 12 339 succès, 4 503 échecs/remplissages, 4 215 évictions de
capacité, 288 invalidations GPU, aucun vidage ; 295 108 608 octets remplis.
Ce relevé motive une capacité supérieure ; il n’établit pas la cause des défauts
visuels. Aucun refus shader dans les logs de cette capture.

---

# 00.033.000 — report CPU avec le moteur intégré .032

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; fermeture confirmée par l’utilisateur,
rollback .032 conservé. Aucun nouveau test, Cubic, commit ou push.

Seul changement de comportement : cpu_write_defer=true au démarrage de session.
Le moteur préparé correspond au patch .032 avant compilation ; corrections du
pool shader et des valeurs AMD indéfinies conservées, ainsi que DMA directe et
cache ciblé de paramètres. Les régressions shader .032 portent sur le code inchangé
et n’ont pas été rejouées. Essai utilisateur : image correcte, 10–12 FPS sur
un premier écran, 4 FPS sur une séquence suivante, puis environ 9 FPS en contrôle
effectif du personnage. Aucun arrêt moteur dans les logs capturés jusqu’à ~221 s ;
les compteurs bornés expirent avant la phase de contrôle.

---

# 00.032.000 — fuite du pool shader et valeurs indéfinies AMD

Compilation PS5 sur `build-server` et contrôles intégrés du build : PASS.
Packaging et contrôle d’isolation PPSA99862 : PASS. Archive récupérée localement.
Installation PS5 effectuée ensuite à la demande de l’utilisateur : 70 fichiers
vérifiés dans le staging avant bascule, fermeture complète confirmée.
Rollback .031 : `/data/ps5-diag/nx2-rollback-031-20261031-44b2fb0e`.
Journal : `/data/ps5-diag/nx2-install-032-20261031-44b2fb0e/install-journal.json`.
Aucune application ni jeu lancé par l’installateur. Essai utilisateur ultérieur :
jeu lancé, écran jouable à 8 FPS ; boot .032 confirmé dans les logs.

- Eglantine `59047f0` : destruction des objets T construits dans les chunks du pool,
  libérant notamment les allocations possédées par les instructions Phi.
- Eglantine `bb35360` : U1/U32 indéfinis SPIR-V remplacés par faux/zéro par défaut.
  Désactivation par `EDEN_NX2_UNDEF_ZERO=0` ou le marqueur
  `/data/eden-nx2/undef-zero-off.txt`, lu au démarrage de la session ; relance
  complète de l’application nécessaire. Choix journalisé, disponible en release.
- Versions de cache Vulkan : 38 actif, 39 désactivé (ancienne : 37), évaluées
  après les réglages de démarrage. Changer de mode rejette l’ancien cache.
  Sel du traducteur natif : `0x4f554e4345a00006`.
- Régression ciblée sur les headers de production préparés, compilée sur build-server
  sous ASan/UBSan/LSan : PASS. Pool vide, déplacement des chunks, consolidation,
  réutilisation, libération répétée et destruction finale ; 19 objets possédant
  chacun une allocation, tous détruits. Trois processus testent le défaut,
  la désactivation et l’activation explicites, ainsi que la cohérence mode/cache
  et son maintien après modification de l’environnement en cours de processus.
- Pas de nouvelle exécution de la suite générale moteur. Les tests ciblés ne
  simulent pas un rendu AMD : aucun gain mémoire/FPS ni effet visuel PS5 mesuré.

Archive : `Eden-NX2-PS5-prototype-00.032.000.tar.gz` (43782142 octets).
SHA256 : `1c4352ae977acbfa99a0dbe89c3854e6cd780ebf087e176a27841d51953c442f`.
Journaux locaux : `artifacts/00.032.000/{build,package,shader-regression-032}.log`.
Aucun commit ni push.

Capture utilisateur .032 : sur ~5,08 s, 3377 attentes de sémaphore Vulkan /
~2,70 s et ~2,27 s cumulées de callbacks d’écriture CPU. Les durées se recouvrent.
Cela ne mesure pas l’effet isolé du cache .031 ni celui des deux corrections .032.

---

# 00.031.000 — cache ciblé des relectures de paramètres

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .030 conservé. Aucune suite générale, Cubic, commit ou push.

Quatre fenêtres GPU de 64 Ko logiques au maximum sont réutilisables uniquement
dans les plages exactes/contiguës de RefreshParametersImpl. Seuls les octets
GPU modifiés demandés sont copiés vers le jeu. Chaque enregistrement d’écriture
GPU invalide les fenêtres recouvrantes, même si la plage était déjà sale ;
suppression de buffer/réinitialisation les effacent. Les lecteurs hors reprise
des paramètres et les lectures grandes/traversant une fenêtre gardent le chemin
existant. Ce bornage exclut les préparations d’écriture GPU avant leur enregistrement.

Méthode de production + vrai cache/RangeSet, tracker/runtime simulés sur build-server,
ASan/UBSan : PASS. Réutilisation sans attente, copies exactes, nouvelle écriture
GPU sur plage déjà sale, ownership CPU, reset, fallback entier, LRU borné et
interdiction de réutilisation hors plage de paramètres, notamment entre déclaration
et exécution d’une écriture. Cela ne qualifie pas le driver réel.

Résultat FPS/image/stabilité PS5 .031 en attente.

---

# 00.030.000 — lecture directe des blocs DMA

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; fermeture confirmée par l’utilisateur,
rollback .029 conservé. Aucun test supplémentaire, Cubic, commit ou push.

Le prototype sélectionne le réglage existant DmaAccuracy::Unsafe pour les blocs
DMA, lecteur dominant confirmé en .029. La précision GPU reste High, les paramètres
indirects/macro modifiés gardent leur relecture explicite et le stockage possédé
des commandes ainsi que les garde-fous restent actifs. Aucun faux signal de fence.

C’est une comparaison d’accuracy DMA, pas une validation générale des commandes
produites par le GPU. Essai .030 : écran jouable/image correcte selon l’utilisateur, 8 FPS initialement
puis 3 FPS plus loin. Logs actifs jusqu’à ~56,4 s sans erreur capturée dans cette
fenêtre. Le volume d’attentes baisse, mais les relectures restantes de petits
paramètres de macros dominent encore. Le gain initial ne règle pas la cadence
des scènes plus lourdes.

---

# 00.029.000 — origine et volume des relectures

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; fermeture confirmée par l’utilisateur,
rollback .028 conservé. Aucun test supplémentaire, Cubic, commit ou push.

Même histogramme borné que .028, complété aux appels MemoryManager::ReadBlock et
RasterizerVulkan::FlushRegion, avec volumes demandés. Cela doit distinguer les
lecteurs à l’origine des attentes sans modifier la synchronisation. ELF/map exacts
.029 conservés sur build-server. Mesure PS5 : écran jouable atteint. Ancre runtime 0x27e9d40 moins ancre ELF
0x23e9d40 confirme la relocation 0x400000. Appelant ReadBlock brut 0x29c6b46,
ELF 0x25c6b46 : DmaPusher::DispatchCalls, Step intégré. Dernier intervalle de
5,000009517 s : 218 743 lectures, 31 830 468 octets, 3,340 s cumulées. Les autres
lecteurs mesurés sont secondaires. Aucun gain FPS revendiqué pour cette mesure.

---

# 00.028.000 — attribution bornée des attentes GPU

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .027 conservé. Aucun test supplémentaire, Cubic, commit ou push.

Histogrammes thread-local aux entrées BufferCacheRuntime::Finish, Scheduler::Finish
et MasterSemaphore::Wait : nombre/durée par appelant, 24 sites plus débordement,
relevé toutes les cinq secondes, trois minutes maximum par thread. Ancre runtime
pour symbolisation exacte ; ELF/map .028 conservés sur build-server. Durées imbriquées,
non sommables. Ni attente ajoutée/supprimée, ni changement de cache.

Version de mesure, pas gain FPS revendiqué.

Mesure .028 : écran jouable atteint. L’ancre runtime 0x27e9d50 et l’ancre ELF
0x23e9d50 établissent la relocation 0x400000. L’appelant brut 0x282815b correspond
à ELF 0x242815b, BufferCache<Vulkan>::DownloadBufferMemory : 29 397 appels /
~3,262 s pendant la fenêtre active de cinq secondes, proche du nombre de draws.
Les autres attentes enregistrées restent secondaires dans cette fenêtre.
L’origine du lecteur doit encore être distinguée ; .029 étend ce relevé.

---

# 00.027.000 — lectures exactes de pointeurs SSBO groupées

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .026 conservé. Aucune suite générale, Cubic, commit ou push.

Les pointeurs SSBO actifs sont regroupés avant liaison graphique/compute native.
Leurs intersections GPU modifiées utilisent un staging et une attente par lot.
Seuls les octets demandés sont réécrits ; les voisins restent modifiés. Le chemin
individuel existant sert de secours, notamment pour les trous et passages de page.

Méthode de production, vrai RangeSet, tracker/runtime simulés, ASan/UBSan sur build-server :
PASS. Une attente, octets exacts, doublons, deux buffers, valeurs partiellement
modifiées, état restant, exclusion CPU-owned, trous/passage de pages, lot vide/propre.
Cela ne valide pas le driver réel.

Essai .027 : écran jouable selon l’utilisateur, toujours 6 FPS. Logs actifs
jusqu’à ~68,3 s, sans capture DMA, compute hors plage ou exception worker dans
cette fenêtre. Les attentes restent ~29 104 appels / ~3,20 s sur le dernier
intervalle ~5,06 s, comparables à .026. Aucun gain FPS observé ; leur provenance
dominante reste à mesurer.

---

# 00.026.000 — arrêt compute explicite et observations de blocs modifiés

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .025 conservé. Aucun nouveau test, Cubic, commit ou push.

Notifications CPU immédiates rétablies, drains ajoutés à FlushRegion en .025
retirés, relecture précise .023 conservée. Les méthodes compute hors banque
échouent explicitement dans le prototype ; le DMA capture le bloc au lieu de
laisser le moteur accepter ces méthodes et répéter les erreurs.

Quatre observations maximum comparent des entrées courtes complètes (<=64 mots)
avec leur état soumis avant exécution. Une différence seule ne modifie ni n’arrête
le flux : les données produites par le GPU peuvent légitimement changer. La raison
de capture distingue observation et exception moteur. Résultat PS5 en attente ;
aucune résolution générale de la corruption ni amélioration de cadence revendiquée.

Essai réel .026 : écran jouable atteint selon l’utilisateur, 6 FPS. Logs actifs
jusqu’à ~64,9 s, sans capture DMA, compute hors plage, moteur non lié ou exception
worker dans cette fenêtre. Observation limitée, pas une validation exhaustive.

---

# 00.025.000 — notifications CPU avant la relecture GPU

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .024 conservé. Aucun test général, Cubic, commit ou push.

Avant les verrous de FlushRegion, FlushCaching applique les notifications CPU
puis InvalidateGPUCache applique les plages d’invalidation collectées. Une portée
thread-local force la reprise GPU à prendre les verrous sans remettre les écritures
en file ; le report reste actif sur les threads invités. Relecture précise .023
conservée. Captures étendues à 64 mots pour couvrir les petits blocs entiers.

Seul contrôle ciblé sur build-server, ASan/UBSan : portée et fonction de verrouillage
réelles extraites ; report normal, verrouillage forcé, portées imbriquées et
indépendance d’un autre thread : PASS. Ce contrôle ne qualifie pas le driver réel.
Essai .025 : écran noir bloqué signalé par l’utilisateur. Les logs atteignent
~38,9 s et répètent des méthodes compute hors banque 0x1f36/0x1f37 ; aucun arrêt
GPU-worker explicite n’est capturé dans stderr. Le correctif d’ordre n’a pas évité
ces commandes invalides. Aucun succès de stabilité ou cadence revendiqué.

---

# 00.024.000 — report CPU rétabli, relecture précise conservée

Build natif incrémental sur build-server et installation réussis, 70 fichiers vérifiés
avant publication. Fermeture confirmée par l’utilisateur, rollback .023 conservé.
Aucun nouveau test, Cubic, commit ou push.

Le démarrage de session réactive cpu_write_defer, désactivé pour la comparaison
.021. La relecture GPU précise de .023 et la désactivation de la trace lourde
restent identiques. Les cinq cas ciblés .023 portent sur le même code de relecture
et n’ont pas été rejoués.

Essai .024 : arrêt DMA à 36,28 s, canal 1 / sous-canal 6 / méthode 0x252,
bloc de 58 mots, erreur à +0x8c. Les 64 premiers octets sont identiques à la
soumission, avant lecture et dans la copie possédée ; les mots plus loin ne sont
pas capturés à la soumission. Pas de conclusion sur leur moment de mutation.
La .025 capture jusqu’à 64 mots et applique les notifications/invalidation CPU
avant la relecture GPU, avec reprise synchrone sur le seul thread GPU.

---

# 00.023.000 — relecture GPU à la plage demandée

Build natif incrémental sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .022 conservé, .014 reste le secours visuellement testé.
Aucune suite générale, Cubic, commit ou push.

DownloadBufferMemory borne désormais les relectures du prototype à la requête
et aux limites du buffer. Seuls les intervalles réellement copiés sont nettoyés ;
les indicateurs de pages sont rétablis pour les données GPU voisines encore
modifiées. Le registre de provenance lourd de la .022 est désactivé par défaut.
Les captures de préfixes et l’arrêt explicite sur moteur absent sont conservés.

Seule vérification ciblée : méthode de production extraite, vrai Common::RangeSet,
runtime GPU et indicateurs de pages simulés sur build-server, ASan/UBSan : 5 cas PASS.
Lecture de 4 octets, 1 octet désaligné, traversée de page, buffer entier et requête
couvrant plusieurs buffers. Octets voisins, relectures suivantes, intervalles
asynchrones et indicateurs GPU vérifiés. Cela ne valide pas le driver Vulkan réel
ni la console.

Essai .023 : l’utilisateur confirme l’écran jouable encore ouvert, 6 FPS et léger
grésillement physique. Logs actifs jusqu’à environ 65 s sans nouvel arrêt DMA,
au-delà des échecs précédents. Observation limitée à cet essai, pas une validation
générale de stabilité. Cadence insuffisante. La .024 conserve la relecture précise
et rétablit le report CPU pour isoler son impact après la comparaison .021.

---

# 00.022.000 — provenance des écritures vers les commandes en attente

Build natif incrémental exclusivement sur build-server, packaging et installation réussis.
70 fichiers vérifiés avant publication ; prototype fermé par l’utilisateur,
rollback .021 conservé. Aucun test général, Cubic, commit ou push.

Capture bornée du dernier Write/WriteBlock/WriteBlockUnsafe vers le préfixe d’une
commande en attente : plage, octets source et adresse brute de l’appelant hôte.
Les notifications CPU Vulkan et les pointeurs hôte à la soumission/à l’échec sont
également conservés. Une notification CPU n’est pas une preuve de la valeur finale
d’une écriture invitée ; l’absence d’événement ne couvre pas les écritures directes
non instrumentées. Les copies ne servent jamais à réparer ou exécuter les commandes.
Résultat réel : écran jouable brièvement ouvert, ~7 FPS selon l’utilisateur,
puis retour au lanceur à 48,51 s. La trace identifie une écriture moteur de 4 Ko
à device 0x15fc7d000 via DeviceMemory::WriteBlockUnsafe. Ses octets source à
l’offset 0x100 correspondent exactement au préfixe de commandes corrompu.
Pointeur hôte inchangé. Appelant brut 0x2827424 ; après relocation 0x400000,
ELF 0x2427424 dans BufferCache<Vulkan>::DownloadBufferMemory. Appel indirect
immédiatement précédent vérifié dans l’ELF exact conservé sur build-server.
Le chemin de relecture est confirmé ; les circonstances qui marquent la page
GPU-modifiée restent à préciser. Trace lourde retirée de la .023.

---

# 00.021.000 — notifications CPU immédiates dans le prototype

Build incrémental exclusivement sur `build-server`, packaging puis installation réussis.
70 fichiers vérifiés avant publication ; application fermée par l’utilisateur,
rollback complet .020 conservé. Aucun test général, Cubic, commit ou push.

Seul changement de comportement : cpu_write_defer=false par défaut sous
EDEN_NX2_PS5_PROTO. Les notifications d’écriture CPU prennent immédiatement
les verrous des caches au lieu d’être reportées. Ce choix isole une hypothèse
d’ordre des écritures ; la .020 prouve une mutation du bloc entre soumission
et lecture mais n’en identifie pas l’auteur. Captures et garde-fous DMA conservés.
Essai réel .021 : retour au lanceur à 37,78 s, entrée 3876/5140,
canal 1 / sous-canal 5 / méthode 0x10be. À GPU 0x1f8342da80 et device
0x15d89da80, le préfixe soumis valide est remplacé par des zéros avant lecture
normale. Avant lecture, possédé et live concordent. Le report des notifications
CPU n’est donc pas nécessaire à la mutation ; l’auteur reste inconnu.

---

# 00.020.000 — préfixes DMA attachés aux lots

Compilation native incrémentale sur `build-server`, packaging et installation réussis.
70 fichiers vérifiés avant publication, application fermée par l’utilisateur,
rollback .019 conservé. Aucun test général, Cubic, commit ou push.

Le préfixe de soumission est désormais transporté avec son `CommandList`, au lieu
de dépendre d’un historique partagé borné. À l’arrêt, la capture contient aussi
le préfixe avant lecture normale, le bloc possédé et le préfixe mémoire courant,
avec les adresses GPU/CPU et l’état initial du parseur. Ces copies servent uniquement
au diagnostic ; les commandes et la synchronisation gardent le même chemin.
Essai .020 : retour au lanceur à 36,41 s. Entrée 2261/5140, GPU 0x1ec04c2980,
adresse device 0x162103980 identique à la soumission et à l’exécution.
Le préfixe soumis est une suite de commandes valide ; son contenu change avant
la lecture normale. Préfixes avant lecture / possédé / relu après échec identiques.
Le lecteur normal n’est donc pas l’opération qui introduit ce changement observé.
L’auteur de l’écriture reste indéterminé. Aucun appel 0x18f enregistré avant l’arrêt.
La .021 désactive le report des notifications CPU comme comparaison contrôlée,
sans prétendre que ce mécanisme est déjà prouvé responsable.

---

# 00.019.000 — capture du bloc DMA rejeté

Build incrémental sur build-server puis installation : réussis. 70 fichiers vérifiés,
rollback .018 conservé. Aucun test général, Cubic, commit ou push.

L’utilisateur a corrigé sa première réponse : le jeu n’avait pas été relancé.
L’essai réel reproduit le retour au lanceur après validation du menu : arrêt
GPU explicite à 34,52 s sur canal 1 / sous-canal 6 / méthode 0xebc.
Bloc de 59 mots, GPU 0x1f82cdd280 ; les mots possédés sont identiques au préfixe
mémoire relu après l’échec. Aucun appel 0x18f n’est enregistré. Le préfixe de
soumission est absent de l’historique borné (séquence 0) ; aucune conclusion
sur le moment où ces données deviennent invalides. La .020 remplace cet historique
par des préfixes attachés aux lots et capture aussi avant lecture avec flush.

---

# 00.018.000 — isolation MME 0x18f avant exécution

Build incrémental sur `build-server`, packaging puis installation PS5 réussis.
Application fermée par l’utilisateur ; 70 fichiers vérifiés avant publication.
Rollback .017 conservé ; .014 reste le secours visuellement testé.
Aucune suite générale, aucun Cubic, commit ou push.

Le macro 0x18f choisit l’interpréteur avant toute exécution et ne passe pas par
le cache mémo. Aucun JIT échoué n’est rejoué. Les autres macros gardent leur chemin.
Quatre captures au maximum sauvegardent code, paramètres et DRAM initiaux ;
128 émissions au maximum sont tracées. Il s’agit d’une isolation, pas d’un gain
ou d’un correctif matériel déjà validé.

Essai .018 : retour au lanceur après exception GPU explicite à 35,52 s,
canal 1 / sous-canal 7 / méthode 0x70 / compteur restant 8186, bloc GPU
0x1f82d47780 + 8. Aucun appel du macro 0x18f n’est enregistré avant cet arrêt ;
cet essai ne tranche donc pas la comparaison JIT/interpréteur.

---

# 00.017.000 — copie possédée des commandes DMA natives

.016 reproduit le même SIGSEGV après 56 secondes, dans DmaPusher::CallMethod,
moteur nul et méthode 0x800. Retirer le suivi détaillé n’a pas suffi : celui-ci
n’est pas nécessaire au crash. La source exacte du flux invalide reste indéterminée.

.017 remplace la vue directe de mémoire invitée par le scratch possédé du canal
pour les commandes natives, conservé pendant une acquisition suspendue. Les
lectures sûres/unsafe respectent le réglage existant. Les préfetches déjà possédés
et les canaux non natifs gardent leur chemin. Une commande sans moteur lié échoue
avec contexte explicite avant déréférencement, sans être ignorée et sans faux signal
GPU de complétion. Candidat de stabilité, pas cause racine déjà prouvée.

Build incrémental exclusivement sur `build-server`, packaging et installation enchaînés
dans une exécution attachée ; résultat final réussi, logs conservés en fichiers.
Aucune suite générale, Cubic, commit ou push. Application fermée par l’utilisateur,
staging vérifié et activation réussie. Rollback .016 ; .014 reste le secours
visuellement testé. .017 revient au lanceur après une exception GPU explicite :
moteur DMA non lié, canal 1 / sous-canal 6 / méthode 0xfa7. Pas de nouveau rapport
de crash natif. Une erreur FIFO MME 0x18f précède cet arrêt ; sa causalité reste à établir.

---

# 00.016.000 — isolation du crash .015

Le retour au lanceur signalé par l’utilisateur correspond à un crash .015, pas à
une sortie normale du jeu. Rapport natif : SIGSEGV sur le thread GPU après 36 s,
lecture à 0x360 dans DmaPusher::CallMethod depuis un pointeur de moteur nul.
Une erreur MME « parameter FIFO underflow » précède le crash ; son rôle causal
n’est pas établi. Les adresses de pile marquées `?` ne prouvent pas une réentrance.

.016 désactive uniquement les hooks détaillés dev_marks ajoutés en .015 en build
ordinaire ; le shader FP16 reste identique. C’est une comparaison contrôlée,
pas une cause racine déjà démontrée ni un correctif de parseur spéculatif.
Build incrémental sur `build-server` : 12 objets, packaging et installation directe.
Pas de nouveaux tests hôte, Cubic, commit ou push.

App fermée par l’utilisateur avant remplacement. Rollback .015 préservé ; .014
reste disponible comme dernier secours visuellement testé. Essai .016 en attente.

---

# 00.015.000 — gather FP16 et mesure après le menu

Build natif incrémental sur `build-server` (31 objets), packaging puis installation directe.
Seul contrôle hôte : le gather réellement refusé et les quatre cas .014 passent
le lowering de production. Pas de suite générale, Cubic, commit ou push.

Gather FP16 : les quatre valeurs sélectionnées sont conservées puis empaquetées
par paires dans les sorties R2/R3, sans l’alignement F32 auparavant imposé à tort.
Banque/offset du descripteur et composante de gather conservés ; autres modes rejetés.

Mesure de la phase jouable : compteurs de préparation des dessins activés avant
le démarrage des workers ; arrêt après trois minutes de présentation, même HUD
masqué. Au plus 36 rapports de cinq secondes. Pas de PC sampling, readback ni
modification des attentes GPU. Les durées de phases imbriquées ne s’additionnent pas.

Installation : staging vérifié puis activation, rollback .014 conservé. Essai .015
en attente. Le bruit physique signalé sur .014 disparaît quand l’utilisateur ferme
l’application ; cause matérielle non identifiée, aucun diagnostic matériel tiré des logs.

---

# 00.014.000 — trois formes de textures restantes

Build PS5 incrémental sur `build-server` (29 objets), packaging depuis le même binaire,
installation immédiate après fermeture confirmée. Pas de Cubic, commit ou push.
Seul contrôle hôte : les quatre séquences d’instructions réellement capturées
passent le lowering de production. Aucune suite desktop ni test général.

Ajouts : profondeur Array2D bindless en disposition vectorielle ; sample 2D à
LOD explicite dans une autre banque ; fetch 2D FP16 à LOD explicite avec sorties
empaquetées, registres impairs et alias d’entrée/sortie. Masques non pris en charge
encore rejetés, synchronisation intacte. Salt du traducteur incrémenté.

Installée : staging vérifié puis activation, rollback .013 conservé dans
`/data/ps5-diag/nx2-rollback-013-20261031`. Jeux et sauvegardes préservés.
L’acceptation des instructions et la compilation ne valident pas le rendu :
essai visuel PS5 en attente.

---

# 00.013.000 — corrections après revue Cubic

Compilation native incrémentale sur `build-server` (18 objets), packaging puis installation
directe après fermeture confirmée. Aucun nouveau test hôte ni suite générale.
Les quatre corrections concrètes de la revue initiale sont détaillées dans
[CUBIC-REVIEW.md](CUBIC-REVIEW.md) : import de sauvegarde non vide après filtrage,
absence de redirection d’uploads, génération unique du cache mémoire entre instances,
et préservation de la matrice couleur signalée par FFmpeg.

70 fichiers vérifiés au staging, activation réussie. Un seul rollback console est
conservé : .012 dans `/data/ps5-diag/nx2-rollback-012-20261031`. Anciennes copies
supprimées sur demande, environ 862 Mio libérés ; jeux et sauvegardes préservés.

Les performances vidéo et l’amélioration graphique partielle ont été mesurées sur
.011/.012 ci-dessous. Pas de validation graphique complète de .013 : les trois
formes restantes de textures identifiées sur .012 restent à implémenter.

---

# 00.012.000 — textures du menu / écran suivant

Compilation PS5 incrémentale sur `build-server`, puis packaging et installation directe.
Deux tests ciblés sur le lowering de production et l’IR Maxwell : **82 assertions
réussies**, bibliothèques hôte existantes réutilisées. Pas de suite desktop complète
ni de répétition des contrôles natifs généraux, selon la préférence utilisateur.

Deux refus des logs .011 reproduits avant correction : RGB bindless 2D avec
sorties séparées, comparaison de profondeur Array2D utilisant une seconde banque
de descripteurs. Registres, aliases, banque/offset et référence de profondeur
préservés ; salt du traducteur incrémenté pour les caches. Gain vidéo .011 conservé.

Installée sur PS5 après fermeture confirmée : 70 fichiers vérifiés pendant le
staging, activation par renommage avec rollback complet .011. Résultat visuel
console : amélioration partielle selon l’utilisateur, défauts encore présents.
Les deux refus précédents sont absents de la capture .012 ; de nouveaux refus
concernent l’Array2D depth bindless, le LOD explicite multi-banques et un fetch
FP16. La justesse graphique complète n’est pas validée.

---

# 00.011.000 — conversion vidéo SSE2

Compilation PS5 et contrôles natifs intégrés sur `build-server` : PASS. Paquet : inventaire,
imports, alignement, isolation PPSA99862 PASS. Packaging depuis le binaire déjà
construit. Suite desktop complète non reconstruite.

Test ciblé Clang 21 -O3 ASan/UBSan sur `build-server` : **33 554 432 pixels exactement
identiques** au calcul scalaire, soit toutes les combinaisons YUV dans chacune
des deux plages. Largeurs 0..19, chroma sans padding, queues impaires et sortie
désalignée avec sentinelles : PASS. Benchmark synthétique Linux : 223,147 ms
scalaire contre 22,962 ms SSE2 par image 4K ; ce résultat ne mesure pas la PS5.

Installée : 70 fichiers vérifiés en mode SELF brut avant publication. Fermeture
confirmée par l’utilisateur. Rollback .010 conservé à
`/data/ps5-diag/nx2-rollback-010-20261031`. Jeux, sauvegardes et réglages préservés.
Résultat comparatif PS5, mêmes 480 images (90..570) : conversion **96,176 →
21,148 ms/image** (×4,55), cadence de sortie vidéo **7,037 → 14,957 images/s**
(×2,13). Présentation pendant la vidéo ~14,2–15,6 FPS, menu 59,94 FPS.
Décodage stable ~25,6 ms/image ; aucun changement de résolution ou de synchronisation.
Image vidéo correcte selon l’utilisateur. Qualification graphique globale REFUSÉE :
flashs noirs au menu et importants défauts visuels après validation. Les logs
capturent des rejets de shaders natifs (descripteurs multi-banques, sorties RGB
bindless 2D). Correctifs ciblés en cours, cause de chaque artefact non établie.

Nettoyage demandé par l’utilisateur : staging .006 et rollbacks .006/.007/.008/.009
supprimés, 645 741 871 octets libérés. Les anciennes mentions de ces chemins dans
l’historique ci-dessous ne désignent plus des rollbacks disponibles sur console.
La .010 reste le seul rollback console conservé.

---

# 00.010.000 — mesure vidéo / Vulkan

Compilation PS5 sur `build-server` : PASS. Contrôles natifs intégrés (JIT, affinités,
synchronisation/arrêt GPU, HUD) et paquet (inventaire, imports, alignement,
isolation PPSA99862) : PASS. Suite desktop complète non reconstruite.
Packaging réalisé directement depuis le binaire construit, sans seconde compilation.

Installation : 70 fichiers vérifiés en mode SELF brut avant publication. Prototype
fermé par l’utilisateur. Rollback complet .009 :
`/data/ps5-diag/nx2-rollback-009-20261031`. Jeux, sauvegardes et réglages préservés.

Mesure console .010 confirmée par boot-trace : 480 images 4K (90..570),
conversion 96,176 ms/image, décodage 25,724 ms, swizzle 6,772 ms,
écriture 4,271 ms. Fenêtres lentes ~6,8–7,2 FPS. La conversion est le coût dominant.
Aucun gain revendiqué pour cette version de référence.
Voir `milestones/video-performance/ANALYSIS.md` pour le protocole et les limites.

---

# 00.009.000 — H.264 initialization

PS5 build on build-server and built-in native checks: PASS. Package inventory, alignment,
imports and prototype isolation: PASS. Focused video-init regression against the
prepared production header: 20 assertions PASS under ASan/UBSan. The complete
host engine suite was not rebuilt or rerun, per user request; prior .008 results
below do not constitute a full .009 test run.

Installed on 2026-10-31: 70 files hash-verified in raw SELF mode. Full .008 rollback
retained. Actual installed param.json confirms .009. No post-update game launch.
H.264 format-3 admission is fixed; full playback remains unvalidated.

---

# Eden NX2 00.008.000 — Eglantine et gather

Compilation et tests exclusivement sur `build-server`. Aucun jeu commercial exécuté par ce chat.

- Compilation PS5 et contrôles natifs réussis : chargement NSO, budgets et alias JIT,
  six cœurs, affinités, synchronisation et arrêt des threads GPU.
- Suite moteur ciblée : **395 cas / 1,877,310 assertions réussis**.
- Régression gather exécutée en premier : **3 cas / 5541 assertions réussis**.
- Mémoire : vraies méthodes Map/Unmap/WalkBlock sur backing de test, trous et remappings
  au milieu d'une suite contiguë, copies désalignées et mapping sans suivi : ASan/UBSan PASS.
- ASTC : vraie sélection et lecture des couches ; frontières, image désalignée, mips
  conservés, plages hors image et repli complet : ASan/UBSan PASS.
- Cache Vulkan : écritures portable et générée PS5 exécutées avec faux driver et vrai
  filesystem ; remplacement, erreur préservant l'ancien fichier, 12 tailles d'en-tête
  tronqué et mauvaise version : ASan/UBSan PASS.
- Métadonnées : NACP/icônes dans une arborescence d'update et version RomFS de repli
  testés dans la suite moteur. Tests RET du fork adaptés au mot haut du lien de retour.
- Paquet : identité PPSA99862, inventaire, imports, alignement et isolation PASS.
- Tests du paquet : six cœurs, historique QMD, MME graphique/compute et allocateur PS5,
  politique PAuth/RETAB, ownership/synchronisation sparse et exclusive monitor PASS.

Archive : `Eden-NX2-PS5-prototype-00.008.000.tar.gz` (43757718 octets).
SHA256 : `3367be929eed65092b2b4939d2b553f330da54a90e062365a0e89a4c01ede95b`.
Patch source final : `57866d469302426aa12ed193e12cc1bdd97bf9ae97678cbad74d69ab6d78c9c2`.
Patch du build PS5 conservé dans `build-nx2-prototype.diff` :
`e6b581622603a5158d4c49038a1556cc31e2f93a3f83414a5d8f3c6714c48351`.
Seul le fixture de test RET a été adapté après le build ; toutes les sources
de production sont identiques. Aucun rebuild PS5 nécessaire pour cette correction de test.

La suite Linux n'est pas une qualification matérielle. Aucun gain mémoire/FPS PS5
n'est mesuré ici. Le sparse sélectif reste absent et le backend sparse reste opt-in.
La génération d'images FSR3 et le contournement de dimensions des vues ne sont pas importés.
Le refus de décodage VP8 reste présent ; le correctif gather ne garantit donc pas
la disparition du PANIC Welcome Tour. Installation éventuelle suivie par l'autre chat.
