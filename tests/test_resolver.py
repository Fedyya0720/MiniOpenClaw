"""Phase 1 dependency parser and version matcher tests."""
import json
import tempfile
import unittest
from pathlib import Path

from resolver.dep_parser import parse_environment, parse_project, parse_pyproject, parse_requirements
from resolver.specifier import compare_versions, matches


class DependencyParserTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_requirements_extras_markers_and_ignored_options(self):
        path = self.root / "requirements.txt"
        path.write_text(
            "# comment\n-r base.txt\nrequests[security]>=2.28,<3; python_version >= '3.10'\nplain\n",
            encoding="utf-8",
        )
        result = parse_requirements(path)
        self.assertEqual([item.name for item in result], ["requests", "plain"])
        self.assertEqual(result[0].extras, ["security"])
        self.assertEqual(result[0].specifier, ">=2.28,<3")
        self.assertIn("python_version", result[0].marker)

    def test_requirements_recursively_include_files_and_preserve_source(self):
        (self.root / "nested").mkdir()
        (self.root / "requirements.txt").write_text(
            "-r nested/base.txt\n--requirement=more.txt\nroot>=1\n", encoding="utf-8"
        )
        (self.root / "nested" / "base.txt").write_text("base==2\n", encoding="utf-8")
        (self.root / "more.txt").write_text("more @ https://example.test/more.whl\n", encoding="utf-8")
        parsed = parse_project(self.root)
        dependencies = parsed["dependencies"]
        self.assertEqual([item["name"] for item in dependencies], ["base", "more", "root"])
        self.assertTrue(dependencies[1]["non_searchable"])
        self.assertEqual(dependencies[1]["direct_reference"], "https://example.test/more.whl")
        self.assertEqual(dependencies[0]["source"], str((self.root / "nested" / "base.txt").resolve()))
        self.assertEqual(len(parsed["metadata"]["warnings"]), 0)
        self.assertEqual(
            parsed["metadata"]["files"],
            [
                str((self.root / "requirements.txt").resolve()),
                str((self.root / "nested" / "base.txt").resolve()),
                str((self.root / "more.txt").resolve()),
            ],
        )

    def test_include_escape_cycle_and_pip_options_are_reported_without_reading(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside==1\n", encoding="utf-8")
        (self.root / "requirements.txt").write_text(
            "-r ../outside.txt\n-r loop.txt\n--index-url https://index.example\nvalid==1\n", encoding="utf-8"
        )
        (self.root / "loop.txt").write_text("--requirement requirements.txt\n", encoding="utf-8")
        parsed = parse_project(self.root)
        self.assertEqual([item["name"] for item in parsed["dependencies"]], ["valid"])
        warnings = parsed["metadata"]["warnings"]
        self.assertEqual(len(warnings), 3)
        self.assertTrue(any("越过项目根目录" in item["reason"] for item in warnings))
        self.assertTrue(any("循环" in item["reason"] for item in warnings))
        self.assertTrue(any(item["raw"].startswith("--index-url") for item in warnings))
        self.assertNotIn(str(outside.resolve()), parsed["metadata"]["files"])

    def test_project_deduplicates_repeated_requirements_deterministically(self):
        (self.root / "requirements.txt").write_text("-r common.txt\nrepeat>=1\n", encoding="utf-8")
        (self.root / "common.txt").write_text("repeat>=1\nother==2\n", encoding="utf-8")
        (self.root / "pyproject.toml").write_text(
            '[project]\ndependencies=["repeat>=1", "project-only"]\n', encoding="utf-8"
        )
        parsed = parse_project(self.root)
        self.assertEqual(
            [item["name"] for item in parsed["dependencies"]],
            ["repeat", "other", "project-only"],
        )
        self.assertEqual(parsed["dependencies"][0]["source"], str((self.root / "common.txt").resolve()))
        json.dumps(parsed)

    def test_pyproject_stdlib_parser(self):
        path = self.root / "pyproject.toml"
        path.write_text(
            '[project]\nname="demo"\ndependencies=["flask~=3.0", "typing-extensions; python_version < \'3.11\'"]\n',
            encoding="utf-8",
        )
        result = parse_pyproject(path)
        self.assertEqual([item.name for item in result], ["flask", "typing-extensions"])

    def test_environment_conda_hints_and_pip_subsection(self):
        path = self.root / "environment.yml"
        path.write_text(
            "name: science\nchannels:\n  - conda-forge\ndependencies:\n  - python=3.11\n  - numpy>=1.26\n  - pip:\n    - httpx[http2]>=0.27\n",
            encoding="utf-8",
        )
        deps, metadata = parse_environment(path)
        self.assertEqual(metadata["conda_hints"]["name"], "science")
        self.assertEqual(metadata["pip_count"], 1)
        self.assertEqual([item.name for item in deps], ["python", "numpy", "httpx"])
        self.assertEqual(deps[0].specifier, "==3.11")

    def test_parse_project_json_serializable_and_tool(self):
        (self.root / "requirements.txt").write_text("demo>=1\n", encoding="utf-8")
        parsed = parse_project(self.root)
        json.dumps(parsed)
        from tools.resolver_tools import parse_deps_tool
        tool_result = json.loads(parse_deps_tool.run(project_path=str(self.root)))
        self.assertTrue(tool_result["ok"])
        self.assertEqual(tool_result["dependencies"][0]["name"], "demo")

    def test_parse_project_requires_supported_dependency_file(self):
        with self.assertRaises(FileNotFoundError):
            parse_project(self.root)
        with self.assertRaises(FileNotFoundError):
            parse_project(self.root / "missing")


class SpecifierTest(unittest.TestCase):
    def test_comparisons_and_and_semantics(self):
        self.assertTrue(matches("2.4.1", ">=2.0,<3,!=2.5"))
        self.assertFalse(matches("2.5", ">=2.0,<3,!=2.5"))
        self.assertTrue(matches("1.4.9", "~=1.4"))
        self.assertFalse(matches("2.0", "~=1.4"))
        self.assertTrue(matches("1.4.5", "~=1.4.5"))
        self.assertFalse(matches("1.5", "~=1.4.5"))

    def test_arbitrary_and_wildcard_equality(self):
        self.assertTrue(matches("release-candidate", "===release-candidate"))
        self.assertFalse(matches("release-candidate", "===release_candidate"))
        self.assertTrue(matches("1.2.0", "==1.2.*"))
        self.assertTrue(matches("1.2rc1", "==1.2.*"))
        self.assertFalse(matches("1.3.0", "==1.2.*"))
        self.assertTrue(matches("1.3.0", "!=1.2.*"))
        self.assertFalse(matches("1.2.4", "!=1.2.*"))
        with self.assertRaises(ValueError):
            matches("1.2", ">=1.2.*")

    def test_dotted_versions_and_prereleases(self):
        self.assertEqual(compare_versions("1.0", "1.0.0"), 0)
        self.assertLess(compare_versions("1.0rc1", "1.0"), 0)
        self.assertLess(compare_versions("1.0b2", "1.0rc1"), 0)
        self.assertGreater(compare_versions("1.0.post1", "1.0"), 0)

    def test_invalid_suffix_and_operator_rejected(self):
        with self.assertRaises(ValueError):
            matches("1.0", "^1.0")
        with self.assertRaises(ValueError):
            matches("1.0weird1", ">=1")


class CombinationsTest(unittest.TestCase):
    def setUp(self):
        import resolver.combinations as mod
        self.mod = mod
        # Reset cache between tests so fixtures are self-contained.
        mod._VERSION_CACHE.clear()
        mod._fetch_versions_impl = None

    def tearDown(self):
        self.mod._VERSION_CACHE.clear()
        self.mod._fetch_versions_impl = None

    def test_basic_combinations_with_mocked_versions(self):
        self.mod._fetch_versions_impl = lambda pkg: {
            "numpy": ["2.0.0", "1.26.4", "1.24.0"],
            "requests": ["2.31.0", "2.28.0"],
        }.get(pkg, [])
        deps = [{"name": "numpy", "specifier": ""}, {"name": "requests", "specifier": ""}]
        result = self.mod.generate_combinations(deps, max_candidates=10)
        self.assertEqual(result["returned"], 6)  # 3 × 2
        self.assertEqual(result["pruned_by_constraint"], 0)
        names = {tuple(sorted(c.keys())) for c in result["combinations"]}
        self.assertEqual(names, {("numpy", "requests")})

    def test_specifier_filters_versions(self):
        self.mod._fetch_versions_impl = lambda pkg: {
            "numpy": ["2.1.0", "2.0.0", "1.26.4", "1.24.0"],
        }.get(pkg, [])
        deps = [{"name": "numpy", "specifier": ">=2.0,<2.1"}]
        result = self.mod.generate_combinations(deps, max_candidates=5)
        # Only 2.0.0 matches >=2.0,<2.1
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["combinations"][0]["numpy"], "2.0.0")

    def test_constraint_prunes_conflicting_pairs(self):
        self.mod._fetch_versions_impl = lambda pkg: {
            "numpy": ["2.0.0", "1.26.4"],
            "torch": ["2.5.0", "2.4.0"],
        }.get(pkg, [])
        deps = [{"name": "numpy", "specifier": ""}, {"name": "torch", "specifier": ""}]
        constraints = [
            {"pkg_a": "numpy", "ver_a": "2.0.0", "pkg_b": "torch", "ver_b": "2.5.0"},
            {"pkg_a": "numpy", "ver_a": "1.26.4", "pkg_b": "torch", "ver_b": "2.4.0"},
        ]
        result = self.mod.generate_combinations(deps, constraints, max_candidates=10)
        # 2×2 = 4 combos total; 2 pruned by constraint → 2 remain.
        self.assertEqual(result["pruned_by_constraint"], 2)
        self.assertEqual(result["returned"], 2)
        for combo in result["combinations"]:
            combo_pair = (combo["numpy"], combo["torch"])
            self.assertNotIn(combo_pair, {("2.0.0", "2.5.0"), ("1.26.4", "2.4.0")})

    def test_max_candidates_caps_output(self):
        self.mod._fetch_versions_impl = lambda pkg: {
            "a": [str(v) for v in range(10)],
            "b": [str(v) for v in range(10)],
        }.get(pkg, [])
        deps = [{"name": "a", "specifier": ""}, {"name": "b", "specifier": ""}]
        result = self.mod.generate_combinations(deps, max_candidates=5)
        self.assertEqual(result["returned"], 5)

    def test_non_searchable_dependency_pinned_to_combinations(self):
        self.mod._fetch_versions_impl = lambda pkg: {
            "requests": ["2.31.0", "2.28.0"],
        }.get(pkg, [])
        deps = [
            {"name": "requests", "specifier": ""},
            {"name": "private-lib", "specifier": "", "non_searchable": True,
             "direct_reference": "git+https://git.example/private.git"},
        ]
        result = self.mod.generate_combinations(deps, max_candidates=5)
        self.assertEqual(result["non_searchable_count"], 1)
        for combo in result["combinations"]:
            self.assertEqual(combo["private-lib"], "git+https://git.example/private.git")

    def test_non_searchable_only_returns_one_pinned_entry(self):
        deps = [
            {"name": "priv", "non_searchable": True,
             "direct_reference": "file://./priv.whl"},
        ]
        result = self.mod.generate_combinations(deps, max_candidates=5)
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["combinations"][0], {"priv": "file://./priv.whl"})

    def test_empty_dependencies_returns_empty_combinations(self):
        result = self.mod.generate_combinations([], max_candidates=5)
        self.assertEqual(result["returned"], 0)
        self.assertEqual(result["combinations"], [])

    def test_version_cache_is_reused_across_calls(self):
        import resolver.combinations as fresh
        call_count = 0

        def counting(pkg):
            nonlocal call_count
            call_count += 1
            return {"numpy": ["2.0.0"]}.get(pkg, [])

        fresh._fetch_versions_impl = counting
        fresh._VERSION_CACHE.clear()
        fresh.generate_combinations([{"name": "numpy", "specifier": ""}], max_candidates=5)
        first = call_count
        fresh.generate_combinations([{"name": "numpy", "specifier": ""}], max_candidates=5)
        self.assertEqual(call_count, first)  # no additional calls
        fresh._fetch_versions_impl = None
        fresh._VERSION_CACHE.clear()

    def test_tool_produces_json_with_constraint_and_version_metadata(self):
        from tools.resolver_tools import generate_combinations_tool
        self.mod._fetch_versions_impl = lambda pkg: {
            "flask": ["3.0.0", "2.3.0"],
        }.get(pkg, [])
        deps = [{"name": "flask", "specifier": ">=2.3"}]
        constraints = [{"pkg_a": "flask", "ver_a": "3.0.0", "pkg_b": "click", "ver_b": "9.0"}]
        output = generate_combinations_tool.run(
            dependencies=deps, constraints=constraints, max_candidates=10,
        )
        parsed = json.loads(output)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["returned"], 2)
        self.assertEqual(len(parsed["combinations"]), 2)
        self.assertIn("version_sources", parsed)


if __name__ == "__main__":
    unittest.main()
