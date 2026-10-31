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
