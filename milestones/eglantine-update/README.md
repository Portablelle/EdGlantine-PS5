# Eglantine — PS5 integration 00.008.000

Examined source: Djihads80/Eglantine, `b40ad217ab829226841cb71f6e4c5cb05977a225`.
Diff from our reference `6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba`;
ASTC optimization from `97ce27ab35153884d2fd05c278433928e429cd91`.
Source patches are retained here for provenance; they must not be reapplied to
the final prototype.

## Adaptations

- End contiguous physical-page runs on map/unmap; reset counters for replaced
  pages, including untracked mappings and holes. The port's CPU backing and
  translation generations are preserved.
- Vulkan cache: reject truncated headers and write through a temporary file in
  the core. The PS5 port already generated an atomic writer; it is retained,
  waiting for the serialization worker and saving only when necessary. A failed
  save preserves the previous valid file.
- Docked/handheld notifications: NX2-specific refresh event, propagation from
  ApplySettings and detection of actual mode changes. Command 210 retains the
  fork's experimental interpretation.
- ExeFS dumps: read NACP and icons from the game directory, including
  updates/title-id/exefs; prefer the NACP version. Otherwise fall back to
  ResourceSizeTable.Product.NNN in the neighboring RomFS, a heuristic that does
  not necessarily distinguish hotfixes. Directory names are not parsed.
- ASTC: select affected layers from our dirty-page tracking, restore page counters
  exactly once, decode in Vulkan per layer and mip, and batch staging toward
  32 MiB (a single layer may exceed that budget). Eligible images >=64 MiB use
  this optimization; other paths retain full transfers. ASTC-to-BC transcoding,
  rescaled images, asynchronous decoding, unbacked images and guest sparse
  mappings are excluded. Levels retained after trimming large mips are respected.
- Release CPU upload scratch buffers over 64 MiB on the next frame and add
  upload-volume counters for future comparisons.
- Adapt the fork's RET R0/R55 tests to our explicit return-register high-word
  validation; the RET fix itself was already in our engine.

ASTC tracking uses the same `tex_partial` setting as existing partial transfers:
disabling it restores full uploads. Vulkan allocations remain resident; no
assumption that holes read as zero is introduced. The 00.006 sparse budgets are
unchanged and remain opt-in.

## Not integrated

- “FSR3” and frame generation: experimental implementation with history-management
  issues; not imported.
- Forcing a Vulkan 2D/3D view type different from what the shader expects: the
  MoltenVK workaround is insufficient to guarantee valid PS5 sampling.
- Qt/Android UI and Qt library scanning: not used by the PS5 frontend.
- Selective sparse residency and lazy GPU-region allocation: require a PS5-driver
  adaptation; not enabled by this import.
- QMD history cleanup: the previous rejection remains in effect.

The Welcome Tour gather fix and rejected-video-codec trace are coordinated in
`../gather-panic/ANALYSIS.md`. This version does not provide a VP8 decoder and is
not claimed to fix the PANIC.

## Validation

Builds and tests run exclusively on the build server, with isolated copies under
`/tmp/ps5-nx2-prototype-20261030`. Native builds use the configured dedicated-host
build image; Linux engine tests use `nx2-host-tests-build` (includes OpenSSL).
Final validation: 395 cases / 1,877,310 assertions passed; native and package
checks passed. See `../../artifacts/eglantine-update/TEST-REPORT.md`.


## Audit du fork zortos293 au 2 novembre 2026

Lecture des 30 commits les plus récents de `zortos293/Eglantine`, branche nx2.
HEAD observé : `4285e58d06c8744a884af3ab207e60f94752fa35` (intégration build 104).
Audit uniquement : aucune compilation, modification du moteur ni installation.
Comparaison avec le snapshot PS5 effectivement compilé dans
`/tmp/edglantine-game-library-20261101`, et avec les adaptations du workspace.

Sources principales :

