# Welcome Tour : gather PerPx et PANIC 2001-0033

## Shader

Capture PS5 00.007.000 : shader natif à 0x1f986ed200, instruction +0xc0,
mots `040a7b63 33800408 041e2f08 100fc200`, refus à 5,495 s.
Le champ 76..77 vaut 2 : PerPx, quatre décalages (x,y) signés stockés
sur huit octets, dans deux registres. Coordonnées R4/R5, offsets R8/R9,
sorties R10/R11 et R8/R9. Les sorties recouvrent les offsets.

La traduction utilise Maxwell TLD4.PTP, émet d'abord les résultats dans
R250..R253 puis les copie selon le masque dans les deux sorties. Le frontend
lit des offsets signés de 8 bits pour les programmes natifs ; le comportement
Maxwell historique à 6 bits reste inchangé. Le sel du cache natif est augmenté.
Seul le mode 2D PerPx sans comparaison de profondeur ni sortie demi-précision
est ajouté. Les autres variantes restent refusées.

Références primaires Mesa NAK, révision b1fe47e94409d81924c8663f58fac97e66ab4527 :
- [sm70_encode.rs](https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/b1fe47e94409d81924c8663f58fac97e66ab4527/src/nouveau/compiler/nak/sm70_encode.rs), OpTld4, bits76..78=PerPx.
- [nak_nir_lower_tex.c](https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/b1fe47e94409d81924c8663f58fac97e66ab4527/src/nouveau/compiler/nak_nir_lower_tex.c), packing des offsets TG4 et répartition coordonnées/src0, offsets/src1.

## PANIC

Capture : SetTerminateResult(0x4201), puis Break/PANIC à 20,416 s.
`svc_results.h` définit Kernel/33 comme ResultNotImplemented (2001-0033).
La pile remonte à main+0xaba0a0 : AbortImpl est appelé sur le résultat non nul
retourné par l'initialisation d'un décodeur vidéo. Les imports ELF dynamiques
présents dans le NSO identifient les branches InitializeH264/Av1/Vp8/Vp9Decoder.
Les 423 WebM du RomFS de mise à jour sont tous marqués V_VP8.

Dans le SDK du dump, InitializeVp8Decoder à 0x8a94ebd0 appelle le helper
0x8a94f294. À 0x8a94f320..354, celui-ci forme une requête TIPC : en-tête0xd8,
5 mots bruts, un handle copié, taille mémoire, codec4, format d'entrée et
format de sortie. À 0x8a94f3b0 le résultat IPC est récupéré puis retourné si
non nul. Ces adresses sont propres au chargement capturé (base sdk0x8a670000).

Le protocole du prototype décode ce paquet comme InitializeByTransferMemory,
commande200, codec4. Son admission accepte AV1, H.264 et un chemin VP9, jamais
VP8/codec4 ; le résultat est donc NotImplemented. Cela suggérait une lacune du décodage VP8 ; cette attribution précise est
infirmée par la trace directe de 00.008 ci-dessous. La capture Info ne contient pas
les paramètres IPC exacts de cette session : une trace d'erreur ciblée est
ajoutée pour confirmer directement la requête refusée lors du prochain essai.

Aucune réussite fictive n'est renvoyée, aucune vidéo n'est supprimée. Ajouter
le backend VP8, sa configuration, ses sorties et des tests de décodage reste
un chantier distinct. Les analyses NSO sont statiques, après décompression
bornée et contrôle SHA256 des segments ; aucun code du jeu n'est exécuté sur Mac.

## Validation et installation

Compilation PS5 sur `build-server` réussie. Tests gather : 3 cas, 5 541 assertions,
tous réussis. Suite ciblée commune : 395 cas, 1 877 310 assertions, tous réussis.
Le paquet commun 00.008.000 a été installé le 31 octobre 2026 : 70 fichiers
vérifiés par SHA256 en transfert SELF brut, ancienne version 00.007.000
conservée intégralement dans `/data/ps5-diag/nx2-rollback-007-20261031`.
Le param.json actif confirme 00.008.000. Aucun lancement du jeu n'a été effectué
après installation ; validation graphique sur console encore en attente.
Botty, les données du jeu et les sauvegardes n'ont pas été modifiés.

## Trace directe 00.008 : correction du diagnostic vidéo

Le lancement utilisateur suivant charge bien 00.008.000. La capture de 44,9 s
ne contient plus le rejet texture gather ni ExceptionRaised ; cela ne valide
pas encore la justesse du rendu, toujours noir selon l’utilisateur.
À 20,314502 s : commande 201, decoder=true, codec=0, input_format=3,
output_format=2, output_mode=1, mémoire 0x1745b000, résultat 0x4201.
SetTerminateResult et PANIC suivent à 20,317 s. Cette combinaison est rejetée
par tous les chemins d’admission actuels, avant création du backend vidéo.
Ce n’est pas la commande 200/codec4 du helper VP8 analysé auparavant.
La présence de vidéos VP8 dans le RomFS ne prouve donc pas le codec de cette
requête. Il faut établir la signification de commande201/codec0/input3 dans
le SDK/protocole avant de choisir un backend ou modifier l’admission.
Les images continuent d’être mises en file après le PANIC ; les compteurs de
présentation ne prouvent pas que le jeu progresse. Capture privée :
`backups/nx2-008-live-20261031/` du workspace ps5. Aucun changement console.
