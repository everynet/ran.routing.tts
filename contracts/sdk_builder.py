import os
import re
import shutil
import subprocess
import sys
from builtins import print
from contextlib import contextmanager
from pathlib import Path

# Constants

CURRENT_DIR = Path(".")

TTI_PROJECT_NAME = "lorawan-stack"
TTI_GIT_REPO = f"https://github.com/TheThingsNetwork/{TTI_PROJECT_NAME}"

TTI_REPO_DIR = Path(f"./{TTI_PROJECT_NAME}")
TTI_API_DIR = TTI_REPO_DIR / "api"
TTI_THIRD_PARTY_DIR = TTI_API_DIR / "third_party"

OUTPUT_PACKAGE_NAME = "tti_contracts"
OUTPUT_PACKAGE_INTERNAL_IMPORTS = OUTPUT_PACKAGE_NAME
OUTPUT_PACKAGE_DIR = CURRENT_DIR / OUTPUT_PACKAGE_NAME
OUTPUT_PACKAGE_API_DIR = OUTPUT_PACKAGE_DIR / "lorawan_stack" / "api"


# Formatting
original_print = print

DOUBLE_LEFT_TOP = "\u2554"  # ╔
DOUBLE_VERTI_PIPE = "\u2551"  # ║
DOUBLE_LEFT_BOTTOM = "\u255a"  # ╚
DOUBLE_RIGHT_TOP = "\u2557"  # ╗
DOUBLE_RIGHT_BOTTOM = "\u255d"  # ╝
DOUBLE_HORIZ_PIPE = "\u2550"  # ═
SINGLE_LEFT_TOP = "\u250c"  # ┌
SINGLE_VERTI_PIPE = "\u2502"  # │
SINGLE_LEFT_BOTTOM = "\u2514"  # └
SINGLE_RIGHT_TOP = "\u2510"  # ┐
SINGLE_RIGHT_BOTTOM = "\u2518"  # ┘
SINGLE_HORIZ_PIPE = "\u2500"  # ─


def print_header_h1(text: str, h: int = 1):
    print(DOUBLE_LEFT_TOP + (DOUBLE_HORIZ_PIPE * (len(text) + 2)) + DOUBLE_RIGHT_TOP)
    print(DOUBLE_VERTI_PIPE + " " + text + " " + DOUBLE_VERTI_PIPE)
    print(DOUBLE_LEFT_BOTTOM + (DOUBLE_HORIZ_PIPE * (len(text) + 2)) + DOUBLE_RIGHT_BOTTOM)


def print_header_h2(text: str, h: int = 1):
    print(SINGLE_LEFT_TOP + (SINGLE_HORIZ_PIPE * (len(text) + 2)) + SINGLE_RIGHT_TOP)
    print(SINGLE_VERTI_PIPE + " " + text + " " + SINGLE_VERTI_PIPE)
    print(SINGLE_LEFT_BOTTOM + (SINGLE_HORIZ_PIPE * (len(text) + 2)) + SINGLE_RIGHT_BOTTOM)


class SpanStack:
    def __init__(self) -> None:
        self.stacks = [original_print]
        self.pad = SINGLE_VERTI_PIPE
        self._open = SINGLE_LEFT_TOP
        self._close = SINGLE_LEFT_BOTTOM
        self._msg_prefix = SINGLE_HORIZ_PIPE

    def _next_print(self):
        use_print = self.stacks[-1]

        def _print(*args, **kwargs):
            use_print(self.pad, *args, **kwargs)

        self.stacks.append(_print)
        return _print

    def add(self, open_msg: str | None = None):
        global print
        if open_msg:
            self.stacks[-1](f"{self._open} {open_msg}")
        else:
            self.stacks[-1](self._open)
        print = self._next_print()

    def pop(self, close_msg: str | None = None):
        global print
        self.stacks.pop()
        if close_msg:
            self.stacks[-1](f"{self._close} {close_msg}")
        else:
            self.stacks[-1](self._close)
        print = self.stacks[-1]


span_stack = SpanStack()


@contextmanager
def span(open_msg: str | None = None, close_msg: str | None = None):
    span_stack.add(open_msg)
    try:
        yield
    finally:
        span_stack.pop(close_msg)


# Main utils


def download_source_repo():
    subprocess.run(["git", "clone", TTI_GIT_REPO])


