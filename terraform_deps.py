"""
A few useful modules geared toward determining what
terraform roots are affected if you modify a module.

Hashicorp recommends that your modules live in their own repos
but, in practice, a lot of teams still keep modules in the same
repo as their roots.


A basic example implementation is
included...

Usage:
# run from the root of your github repo
terraform_deps.py [ROOTS_PATH] [MODULE_PATH ...]

It will find the roots in ROOT_PATH and scan the .tf files for
module source declarations and follow the relative path for those
to find the tree of dependencies. A flat dictionary is built.
Then it will scan the dictionary for each module you reference to
tell you what you seek: which roots are dependent on this module.
"""

import functools
import os
import re
import sys
import time

from collections import defaultdict

import hcl2

def get_root_paths(start_path: str) -> list:
    """Walk paths to discover roots"""
    # assumes roots have a backend or tf cloud defined
    found_paths = set()
    # find unique tf paths
    if not os.path.isdir(start_path):
        raise Exception(f"Invalid start path {start_path}")
    for this_path, dirs, files in os.walk(start_path):
        if ".terraform" in this_path:
            continue
        for fl in files:
            if fl.endswith(".tf"):
                if file_has_backend(os.path.join(this_path, fl)):
                    found_paths.add(this_path)
                    break
    return list(found_paths)


def file_has_backend(path: str) -> bool:
    with open(path) as f:
        data = f.read()
        if re.search(r"backend +\"", data) or re.search(r"cloud +\{", data):
            return True
        else:
            return False

def extract_sources(path: str) -> list:
    """Find/extract module sources for a tf file.
        hcl2 is a bit slow, tbh. regexp would be way faster
        but not sure it can be done reliably
        e.g. this makes the wrong assumption that source is on the next
        line after module {
        matches = re.findall(r"module +\"\S+\" +\{\s+source += +\"(\S+)\"", data, flags=re.DOTALL)
        for item in matches:
            sources.append(item)
    """
    sources = []
    with open(path) as f:
        data = f.read()
        # only deserialize if we need to (3x faster)
        if "source " in data:
            tf_dict = hcl2.loads(data)
            for m in tf_dict.get('module', []):
                for _, module_dict in m.items():
                    source: str = module_dict.get('source')
                    sources.append(source)
    return sources

def get_tf_files(path: str) -> list:
    if not os.path.isdir(path):
        raise Exception(f"The path {path} either doesn't exist or isn't a directory")
    files: list = os.listdir(path)
    return [x for x in files if x.endswith(".tf")]


def build_dependency_dict(roots: list, start_dir: str) -> dict:
    """Build a flat dict of dependency relationships for tf roots.
    Returns a dict where the key is every module and the
    value is the set of modules or roots that depend on it.
    """
    # map of modules and their direct dependents
    dependents = defaultdict(set)
    os.chdir(start_dir)

    @functools.lru_cache()
    def find_deps_for_dir(tf_dir: str) -> None:

        for file in get_tf_files(tf_dir):
            sources: list = extract_sources(os.path.join(tf_dir, file))
            for source in sources:
                if "./" in source:
                    os.chdir(tf_dir)
                    abs_mod_path = os.path.abspath(source)
                    rel_mod_path = os.path.relpath(abs_mod_path, start_dir)
                    rel_child_path = os.path.relpath(tf_dir, start_dir)
                    dependents[rel_mod_path].add(rel_child_path)
                    find_deps_for_dir(abs_mod_path)

    for start_root in roots:
        os.chdir(start_dir)
        find_deps_for_dir(os.path.abspath(start_root))
    return dependents


def find_mods_affected(subject: str, modules: set, deps_dict: dict) -> set:
    """Find dependent modules for a given modules"""
    for dep in deps_dict.get(subject, []):
        modules.add(dep)
        modules = find_mods_affected(dep, modules, deps_dict)
    return modules


def main():
    start_dir: str = os.path.abspath(os.path.curdir)
    root_path: str = sys.argv[1]
    mods: list = sys.argv[2:]
    roots = get_root_paths(root_path)
    print(f"scanning {len(roots)} roots...")
    start = time.time()
    dependents = build_dependency_dict(roots, start_dir)
    elapsed: int = int(time.time() - start)
    print(f"Built dependency map for {len(roots)} roots in {elapsed}s")
    print()
    for mod in mods:
        print(f"recursive scan to find those dependent on: {mod}...")
        dmods: list = find_mods_affected(mod, set(), dependents)
        for dmod in sorted(dmods):
            print(dmod)
        print()


if __name__ == "__main__":
    main()
