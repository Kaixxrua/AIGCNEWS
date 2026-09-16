"""Pinned patch/scope checks and the ACTUAL function in a tiny mocked-GL C++ TU.

No SDK edits, engine build, browser, real GL, scene, or performance benchmark.
Generated standalone test files stay in a fresh independent artifact directory.
"""
from pathlib import Path
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".tools/godot-web-v126/src/drivers/gles3/shader_gles3.cpp"
PATCH = Path(__file__).with_name("deferred-web-validation-v135.patch")
BEFORE_SHA = "bef3d081a1e8ef8769f11148821edea70ca0830fc29bab7660a252862c97c9d8"
TARGET = "drivers/gles3/shader_gles3.cpp"
BEGIN = "void ShaderGLES3::_compile_specialization("
END = "\nRenderingServerTypes::ShaderNativeSourceCode ShaderGLES3::version_get_native_source_code("

DEFERRED_DIAGNOSTICS = '''#ifdef WEB_ENABLED
		// A failed link can include either/both failed stages. Diagnose both
		// before the unchanged program-log and cleanup path below.
		const GLuint shader_ids[] = { spec.vert_id, spec.frag_id };
		const StageType shader_stages[] = { STAGE_TYPE_VERTEX, STAGE_TYPE_FRAGMENT };
		const char *shader_stage_names[] = { "Vertex", "Fragment" };
		for (int i = 0; i < 2; i++) {
			GLint compile_status = GL_FALSE;
			glGetShaderiv(shader_ids[i], GL_COMPILE_STATUS, &compile_status);
			if (compile_status != GL_FALSE) {
				continue;
			}
			GLsizei stage_log_length = 0;
			glGetShaderiv(shader_ids[i], GL_INFO_LOG_LENGTH, &stage_log_length);
			if (stage_log_length < 0) {
				ERR_PRINT(name + ": No OpenGL " + shader_stage_names[i] + " shader compiler log.");
				continue; // Still diagnose the other stage, then clean up both.
			}
			if (stage_log_length == 0) {
				stage_log_length = 4096; // Preserve the existing buggy-driver fallback.
			}
			char *stage_log = (char *)Memory::alloc_static_zeroed(stage_log_length + 1);
			glGetShaderInfoLog(shader_ids[i], stage_log_length, &stage_log_length, stage_log);
			StringBuilder builder;
			_build_variant_code(builder, p_variant, p_version, shader_stages[i], p_specialization);
			_display_error_with_code(name + ": " + shader_stage_names[i] + " shader compilation failed:\\n" + stage_log, builder.as_string());
			Memory::free_static(stage_log);
		}
#endif
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def function(source):
    start, end = source.index(BEGIN), source.index(END)
    return source[start:end]


def expected_candidate(source):
    old = function(source)
    new = old.replace("\tGLint status;\n", "\tGLint status;\n#ifdef WEB_ENABLED\n"
                      "\t// Successful real LINK_STATUS validates both attached compiled stages.\n"
                      "\tstatus = GL_FALSE;\n#endif\n", 1)
    for stage in ("vert", "frag"):
        start = new.index(f"\t\tglGetShaderiv(spec.{stage}_id, GL_COMPILE_STATUS, &status);")
        end = new.index("\n\t\t}\n\t}\n", start) + len("\n\t\t}\n")
        new = new[:start] + "#ifndef WEB_ENABLED\n" + new[start:end] + "#endif\n" + new[end:]
    anchor = "\tglGetProgramiv(spec.id, GL_LINK_STATUS, &status);\n\tif (status == GL_FALSE) {\n"
    if new.count(anchor) != 1:
        raise ValueError("Unique real link-status failure gate required")
    new = new.replace(anchor, anchor + DEFERRED_DIAGNOSTICS, 1)
    return source.replace(old, new, 1)


def apply_exact_patch(source, patch):
    """Single-file unified patch, exact positions/context; no fuzz or filesystem writes."""
    lines = patch.splitlines(True)
    if lines[:2] != [f"--- a/{TARGET}\n", f"+++ b/{TARGET}\n"]:
        raise ValueError("Patch must touch only the pinned shader file")
    original, output, consumed, i = source.splitlines(True), [], 0, 2
    while i < len(lines):
        header = re.fullmatch(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@\n", lines[i])
        if not header:
            raise ValueError("Unsupported/extra patch section")
        old_line, old_count, new_line, new_count = map(int, header.groups())
        if old_line - 1 < consumed:
            raise ValueError("Overlapping patch hunks")
        output.extend(original[consumed:old_line - 1])
        if len(output) != new_line - 1:
            raise ValueError("Incorrect output hunk position")
        i += 1
        before, after = [], []
        while i < len(lines) and not lines[i].startswith("@@ "):
            line = lines[i]
            if not line or line[0] not in " +-":
                raise ValueError("Malformed patch body")
            if line[0] in " -": before.append(line[1:])
            if line[0] in " +": after.append(line[1:])
            i += 1
        if len(before) != old_count or len(after) != new_count:
            raise ValueError("Incorrect patch hunk lengths")
        if original[old_line - 1:old_line - 1 + old_count] != before:
            raise ValueError("Patch context differs from pinned source")
        output.extend(after)
        consumed = old_line - 1 + old_count
    output.extend(original[consumed:])
    return "".join(output)


def select_web(source, web):
    active, stack, result = True, [], []
    for line in source.splitlines(True):
        directive = line.strip()
        if directive in ("#ifdef WEB_ENABLED", "#ifndef WEB_ENABLED"):
            stack.append(active)
            active = active and (web if directive.startswith("#ifdef") else not web)
        elif directive == "#endif":
            active = stack.pop()
        elif directive.startswith("#"):
            raise ValueError("Unexpected preprocessor scope in audited function")
        elif active:
            result.append(line)
    if stack:
        raise ValueError("Unbalanced Web guards")
    return "".join(result)


# Only mocks are handwritten. The function under test below is inserted directly
# from the exact applied patch (and separately from the original for comparison).
CPP_PREFIX = r'''
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using GLuint = unsigned int; using GLint = int; using GLsizei = int;
enum { GL_FALSE=0, GL_TRUE=1, GL_VERTEX_SHADER=2, GL_FRAGMENT_SHADER=3,
       GL_COMPILE_STATUS=4, GL_INFO_LOG_LENGTH=5, GL_LINK_STATUS=6, GL_INTERLEAVED_ATTRIBS=7 };