def compile_proto(
    source_file: Path,
    output_folder: Path,
    includes: list[Path] | None = None,
    grpc: bool = True,
    mypy: bool = True,
    patch_imports: str | None = None,
    dest_subdir: Path | None = None,
):
    output_folder = output_folder.absolute()
    source_file = source_file.absolute()
    args = [
        "python",
        "-m",
        "grpc_tools.protoc",
        # "protoc"
    ]
    includes = includes or []
    for include in includes:
        args.extend(["--proto_path", str(include.absolute())])

    args.append(f"--python_out={output_folder}")
    if grpc:
        args.append(f"--grpc_python_out={output_folder}")
    if mypy:
        args.append(f"--mypy_out={output_folder}")
        if grpc:
            args.append(f"--mypy_grpc_out={output_folder}")

    args.append(str(source_file))

    print("Compiling...")

    cmd = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd.check_returncode()

    print("Done!")

    if patch_imports is None:
        return
    if not dest_subdir:
        raise Exception("If 'patch_imports provided, 'dest_subdir' also must be provided")

    print("Patching imports...")
    patch_imports_in_file(dest_subdir / f"{source_file.stem}_pb2.py", patch_imports)

    if grpc:
        grpc_py = dest_subdir / f"{source_file.stem}_pb2_grpc.py"
        if grpc_py.exists():
            patch_imports_in_file(grpc_py, patch_imports)

    if mypy:
        pb2_pyi = dest_subdir / f"{source_file.stem}_pb2.pyi"
        patch_lorawan_stack_api_usage(pb2_pyi, patch_imports)
        patch_imports_in_file(pb2_pyi, patch_imports)

        if grpc:
            grpc_pyi = dest_subdir / f"{source_file.stem}_pb2_grpc.pyi"
            # print(f"Patching {grpc_pyi}: {grpc_pyi.exists()}")
            if grpc_pyi.exists():
                patch_lorawan_stack_api_usage(grpc_pyi, patch_imports)
                patch_imports_in_file(grpc_pyi, patch_imports)

    print("Done!")


