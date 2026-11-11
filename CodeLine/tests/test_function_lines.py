"""Run with: python CodeLine/tests/test_function_lines.py [--dataset test/testcase3]."""
import argparse
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile
import textwrap


PROJECT = Path(__file__).resolve().parents[1]
LANGUAGES = ("C", "C++", "JAVA", "Python", "C#")


def cli_rows(binary, folder, *flags):
    output = subprocess.check_output([str(binary), str(folder), *flags], encoding="utf-8")
    rows = {}
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if cells and cells[0] in LANGUAGES:
            rows[cells[0]] = [float(cell) if cell != "/" else "/" for cell in cells[1:]]
    return rows


def check_folder(binary, folder, expected=None):
    cli = cli_rows(binary, folder)
    web = json.loads(subprocess.check_output(
        ["node", str(PROJECT / "tests" / "check_web.cjs"), str(folder)], encoding="utf-8"))
    assert cli == web["rows"], (folder, cli, web["rows"])
    if expected is not None:
        by_name = {Path(detail["file"]).name: detail for detail in web["details"]}
        for name, lengths in expected.items():
            actual = by_name[name]
            assert sorted(actual["functionCodeLines"]) == sorted(lengths), (name, actual, lengths)
            assert actual["functions"] == len(lengths), (name, actual)
        for language in LANGUAGES:
            lengths = [length for detail in web["details"] if detail["language"] == language
                       for length in expected[Path(detail["file"]).name]]
            summary = [len(lengths), max(lengths, default=0), min(lengths, default=0),
                       round(statistics.mean(lengths), 2) if lengths else 0,
                       statistics.median(lengths) if lengths else 0]
            assert cli[language][4:] == summary, (language, cli[language], summary)
    return web


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="loc-regression-") as temporary:
        temporary = Path(temporary)
        binary = temporary / ("loc.exe" if os.name == "nt" else "loc")
        subprocess.run([shutil.which("g++") or "g++", "-std=c++11", "-O2", "-Wall", "-Wextra",
                        str(PROJECT / "loc.cpp"), "-o", str(binary)], check=True)
        fixtures = temporary / "fixtures"
        fixtures.mkdir()
        cases = {
            "bounds.c": ("""
                #include <stdio.h>
                int global = 0;
                int prototype(void);
                // A multiline signature; braces in comments/strings are ignored.
                int
                first(
                    int x)
                {
                    // comment

                    puts("} fake() {");
                    if (x) { x++; }
                    return x;
                }
                void empty(void) {}
                int other_global = 3;
            """, [8, 1]),
            "operators.cpp": ("""
                struct Box {
                public:
                    int value;
                    Box() : value{1} {}
                    int operator()(int x) const { return x; }
                    bool operator<(const Box& b) const { return value < b.value; }
                    void method()
                    {
                        auto fn = []() { return 1; };
                        if (fn()) { value++; }
                    }
                };
            """, [1, 1, 1, 5]),
            "Methods.java": ("""
                package sample;
                class Methods {
                    Methods() {}
                    @Override
                    public String toString() {
                        return "{";
                    }
                    void prototype();
                }
            """, [1, 4]),
            "Methods.cs": ("""
                class Methods {
                    public Methods() {}
                    public void Empty() {}
                    public int Value() {
                        // ignore
                        return 1;
                    }
                }
            """, [1, 1, 3]),
            "nested.py": ("""
                GLOBAL = 1
                @decorator
                async def outer(
                    value,
                ):
                    \"\"\"Docstring is excluded.\"\"\"
                    # comment
                    def inner(): return 1
                    return (
                value + inner()
                    )
                GLOBAL = 2

                def final():
                    return GLOBAL
            """, [7, 1, 2]),
            "tabs.py": ("def one():\r\n\treturn 1\r\n\r\n'global string'\r\ndef two(): return 2", [2, 1]),
            "continuation.py": ("def one():\n    result = 1 + \\\n0\n    return result\n\nclass End: pass\n", [4]),
            "string_continuation.py": ('def one():\n    call(\n        "a\\\n# ) } still a string")\n    return 1\n\ndef two(): return 2\n', [5, 1]),
            "no_functions.py": ("GLOBAL = 42\n", []),
            "empty.c": ("", []),
            "macros.c": ("#define FAKE(x) { x; }\nvoid real() {}\n", [1]),
            "incomplete.cpp": ("void incomplete() {\n    return;\n", []),
        }
        expected = {}
        for name, (source, lengths) in cases.items():
            (fixtures / name).write_bytes(textwrap.dedent(source).lstrip("\n").encode("utf-8"))
            expected[name] = lengths
        # A large file must not inflate the length of its only short function.
        (fixtures / "large.c").write_text("int global;\n" * 12000 + "void small() {}\n", encoding="utf-8")
        expected["large.c"] = [1]
        check_folder(binary, fixtures, expected)
        globals_only = temporary / "globals-only"
        globals_only.mkdir()
        (globals_only / "globals.c").write_text("int global = 1;\n", encoding="utf-8")
        (globals_only / "globals.py").write_text("GLOBAL = 1\n", encoding="utf-8")
        (globals_only / "empty.c").write_bytes(b"")
        check_folder(binary, globals_only, {"globals.c": [], "globals.py": [], "empty.c": []})
        simple = cli_rows(binary, fixtures, "-s")
        assert all(row[2:4] == ["/", "/"] for row in simple.values())
        samples = check_folder(binary, PROJECT / "samples", {
            "hello.c": [5], "util.cpp": [7, 1], "Main.java": [3], "script.py": [2],
        })
        assert len(samples["details"]) == 4
        print("PASS: function ranges, comments, empty bodies, operators, nested/multiline Python, large files, CLI/web parity, simple mode, samples")
        if args.dataset:
            result = check_folder(binary, args.dataset.resolve())
            for language, row in result["rows"].items():
                files = [detail for detail in result["details"] if detail["language"] == language and detail["functionCodeLines"]]
                largest = max(files, key=lambda detail: max(detail["functionCodeLines"]), default=None)
                print(language, row, "largest:", largest["file"] if largest else "-")
            print("PASS: dataset CLI/web parity")


if __name__ == "__main__":
    main()
