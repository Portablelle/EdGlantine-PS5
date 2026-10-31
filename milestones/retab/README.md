# RETAB — 00.007.000

La première exécution PS5 de Welcome Tour avec 00.006.000 charge les huit NSO,
initialise Vulkan puis déclenche `UnallocatedEncoding` sur `D65F0FFF` (RETAB)
à PC `0x802f50c0`, dans rtld. Les erreurs de pile non mappée surviennent ensuite.
Ce constat ne démontre pas une absence de firmware ni une corruption du dump.

Le cœur et son wrapper activent déjà `enable_pauth_returns` à partir du NPDM
étendu. Cependant, `headless/dynarmic/jit_impl.inc` remplace l'implémentation
amont et ne transmettait que les deux premières options de traduction. PAuth
restait donc désactivé et la largeur d'adresse restait à 64 bits. Les chemins
GetBlock et EdenPrecompile transmettent maintenant explicitement l'option du
processus et sa largeur d'adresse. Le modèle de compilation par lots conserve
les mêmes options. Aucune activation globale pour les processus hérités.

Les tests du cœur PAuth sont désormais reliés au JIT réellement généré par le
port dans la suite hôte. Le test du port couvre Run avec RET/RETAA/RETAB et
PACIASP/PACIBSP, puis la précompilation et l'exécution sur un autre membre du
groupe partagé. Les variantes désactivées doivent toujours refuser RETAA/RETAB.
Le contrôle natif vérifie aussi les options dans les sources générées utilisées
par le binaire PS5.

Validation sur build-server : avant correction, 6 cas échouent (95 assertions en échec).
Après correction, 7 cas / 904 assertions passent, dont les nouveaux chemins Run
et précompilation. Suite moteur ciblée : 387 cas / 1 871 750 assertions passent.
Les tests exécutent du code ARM synthétique ; aucun dump commercial n'est lancé
sur le Mac ou le dédié. Cette validation ne prouve pas que le jeu atteint son menu.

Essai PS5 00.007.000 : le précédent blocage RETAB est franchi, sans nouvelle
ExceptionRaised dans la capture. Chargement NRO et présentation active. Le jeu
reste noir : shader refusé à 5,495 s (texture gather, champ 76..80 à 2), puis
panic 0x4201 à 20,416 s. Le lien causal entre ces événements reste à établir.
Les FPS de présentation ne prouvent pas la validité du rendu du jeu.
