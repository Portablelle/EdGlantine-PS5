# Prochaines étapes du prototype NX2 PS5

## Résidence sparse des textures par couche — audit dédié réalisé

Piste conservée pour un travail ultérieur.
Aucun déploiement ni accès console n'est autorisé par cette note.

Premier jalon réalisé : `experiments/sparse-textures/README.md`. Le pilote possède
les bindings et annonce la résidence 2D, mais ne garantit pas les lectures à zéro
des trous. Tests des routines RADV sous ASan/UBSan et bibliothèque de diagnostic
cross-compilée PS5 réussis sur le dédié. Aucun chemin de résidence par couche
n'est activé par défaut.

Deuxième jalon : 00.006.000 intègre le gestionnaire de couches, les budgets, la
synchronisation et la quarantaine sur erreur. Il lie toutes les couches visibles
avant publication. Voir `milestones/sparse-layers/README.md`. La priorité restante
est la preuve des accès aux couches pour rendre possible une résidence sélective,
puis des dépendances GPU plus fines ; aucun gain mémoire sélectif n'est encore revendiqué.

Référence : [Eglantine](https://github.com/Djihads80/Eglantine), révision
`6f5e137ec4eb83bbff9ea15f1ad1a8407cfc0cba`, notamment les commits `6380b66`,
`97ce27a`, `940d44c` et `d4ee7fc`.

En 00.008, les uploads/décodages ASTC des couches modifiées sont intégrés sans
résidence sélective ; voir `milestones/eglantine-update/README.md`.

Objectif : éviter de réserver et de retransférer toutes les couches de grandes
textures peu utilisées. Allouer les blocs GPU et les couches d'image à la demande,
et ne redécoder que les couches ASTC modifiées. Gains PS5 non mesurés.

Travail possible sur le dédié, sans console :

1. Examiner le pilote RADV et la couche Vulkan épinglés dans le port : exposition
   de sparseBinding, sparseResidencyImage2D, propriétés de résidence, formats
   et queues compatibles avec vkQueueBindSparse.
2. Comparer les chemins de mémoire GPU d'Eglantine à ceux d'Eden-NS2 déjà importés.
   Définir un seul propriétaire pour le suivi des blocs, couches et pages modifiées.
3. Prototyper derrière une option désactivée par défaut, avec détection des
   capacités et repli vers les images ordinaires lorsque le format ou le pilote
   ne permet pas cette résidence. Adapter les plafonds au pool partagé PS5.
4. Tester les calculs de couches/mips, les blocs non engagés, les écritures et
   remappages, les barrières, les échecs d'allocation et la libération après usage
   GPU. Vérifier aussi les rendus vers ces images, pas uniquement leur lecture.
5. Compiler et empaqueter une variante distincte sur le dédié ; conserver le
   prototype validé pour comparaison et retour arrière.

Validation matérielle ultérieure, seulement dans une tâche qui l'autorise :
confirmer les capacités réellement exposées par le pilote, puis comparer mémoire
engagée, volumes transférés, temps de trame, rendu et stabilité sur la même scène.
Une compilation ou les mesures PC d'Eglantine ne suffisent pas à activer ce chemin
par défaut sur PS5. Botty et son moteur Switch 1 restent hors du périmètre.

## Tests shaders Eden-NS2 — corrigés en 00.005.000

Les onze cas ont été réconciliés : huit corrections de validation du contrôle de
flux et trois attentes obsolètes remplacées par des vérifications sémantiques.
La suite ciblée passe : 380 cas et 1 870 846 assertions. Voir `TEST-REPORT.md` et
`milestones/shader-fixes/ANALYSIS.md`. La qualification graphique en jeu sur PS5
reste à effectuer dans une tâche autorisant explicitement la console.