struct CharString { std::string s; const char *ptr() const { return s.c_str(); } int length() const { return int(s.size()); } };
struct String : std::string { using std::string::string; String() {} String(const std::string &s):std::string(s) {}
    CharString utf8() const { return { *this }; } };
struct StringBuilder { String code; String as_string() const { return code; } };
template<class T> struct Vector : std::vector<T> { const T *ptr() const { return this->data(); } };
struct State {
    bool vs=true, fs=true, link=true, write_link=true;
    int stage_log=64, program_log=64, allocations=0, uniforms=0, link_queries=0;
    bool linked=false; int compile_queries[2]={0,0};
    std::vector<std::string> calls, errors, error_codes, submitted;
    std::vector<GLuint> deleted_shaders, deleted_programs;
} g;
static void check(bool b, const char *s) { if (!b) throw std::runtime_error(s); }
static std::string stage(GLuint id) { return id==201 ? "VS" : "FS"; }
static bool stage_ok(GLuint id) { return id==201 ? g.vs : g.fs; }
static int position(const std::string &s) { auto p=std::find(g.calls.begin(),g.calls.end(),s); return p==g.calls.end() ? -1 : int(p-g.calls.begin()); }
struct Memory {
    static void *alloc_static(size_t n) { ++g.allocations; return std::malloc(n); }
    static void *alloc_static_zeroed(size_t n) { ++g.allocations; return std::calloc(n,1); }
    static void free_static(void *p) { --g.allocations; std::free(p); }
};
static void emit(const String &s) { g.errors.push_back(s); }
static void _display_error_with_code(const String &s,const String &code) { emit(s); g.error_codes.push_back(code); }
#define ERR_PRINT(s) emit(s)
#define ERR_FAIL() do { g.calls.push_back("FAIL_RETURN"); return; } while (0)
static GLuint glCreateProgram() { g.calls.push_back("createProgram"); return 100; }
static GLuint glCreateShader(int type) { GLuint id=type==GL_VERTEX_SHADER ? 201 : 202; g.calls.push_back("create"+stage(id)); return id; }
static void glShaderSource(GLuint id,int n,const char **s,GLint *len) {
    check(n==1,"source count"); g.calls.push_back("source"+stage(id)); g.submitted.emplace_back(*s,*len);
}
static void glCompileShader(GLuint id) { g.calls.push_back("compile"+stage(id)); }
static void glGetShaderiv(GLuint id,int parameter,GLint *out) {
    if(parameter==GL_COMPILE_STATUS) { g.calls.push_back("status"+stage(id)); ++g.compile_queries[id==201?0:1]; *out=stage_ok(id)?GL_TRUE:GL_FALSE; }
    else { check(parameter==GL_INFO_LOG_LENGTH,"shader parameter"); g.calls.push_back("length"+stage(id)); *out=g.stage_log; }
}
static void copy_log(const std::string &s,GLsizei size,GLsizei *len,char *out) {
    check(size>0,"log size"); *len=std::min(int(s.size()),size-1); std::memcpy(out,s.data(),*len); out[*len]=0;
}
static void glGetShaderInfoLog(GLuint id,GLsizei size,GLsizei *len,char *out) {
    g.calls.push_back("log"+stage(id)); copy_log(stage(id)+" compiler log",size,len,out);
}
static void glAttachShader(GLuint program,GLuint id) { check(program==100,"attach program"); g.calls.push_back("attach"+stage(id)); }
static void glTransformFeedbackVaryings(GLuint program,int count,const char *const *names,int mode) {
    check(program==100 && count==1 && std::string(names[0])=="varying" && mode==GL_INTERLEAVED_ATTRIBS,"feedback unchanged"); g.calls.push_back("feedback");
}
static void glLinkProgram(GLuint id) { check(id==100,"link program"); g.calls.push_back("link"); g.linked=true; }
static void glGetProgramiv(GLuint id,int parameter,GLint *out) {
    check(id==100,"program query id");
    if(parameter==GL_LINK_STATUS) {
        check(g.linked,"real link first"); g.calls.push_back("linkStatus"); ++g.link_queries;
        if(g.write_link) *out=(g.link && g.vs && g.fs)?GL_TRUE:GL_FALSE;
    } else { check(parameter==GL_INFO_LOG_LENGTH,"program parameter"); g.calls.push_back("programLogLength"); *out=g.program_log; }
}
static void glGetProgramInfoLog(GLuint,GLsizei size,GLsizei *len,char *out) { g.calls.push_back("programLog"); copy_log("program linker log",size,len,out); }
static void glDeleteShader(GLuint id) { g.deleted_shaders.push_back(id); g.calls.push_back("delete"+stage(id)); }
static void glDeleteProgram(GLuint id) { g.deleted_programs.push_back(id); g.calls.push_back("deleteProgram"); }
class ShaderGLES3 {
public:
    enum StageType { STAGE_TYPE_VERTEX, STAGE_TYPE_FRAGMENT };
    struct Version { struct Specialization { GLuint id=0,vert_id=0,frag_id=0; bool ok=false; }; };
    struct Feedback { const char *name; uint64_t specialization; };
    String name="FixtureShader"; int feedback_count=1; Feedback feedbacks[1]={{"varying",0}};
    void _build_variant_code(StringBuilder &b,uint32_t variant,Version *,StageType type,uint64_t spec) {
        check(variant==7 && spec==171,"same variant and full specialization"); b.code=type==STAGE_TYPE_VERTEX ? "VERTEX SOURCE 7/171" : "FRAGMENT SOURCE 7/171";
    }
    void _get_uniform_locations(Version::Specialization &,Version *) {
        check(g.link_queries==1 && g.link && g.vs && g.fs && g.write_link,"uniform setup requires real successful link");
        ++g.uniforms; g.calls.push_back("uniforms");
    }
    void _compile_specialization(Version::Specialization &,uint32_t,Version *,uint64_t);
};
'''

CPP_SUFFIX = r'''
static bool contains(const std::string &s) { for(auto &v:g.errors) if(v.find(s)!=std::string::npos) return true; return false; }
static void run(const char *label,bool vs,bool fs,bool link,int slog=64,int plog=64,bool write=true) {
    g=State(); g.vs=vs;g.fs=fs;g.link=link;g.stage_log=slog;g.program_log=plog;g.write_link=write;
    ShaderGLES3 shader; ShaderGLES3::Version version; ShaderGLES3::Version::Specialization spec;
    shader._compile_specialization(spec,7,&version,171);
    bool success=vs && fs && link && write;
    check(spec.ok==success,"spec.ok must match actual result");
    check(g.allocations==0,"all diagnostic buffers freed");
    if(success) {
        check(spec.id==100 && g.uniforms==1 && g.deleted_programs.empty() && g.deleted_shaders.empty(),"success lifetime");
        check(g.errors.empty() && g.link_queries==1,"success real link/no errors");
    } else { check(!spec.ok && spec.id==0 && !g.uniforms && !g.errors.empty(),"failure closed and observable"); }
#ifdef WEB_ENABLED
    check(position("compileVS")>=0 && position("compileFS")>position("compileVS"),"both stages queued");
    check(position("link")>position("compileFS") && position("linkStatus")>position("link"),"real link synchronization");
    check(position("feedback")>position("attachVS") && position("feedback")<position("link"),"feedback before link");
    if(success) {
        check(g.compile_queries[0]==0 && g.compile_queries[1]==0,"no successful per-stage sync queries");
        check(position("programLogLength")==-1,"no success log queries");
    } else {
        check(g.compile_queries[0]==1 && g.compile_queries[1]==1,"both real stage statuses on link failure");
        check(position("statusVS")>position("linkStatus") && position("statusFS")>position("linkStatus"),"deferred diagnostics");
        check(g.deleted_shaders==std::vector<GLuint>({202,201}) && g.deleted_programs==std::vector<GLuint>({100}),"both stages/program freed exactly once");
        check(contains(plog<0 ? "No OpenGL program link log" : "Program linking failed"),"link failure visible even after stage errors");
        for(int i=0;i<2;i++) {
            bool ok=i==0?vs:fs; std::string title=i==0?"Vertex":"Fragment";
            if(!ok) {
                check(contains(slog<0 ? "No OpenGL "+title : title+" shader compilation failed"),"failed stage identifiable");
                if(slog>=0) {
                    std::string code=i==0?"VERTEX SOURCE 7/171":"FRAGMENT SOURCE 7/171";
                    check(std::find(g.error_codes.begin(),g.error_codes.end(),code)!=g.error_codes.end(),"correct stage source logged");
                    check(contains(i==0?"VS compiler log":"FS compiler log"),"real stage log retained");
                }
            }
        }
        if(vs && fs) check(position("logVS")==-1 && position("logFS")==-1,"link-only error not mislabeled compile error");
    }
#else
    check(position("statusVS")>position("compileVS"),"native immediate vertex validation");
    if(vs) check(position("statusFS")>position("compileFS"),"native immediate fragment validation");
    else check(position("compileFS")==-1,"native early vertex failure unchanged");
#endif
    std::cout<<label<<" PASS "; for(auto &s:g.calls) std::cout<<s<<","; for(auto &s:g.errors) std::cout<<s<<";"; std::cout<<"\n";
}
int main() {
    try {
        run("success",true,true,true);
        run("vertex-failure",false,true,true);
        run("fragment-failure",true,false,true);
        run("both-stage-failure",false,false,true);
        run("link-only-failure",true,true,false);
        run("zero-stage-and-link-log",false,false,true,0,0);
        run("negative-stage-log",false,false,true,-1,64);
        run("negative-program-log",false,true,true,64,-1);
#ifdef WEB_ENABLED
        run("unwritten-link-status-fails-closed",true,true,true,64,64,false);
#endif
    } catch(const std::exception &e) { std::cerr<<e.what()<<"\n"; return 1; }
    return 0;
}
'''


class DeferredValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = SOURCE.read_bytes()
        if sha(cls.raw) != BEFORE_SHA:
            raise ValueError("Pinned source changed: audit requires the unapplied reviewed source")
        cls.original = cls.raw.decode()
        cls.candidate = apply_exact_patch(cls.original, PATCH.read_text(encoding="utf-8"))

    def test_patch_is_exact_recipe_and_one_function_only(self):
        self.assertEqual(self.candidate, expected_candidate(self.original))
        self.assertEqual(self.candidate.replace(function(self.candidate), function(self.original), 1), self.original)
        self.assertEqual(sha(SOURCE.read_bytes()), BEFORE_SHA)

    def test_non_web_preprocessed_function_is_byte_exact_original(self):
        self.assertEqual(select_web(function(self.candidate), False), function(self.original))

    def test_reverse_patch_restores_the_full_pinned_file(self):
        reverse = "".join(difflib.unified_diff(self.candidate.splitlines(True), self.original.splitlines(True),
                                            fromfile="a/"+TARGET, tofile="b/"+TARGET))
        self.assertEqual(apply_exact_patch(self.candidate, reverse).encode(), self.raw)

    def test_machine_manifest_hashes_are_exact(self):
        pins = json.loads(PATCH.with_suffix(".json").read_bytes())
        self.assertEqual(pins["path"], TARGET)
        self.assertEqual(pins["beforeSha256"], BEFORE_SHA)
        self.assertEqual(pins["afterSha256"], sha(self.candidate.encode()))
        self.assertEqual(pins["patchSha256"], sha(PATCH.read_bytes()))

    def test_real_link_gate_uniform_setup_success_and_cleanup_are_retained(self):
        web = select_web(function(self.candidate), True)
        query = "glGetProgramiv(spec.id, GL_LINK_STATUS, &status);"
        self.assertEqual(web.count(query), 1)
        self.assertLess(web.index("glCompileShader(spec.frag_id)"), web.index(query))
        self.assertGreater(web.index("glGetShaderiv(shader_ids[i], GL_COMPILE_STATUS"), web.index(query))
        old_tail = function(self.original).split(query, 1)[1]
        new_tail = function(self.candidate).split(query, 1)[1].replace(DEFERRED_DIAGNOSTICS, "", 1)
        self.assertEqual(new_tail, old_tail)
        self.assertEqual(web.count("spec.ok = true;"), 1)
        self.assertLess(web.index("_get_uniform_locations(spec, p_version)"), web.index("spec.ok = true"))

    def test_unknown_context_and_extra_file_patch_are_rejected(self):
        with self.assertRaises(ValueError):
            apply_exact_patch(self.original.replace("glCompileShader(spec.vert_id);", "changed();", 1), PATCH.read_text())
        with self.assertRaises(ValueError):
            apply_exact_patch(self.original, PATCH.read_text()+"--- a/other.cpp\n+++ b/other.cpp\n")

    def test_standalone_actual_cpp_function_success_and_failure_paths(self):
        compiler = Path("C:/MinGW/bin/g++.exe")
        self.assertTrue(compiler.is_file(), "Standalone fixture compiler is required; no silent skip")
        parent = ROOT / "artifacts/startup-v135/independent"
        parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="deferred-web-validation-", dir=parent))
        outputs = {}
        env = os.environ.copy()
        env["PATH"] = str(compiler.parent)+os.pathsep+env.get("PATH", "")
        for label, body, flags in (("web", function(self.candidate), ["-DWEB_ENABLED"]),
                                    ("native", function(self.candidate), []),
                                    ("original-native", function(self.original), [])):
            source, exe = stage / (label+".cpp"), stage / (label+".exe")
            source.write_text(CPP_PREFIX+body+CPP_SUFFIX, encoding="utf-8", newline="\n")
            command = [str(compiler), "-std=c++11", "-O0", *flags, str(source), "-o", str(exe)]
            result = subprocess.run(command, capture_output=True, timeout=30, env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            (stage / (label+"-compile.log")).write_bytes(result.stdout+result.stderr)
            self.assertEqual(result.returncode, 0, (result.stdout+result.stderr).decode(errors="replace"))
            run = subprocess.run([str(exe)], capture_output=True, timeout=10, env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            (stage / (label+"-run.log")).write_bytes(run.stdout+run.stderr)
            self.assertEqual(run.returncode, 0, (run.stdout+run.stderr).decode(errors="replace"))
            outputs[label] = run.stdout.decode()
        self.assertEqual(outputs["native"], outputs["original-native"], "Non-Web complete mock call/log traces identical")
        self.assertEqual(outputs["web"].count(" PASS "), 9)
        self.assertEqual(outputs["native"].count(" PASS "), 8)
        report = {"status": "PASS_STANDALONE_ACTUAL_FUNCTION_MOCK_GL", "sourceBeforeSha256": BEFORE_SHA,
                  "candidateSha256": sha(self.candidate.encode()), "patchSha256": sha(PATCH.read_bytes()),
                  "webCases": 9, "nativeCasesByteExactVsOriginal": 8,
                  "sourceUnchanged": sha(SOURCE.read_bytes()) == BEFORE_SHA,
                  "limits": "Standalone mocked GL only; not an engine build, real GPU/driver test or performance result."}
        (stage / "evidence.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        self.assertTrue(report["sourceUnchanged"])
        print("Standalone evidence: " + (stage / "evidence.json").as_posix())


if __name__ == "__main__":
    if sys.argv[1:] == ["--print-patch"]:
        data = SOURCE.read_bytes()
        if sha(data) != BEFORE_SHA: raise SystemExit("Pinned source changed")
        text = data.decode()
        print("".join(difflib.unified_diff(text.splitlines(True), expected_candidate(text).splitlines(True),
                                        fromfile="a/"+TARGET, tofile="b/"+TARGET)), end="")
    else:
        unittest.main(verbosity=2)