- https://github.com/zortos293/Eglantine/commit/3140648a668aaebf87bae2dea17512fdca125ba0
- https://github.com/zortos293/Eglantine/commit/4285e58d06c8744a884af3ab207e60f94752fa35
- https://github.com/zortos293/Eglantine/commit/95e06df7a84dc274b98ccbf22885e39162ad5d92

Candidats concrets absents du snapshot console :

1. Descripteurs surface/texture séparés : `SurfaceBoundBuffer` dans l'environnement,
   `required_surface_buffer` dans le lowerer, sélection des opcodes d'images de
   stockage via `IndexedInstruction`. Le PS5 utilise encore la seule table texture.
   Priorité compatibilité/rendu ; vérifier une capture d'un shader utilisant les
   deux tables avant d'attribuer à cela le ciel noir ou les objets manquants.
   Reprendre ensemble sérialisation, valeur sentinelle ~0U et invalidation caches.
2. Flush des query reports avant DMA MME : l'amont inclut BufferCache | QueryCache
   et déclare les régions query dans MustFlushRegion. Le chemin PS5 inspecté ne
   demande que BufferCache et son MustFlushRegion ignore QueryCache. Cela peut
   fausser la décision de rendu conditionnel. Préserver les chemins natifs/split
   propres au port et tester la lecture du rapport effectivement publiée.
3. X8Z24 mixte (UNORM,UINT,UNORM,UNORM) + conversions X8_D24/ABGR8 avec scaling
   binaire exact. Format additionnel et conversions absents du snapshot.
4. CircularBufferSinkInfo::CleanUp : l'ancien code PS5 réinterprète son état en
   DeviceState et libère un faux pointeur d'upsampler ; l'amont efface l'état.
   Correction de crash audio intéressante, sans gain FPS promis ni lien établi
   avec les symptômes Bananza actuels.
5. Services/polices Switch 2, et vidéo AV1 du build 104 : à adapter aux besoins
   réellement observés, et aux bibliothèques FFmpeg PS5 disponibles.

Ne pas importer en bloc :

- Les optimisations badc91e / 11a1108 de pages partielles, propriétaire et strides
  ont déjà été adaptées (`milestones/eglantine-pages-textures/README.md`).
- Le correctif IMAD.WIDE du fork ne s'applique pas textuellement : notre lowerer
  possède déjà sa propre séquence de produit haut, addend, retenue et paire de
  destinations. Comparer les sémantiques/tests, pas les seuls messages de commit.
- Le chemin experimental tensor dépend de VK_NV_cooperative_matrix et d'une
  forme/subgroup validée. Le RADV épinglé PS5 limite déjà son cooperative-matrix
  de base à gfx_level >= GFX11 ; ce n'est pas une accélération utilisable telle
  quelle pour le GPU PS5. Conserver la désactivation/sélection par capacités.
- Les correctifs AVX-512 ne concernent pas le CPU PS5 Zen 2, et les changements
  Qt/macOS/Windows/updater desktop ne corrigent pas notre lanceur natif.
- Les sparse images du build 104 changent beaucoup de gestion mémoire ; le fork
  lui-même exclut RADV par défaut dans CanUseUnbackedSparseImages. Ne pas activer
  aveuglément ce chemin à la place du backend PS5 optionnel existant.

Ces commits ne démontrent ni un gain FPS sur PS5 ni une résolution de la phase
`dump.romfs.begin` où s'est arrêté le dernier essai Bananza. L'essai actuel reste
à refaire après la fin du transfert Mario Kart. Les travaux mémoire/readback
préparés dans l'autre chat restent un lot séparé, non déployé dans ce snapshot.


## Intégration des quatre correctifs sélectionnés

À la demande du joueur, adaptation du commit zortos293
`3140648a668aaebf87bae2dea17512fdca125ba0` dans le patch autonome
`eden/tools/eden-patches/92-nx2-surface-query-depth-audio.diff`.
Le patch s'applique sur le snapshot 90 actuellement testé ; la compatibilité
avec le lot 91 préparé dans l'autre chat a aussi été vérifiée par application à
blanc, sans intégrer ce lot au binaire console ciblé.

