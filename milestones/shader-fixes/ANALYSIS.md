# Analysis of eleven shader failures — NX2 prototype

Scope: separate PPSA99862 prototype, Eden-NS2 sources pinned to
`e2f285ab1ecd3a2475c2ccad66f23b06b94ead5c`. Builds and tests run on the build server.

## Eight control-flow cases

Six barrier-cancellation tests failed: leaving an inner scope, cancelling two
barriers, preserving parents, two separate cleanup paths and inner cancellation
at a parent reconvergence point. The BREAK shortcut accepted cancellation as soon
as an enclosing SYNC scope existed, before proving the exit path. It therefore
accepted variants that changed the predicate or returned to a cancelled scope.
For two consecutive BREAKs, it ignored the first without recording the validated
chain; the second then encountered the wrong inner token and was rejected.

Removing this shortcut lets the existing linear-path or control-path proofs run,
then mark the validated cancellations together. Tests still follow both branches
of the Maxwell CFG and check reconvergence, cleanup, termination and paths that
must not be visited. Negative variants are retained.

The CALL.REL.NOINC shortcut that skips a backward branch also bypassed proof of
active-scope cleanup. It is now restricted to loops without a scope or the already
explicit case of immediate reconvergence. Inside a scope, the existing cleanup
check excludes backward jumps, scope exits and unproven cleanup forms.

Finally, WARPSYNC after BSYNC could become a NOP when the BSSY target did not match
that reconvergence point. This inconsistency is rejected. The valid path retains
its memory barrier; all three tested tokens remain covered.

These fixes make translation more conservative for paths whose validity has not
been proved. They do not, by themselves, establish the semantics of all Ampere
control-flow forms or full-game compatibility.

## Three outdated negative expectations

- Vector AST from RZ: the translator already scalarizes components to avoid
  register-number overflow. The test now checks two, three and four consecutive
  attributes and their RZ reads in the IR.
- Zero-LOD cube-array TEX: the general TEX path already emits an explicit zero-LOD
  sample. The test checks cube-array type, descriptor, LOD, all four coordinates
  and RGBA copies to separate destinations. The other negative variant, an
  unaligned source register, is retained.
- RED.E.MIN U32: the changed bit selected MIN, which was already translated,
  rather than an invalid instruction. The test now executes MIN and MAX for
  25 value pairs each, including signed/unsigned boundaries, checking the 64-bit
  pointer, neighboring memory and every register/predicate. Odd pointers and
  invalid mode bits remain rejected.

None of the eleven cases is filtered out, and no test is marked as an expected
failure. Final results and validation limits are in `TEST-REPORT.md` at the
prototype root.
