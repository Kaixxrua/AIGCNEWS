# Deferred Web stage diagnostics — review candidate

Ready for main-agent review; **not applied to the SDK and no engine build run**.
Only `ShaderGLES3::_compile_specialization` changes: 37 inserted lines, zero
deleted lines. Shader source generation, attachment order, transform feedback,
link call/check, uniforms, `spec.ok`, and the existing link-error cleanup remain.
The earlier lazy-variant patch and everything outside this function are exact.

## Pinned input and output

Godot 4.7.2 `ed1daf0bf001b61586d9930840f2f1394092c079`, with the previously
reviewed Web lazy-variant change already present. Target:
`drivers/gles3/shader_gles3.cpp`.

Machine-readable pins are in
[deferred-web-validation-v135.json](/E:/Projects/Godot-Octopath2/godot/engine-patches/deferred-web-validation-v135.json):

- Before: `bef3d081a1e8ef8769f11148821edea70ca0830fc29bab7660a252862c97c9d8`
- After: `b73d6aa83d5c235693fe64504eca5eb943964d8ac2350e65627bdc7301af6ab9`
- Patch: `8c332fee68cadb9fbc8aedd47d7f774c9383c3131453d38029d737ec83df7f0d`

Check the before hash, apply the single-file patch without fuzz, then check the
after hash before main's one incremental build. Reversing this patch restores
the complete before file exactly. Do not apply to an unknown source version.
No build command, cap, BUILD_NAME, SDK, release, PCK or host configuration is
changed by these files. Main owns the existing reflection-depth build recipe.

## Why this is validation deferral, not a fabricated success

Under `WEB_ENABLED`, submit vertex and fragment compilation before making the
existing synchronous `glGetProgramiv(..., GL_LINK_STATUS, ...)` call. Initialize
the Web local status to false so a query that does not write cannot imply
success. There is no substitution of a GL result, async completion assertion,
program/status cache, or readiness signal.

The OpenGL ES 3.0.6 specification, section 2.12.3, printed page 49, defines
successful linking as creation of a valid executable and lists unsuccessfully
compiled attached shaders as a link-failure condition. Both shader objects are
attached to this newly created program; no prior successful executable exists.
Thus the real successful link is sufficient to reject stage compilation
failures here. This does **not** mean a rendered frame has been presented.
[Khronos specification, PDF page 62](https://registry.khronos.org/OpenGL/specs/es/3.0/es_spec_3.0.pdf#page=62).
The supplied XHTML reference was not readable by the document fetcher because
of its content type; the linked official PDF was read instead.

On a failed link, query BOTH real stage compile statuses. For each failed stage,
read its actual log and rebuild its diagnostic source using the same version,
variant and specialization arguments. Rebuilding happens only on failure; the
successful path does not retain both large source strings for later diagnostics.
Never return early from a stage diagnostic: proceed to the original program log
and cleanup, including for unavailable/zero-length stage logs.

| Link outcome / stage state | Observable result |
|---|---|
| Success | No stage status queries; real link check, unchanged uniform setup, then `spec.ok=true` |
| Vertex failure | Vertex status/log/source plus program failure; both shader IDs and program deleted |
| Fragment failure | Fragment status/log/source plus program failure; same cleanup |
| Both stages fail | Both stage diagnostics plus program failure; same cleanup |
| Link fails, both stages compiled | Both statuses checked; program error retained, no invented compile error |

Every Web failure retains `spec.ok=false`, sets `spec.id=0`, returns before
uniform setup, and deletes both stages/program exactly once through the
original link-error branch. The zero-log 4096-byte fallback is retained; a
negative stage log length still reports its stage and does not skip cleanup.
For non-Web, selecting the preprocessor branch yields the **byte-identical
original function**, including its original immediate stage checks/error paths.

## Bounded evidence

[Test file](/E:/Projects/Godot-Octopath2/godot/engine-patches/test_deferred_web_validation_v135.py):

```powershell
& E:/Anaconda3/python.exe -B E:/Projects/Godot-Octopath2/godot/engine-patches/test_deferred_web_validation_v135.py
```

Run before SDK application: the test deliberately requires the unchanged
before-SHA. It applies the patch only in memory, checks the reverse operation,
rejects foreign context/extra-file patches, verifies all three machine pins,
and checks unchanged non-Web source and the real link/success/cleanup tail.

**7/7 tests passed.** A small standalone MinGW C++ fixture compiles and executes
the actual extracted patched function, not a rewritten algorithm. GL, Godot
utility types and logging are mocks. Nine Web cases cover success, vertex-only,
fragment-only, both-stage, link-only, zero logs, negative stage log length,
negative program log length, and an unwritten link result. Eight non-Web cases
have byte-identical complete call/log output versus the actual original
function. Diagnostic allocation/free balance and stage source identity are
checked. No engine translation unit, Godot scene or real GPU is built/run.

[Evidence](/E:/Projects/Godot-Octopath2/artifacts/startup-v135/independent/deferred-web-validation-x7f1_si2/evidence.json),
[Web call/error traces](/E:/Projects/Godot-Octopath2/artifacts/startup-v135/independent/deferred-web-validation-x7f1_si2/web-run.log).
The SDK source was rehashed after the tests and remains the before-SHA.

## Performance and acceptance boundary

Actual v144 trace: 94 shader-status calls total 836.5 ms; 94 program-status calls
total 1722.8 ms. These are instrumented synchronous waits, not a promise of
836.5 ms recoverable CPU time. Work can move into the remaining link wait;
queue/driver scheduling and compilation overlap determine any net benefit.

Main's controlled engine-only A/B must keep PCK/host/render settings fixed,
record total navigation-to-live-core and GL wait totals, and separate HTTP
cache bypass from shader/driver cache state. Require real complete QHD day,
night, return-day and animation/water rendering, with no new shader/link errors.
Neither smaller query counts nor two RAFs establish physical presentation or
the <=10-second target. All real-GPU/build/performance acceptance is pending.