1. Tables surface/texture séparées de bout en bout : interface d'environnement,
   table native requise par SULD/SUST, classification `IndexedInstruction` des
   reads/writes/atomiques, état sérialisé et désérialisé. La sentinelle ~0U conserve
   le repli vers la table texture. Le fallback bindless déjà présent dans notre
   SUST est conservé lorsqu'un second buffer de surfaces est employé ; les
   correctifs Bananza et Pokopia restent dans l'adapter de lowering existant.
2. Cohérence des rapports d'occlusion : les deux chemins DMA natifs (macro et
   frontend Maxwell3D) demandent BufferCache | QueryCache ; MustFlushRegion
   rapporte les pages de query même à faible précision GPU, avant son retour
   anticipé. FlushRegion utilise déjà le cache de queries du port.
3. X8Z24 mixte reconnu comme profondeur ; conversion X8_D24/ABGR8 dans les deux
   sens, normalisation binaire exacte conservant les 24 bits. Les alias couleur
   de quatre octets passent par une vue UNORM de bytes ; les conversions sont
   divisées par couche en conservant les offsets et les niveaux mip.
4. CleanUp du circular buffer audio efface son propre état et ses paramètres,
   sans réinterpréter l'état en DeviceState ni libérer un faux upsampler.

Format cache Vulkan : 40/41 au lieu de 38/39 (puis tags par jeu inchangés) ;
OpenGL : 18 au lieu de 17. Nécessaire parce que les environnements sérialisés ont
un champ supplémentaire ; pas de suppression manuelle de tout le cache driver.

Tests ciblés sur dedie : `eden/tests-nx2/check-four-fixes.py`, ASan/UBSan.
Classification des vrais opcodes bound/bindless, lowering natif avec tables 2/3
indépendantes dans les deux ordres, cas surface seule, rapports query seuls lus
après flush sur les deux chemins à basse précision, 16 777 216 valeurs D24
aller-retour et normalisation correctement arrondie, vues alias et copies par
couche/mip, nettoyage audio répété avec état arbitraire : PASS. Les deux shaders
GLSL réels compilent et passent spirv-val. Vérification de la paire de champs
sérialisés et des deux générations de cache : PASS. Ces tests ne valident pas
les pixels produits par le GPU PS5 ni le démarrage effectif de Bananza.

Build dédié isolé : `/tmp/edglantine-game-library-20261101`,
`four-fixes-build.log`, `four-fixes-test.log`.
Artefacts locaux : `artifacts/00.065.000-four-fixes/`.
Compilation native et packaging réussis sur dedie ; binaire installé sur PPSA99862
par remplacement vérifié avec backup du précédent. Journal :
`artifacts/00.065.000-four-fixes/install-journal.json`.
Aucun succès de rendu ou gain FPS console encore établi pour ce lot.


Les ajustements de revue pré-push (parseur NPDM canonique et réservation RAII du
cache VFS via le patch 93) sont une évolution source ultérieure au déploiement
du lot quatre-correctifs ; voir le journal Bananza. Ils ne modifient pas la
sémantique des quatre correctifs graphiques/audio.

### Final source ownership review

The cumulative candidate includes core patches 90–97. The native half predicates, verified barrier cancellation, FSEL option and full generic-attribute bounds live in core patch 95, with only PS5 title/cache policy in the platform adapter. Patch 93 owns bounded VFS allocation and direct-read fallback in ordinary core builds as well as the frontend. Patch 94 gives capture state renderer lifetime and accounts for requested skipped draws in its bounded observation window. Patch 96 owns optional startup trace hooks in core. Loose-dump metadata also retains supported language flags; the non-Vulkan native configuration does not invoke Vulkan-only adapters. These structural checks do not establish an improvement in hardware rendering.

Patch 97 owns unaligned GPU-written uniform readback in the canonical buffer cache. Descriptor-table metrics are independent of VFS types. Each captured draw retains its own bounded TIC/TSC snapshot, including in-place updates and table-limit changes.
