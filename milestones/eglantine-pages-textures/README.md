# Eglantine : pages et espacements de textures

Intégration ciblée du 1er novembre 2026, sur les changements PS5 en cours.

Provenance :
- [zortos293/Eglantine badc91e](https://github.com/zortos293/Eglantine/commit/badc91ebce6b6cb44eabe67f7aa0dbbc6abd9e46) : regroupement des pages partielles dans `MarkPartialWrite` et `RestorePartialPages`, mise à jour de l'ASID courant dans `UpdatePagesCachedCountNoLock`.
- [zortos293/Eglantine 11a1108](https://github.com/zortos293/Eglantine/commit/11a110898fcfe16a5b9aee98c4346265825c3178) : espacement explicite des couches (repli calculé si nul), alignement des lignes lors du swizzle, taille des bandes partielles indépendante du padding de fin, téléchargement des textures avec espacement horizontal.

Le patch NX2 existant conserve tous ses autres changements. Les trois sections
modifiées ont été comparées à leur état sauvegardé avant intégration. Les sources
de travail correspondantes dans `core/` sont synchronisées avec ces sections.
Les diagnostics PS5 du transfert partiel et les exclusions de formats restent en place.
Les budgets mémoire, le JIT et les pipelines ne sont pas modifiés.
La correction supplémentaire de sortie DMA à l’arrêt est détaillée ci-dessous.

## Tests ciblés

Exécuter exclusivement sur `build-server`, après préparation des sources :

```sh
python3 tests-nx2/check-eglantine-pages-textures.py
```

Les véritables méthodes sont extraites des sources préparées et compilées sous
ASan/UBSan avec des backends enregistreurs :

- Propriétaires A→B→A aux adresses virtuelles contiguës, incrément/décrément,
  même propriétaire, trous et adresses discontinues.
- Mille pages nouvelles en un appel, répétition sans double décrément,
  2 000 plages déterministes comparées à un oracle par page, restauration et
  frontière de page dans une image désalignée.
- Transferts complets/partiels : espacement explicite de 64 Kio, repli calculé,
  plusieurs couches et mips, alignement horizontal, bandes avec padding et
  écritures ne touchant que le padding, repli pour multisampling non pris en charge.

Les appels au décodeur sont enregistrés : ces tests valident les adresses,
les tailles et l'alignement transmis, pas les pixels produits ni le pilote PS5.
Résultat des trois groupes : PASS sur `build-server` sous ASan/UBSan.

Les états précédents, le delta propre à cette intégration et les journaux sont
conservés localement dans `artifacts/eglantine-pages-textures/` (non versionné).
Aucune installation console, aucun résultat FPS revendiqué.

Le contrôle de démarrage hérité attendait neuf workers malgré l'ajout déjà
présent de `GPUBack`. Son attente passe à dix avec une assertion explicite
sur `GPUBack` ; aucune modification du comportement de ces threads.

Le contrôle de cycle de vie GPU est également actualisé pour la garde
`!split.Active()` et le hook de chargement déjà présents. Le fixture des attentes
simule les appels de synchronisation et l'erreur du backend.

Ce contrôle a révélé une régression antérieure : la substitution CMake cherchait
l'ancienne attente DMA et ne protégeait plus la nouvelle boucle NX2 contre l'arrêt.
L'adaptation conserve cette boucle (contrôle d'erreur et traces compris), ajoute
le contrôle d'arrêt et exige désormais la présence de ses ancres de substitution.

## Résultat final

Compilation native PS5 sur `build-server` et tous les contrôles intégrés : PASS.
Le binaire récupéré est `artifacts/eglantine-pages-textures/eden-headless.elf`.
Le journal final complet est `build.log`, les tests ciblés sont consignés dans
`eglantine-pages-tests.log` et l'arrêt DMA dans `eglantine-sync-check.log`.
La version du titre est inchangée ; ce binaire n'a pas été déployé.

## Installation 00.063.000

Binaire reconstruit sur `build-server` après incrément de `contentVersion`, puis paquet
validé et publié le 1er novembre 2026, après confirmation de fermeture.
70 fichiers vérifiés avant publication. Rollback 00.062.000 complet :
`/data/ps5-diag/nx2-rollback-062-20261101-eb9d8c35`.
Archive et journal dans `artifacts/00.063.000/`. Aucune relance automatique ;
FPS et rendu restent à mesurer. Le contrôle d'isolation vérifie désormais
le verrou d'activation explicite du split déjà présent dans les sources.
