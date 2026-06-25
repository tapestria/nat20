"""Tests for tools.regen._gate_for_yaml — the per-file SRD admission gate.

Distinct from test_srd_gate.py, which only covers gate_decision(). These
exercise the YAML → verdict path, in particular the edition (rules) check.
"""

import textwrap

from tools.regen import _gate_for_yaml


def _write(tmp_path, body: str):
    path = tmp_path / "doc.yml"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_gate_admits_2024_edition(tmp_path):
    path = _write(
        tmp_path,
        """
        name: Shortsword
        flags: {}
        system:
          source:
            license: "CC-BY-4.0"
            rules: "2024"
        """,
    )
    assert _gate_for_yaml(path).is_srd is True


def test_gate_still_admits_2014_edition(tmp_path):
    path = _write(
        tmp_path,
        """
        name: Longsword
        flags: {}
        system:
          source:
            license: "CC-BY-4.0"
            rules: "2014"
        """,
    )
    assert _gate_for_yaml(path).is_srd is True