def autoformat_pyfile(file: Path):
    subprocess.run(
        ["python", "-m", "black", "-l", "120", "--target-version", "py310", str(file.absolute())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["python", "-m", "isort", str(file.absolute())],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def patch_lorawan_stack_api_usage(file: Path, import_prefix):
    regex = re.compile(r"(?<!import\s)lorawan_stack\.api\.")

    with file.open("r") as f:
        content = f.read()

    with file.open("w") as f:
        f.write(regex.sub(f"{import_prefix}.lorawan_stack.api.", content))


def patch_imports_in_file(file: Path, import_prefix):
    regex_import_from = re.compile(
        r"^from (?P<imp_from>(github|google\.api|lorawan_stack|protoc_gen_openapiv2)(\.[a-zA-Z0-9_.]+)?) "
        r"(?P<imp_what>import .*$)",
        flags=re.MULTILINE,
    )

    regex_import = re.compile(
        r"^import (?P<imp_from>(github|google\.api|lorawan_stack|protoc_gen_openapiv2)(\.[a-zA-Z0-9_.]+)?)$",
        flags=re.MULTILINE,
    )

    def repl_import_from(m):
        d = m.groupdict()
        return f"from {import_prefix}.{d['imp_from']} {d['imp_what']}"

    def repl_import(m):
        d = m.groupdict()
        return f"import {import_prefix}.{d['imp_from']}"

    with file.open("r") as f:
        content = f.read()

    with file.open("w") as f:
        f.write(regex_import.sub(repl_import, regex_import_from.sub(repl_import_from, content)))


class ImportOption:
    pass


class ImportAuto(ImportOption):
    pass


class ImportFrom(ImportOption):
    def __init__(self, path: Path) -> None:
        self.path = path


class ImportStatic(ImportOption):
    def __init__(self, modules_to_import: list[str]) -> None:
        self.modules_to_import = modules_to_import


def make_imports_file(path: Path, root: str = ".", import_opt: ImportOption | None = None):
    path = path.absolute()

    if import_opt is None:
        import_opt = ImportAuto()

    if isinstance(import_opt, ImportAuto):
        python_modules = sorted([f for f in (f.stem for f in path.rglob("*.py")) if "__init__" not in f])
    elif isinstance(import_opt, ImportFrom):
        python_modules = sorted([f for f in (f.stem for f in import_opt.path.rglob("*.py")) if "__init__" not in f])
    elif isinstance(import_opt, ImportStatic):
        python_modules = import_opt.modules_to_import[:]
    else:
        raise ValueError(f"Unknown import option: {repr(import_opt)}")

    if not len(python_modules):
        return

    init_file = path / "__init__.py"
    import_templ = "from {root} import {module}\n"
    all_templ = "__all__ = [{modules}]"

    with init_file.open("w") as f:
        for py_file in python_modules:
            f.write(import_templ.format(root=root, module=py_file))
        f.write("\n\n")
        f.write(all_templ.format(modules=", ".join(f'"{mod}"' for mod in python_modules)))
        f.write("\n")
    autoformat_pyfile(init_file)


def make_module_tree(path: Path):
    def traverse(root, branch):
        if not branch:
            return
        if branch[0] not in root:
            root[branch[0]] = {}
        traverse(root[branch[0]], branch[1:])

    def make_init_files_recursive(root):
        for path, successors in root.items():
            if not successors:
                return
            print(f"Making imports for '{path}'...")
            make_imports_file(path, import_opt=ImportStatic(modules_to_import=[folder.stem for folder in successors]))
            print("Done!")
            make_init_files_recursive(successors)

    modules = {}  # type: ignore
    for module_init in path.rglob("__init__.py"):
        traverse(modules, module_init.parents[::-1][2:])

    make_init_files_recursive(modules)


def has_grpc(file: Path) -> bool:
    regex = re.compile(r"^service [a-zA-Z_]* \{", flags=re.MULTILINE)
    with file.open("r") as f:
        match = regex.search(f.read())
    return match is not None


def build_third_party():
    for folder in list(TTI_THIRD_PARTY_DIR.iterdir()):
        with span(f"Building '{folder}' dependency", "Dependency built!"):
            for proto_file in folder.rglob("*.proto"):
                with span(f"Building '{proto_file}' proto file", "Proto file built!"):
                    relpath = proto_file.relative_to(TTI_THIRD_PARTY_DIR)
                    output_folder = os.sep.join(
                        [d_no_dot.strip().replace("-", "_") for d in relpath.parent.parts for d_no_dot in d.split(".")]
                    )
                    full_output_folder = OUTPUT_PACKAGE_DIR.joinpath(output_folder)
                    full_output_folder.mkdir(parents=True, exist_ok=True)
                    compile_proto(
                        source_file=proto_file,
                        output_folder=OUTPUT_PACKAGE_DIR,
                        includes=[TTI_THIRD_PARTY_DIR, proto_file.parents[0]],
                        mypy=False,
                        grpc=False,
                        # Patching
                        patch_imports=OUTPUT_PACKAGE_INTERNAL_IMPORTS,
                        dest_subdir=full_output_folder,
                    )
                    print("Assembling __init__.py file...")
                    make_imports_file(full_output_folder)
                    print("Done!")


def build_api():
    for proto_file in sorted(list(TTI_API_DIR.glob("*.proto"))):
        with span(f"Building '{proto_file}' proto file", "Proto file built!"):
            compile_proto(
                source_file=proto_file,
                output_folder=OUTPUT_PACKAGE_DIR,
                includes=[TTI_THIRD_PARTY_DIR, TTI_API_DIR.parents[1]],
                mypy=True,
                grpc=has_grpc(proto_file),
                # Patching
                patch_imports=OUTPUT_PACKAGE_INTERNAL_IMPORTS,
                dest_subdir=OUTPUT_PACKAGE_API_DIR,
            )
    print("Assembling __init__.py file...")
    make_imports_file(OUTPUT_PACKAGE_API_DIR)
    print("Done!")


def make_imports_full():
    with span("Generating imports for modules", "Imports generated!"):
        make_module_tree(OUTPUT_PACKAGE_DIR)
    print("Generating final module import...")
    make_imports_file(OUTPUT_PACKAGE_DIR, root=".lorawan_stack.api", import_opt=ImportFrom(OUTPUT_PACKAGE_API_DIR))
    print("Done!")


def build():
    print_header_h1(f"Cloning '{TTI_PROJECT_NAME}'")
    download_source_repo()
    print_header_h1("Building third-party dependencies")
    build_third_party()
    print_header_h1("Building API dependencies")
    with span():
        build_api()
    print_header_h1("Generating module import files")
    with span():
        make_imports_full()


def clean(clean_src: bool = True, clean_dst: bool = True):
    if not clean_src and not clean_dst:
        return
    print_header_h1("Performing clean")
    with span():
        if clean_src:
            print(f"Removing '{TTI_REPO_DIR}'...")
            shutil.rmtree(TTI_REPO_DIR, ignore_errors=True)
            print("Done!")
        if clean_dst:
            print(f"Removing '{OUTPUT_PACKAGE_DIR}'...")
            shutil.rmtree(OUTPUT_PACKAGE_DIR, ignore_errors=True)
            print("Done!")


if __name__ == "__main__":

    def usage():
        print("Usage: 'python build.py [build|rebuild|clean|clean [src|dst]]'")
        exit(0)

    if len(sys.argv) < 2:
        usage()

    cmd = sys.argv[1].lower()

    if cmd == "build":
        build()

    elif cmd == "rebuild":
        clean()
        build()

    elif cmd == "clean":
        if len(sys.argv) == 2:
            clean(clean_src=True, clean_dst=True)
        elif len(sys.argv) == 3:
            clean_arg = sys.argv[2].lower()
            if clean_arg == "src":
                clean(clean_src=True, clean_dst=False)
            elif clean_arg == "dst":
                clean(clean_src=False, clean_dst=True)
            else:
                usage()
        else:
            usage()
    else:
        usage()
