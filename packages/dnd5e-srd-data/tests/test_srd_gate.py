from tools.translators.srd_gate import SrdSourceVerdict, gate_decision


def test_all_three_agree_srd_passes():
    v = SrdSourceVerdict(foundry_srd=True, open5e_srd=True, five_e_bits_srd=True)
    decision = gate_decision(v)
    assert decision.is_srd is True
    assert decision.quarantine_reason is None


def test_all_three_agree_non_srd_excluded():
    v = SrdSourceVerdict(foundry_srd=False, open5e_srd=False, five_e_bits_srd=False)
    decision = gate_decision(v)
    assert decision.is_srd is False
    assert decision.quarantine_reason == "unanimous_non_srd"


def test_disagreement_quarantines():
    v = SrdSourceVerdict(foundry_srd=True, open5e_srd=False, five_e_bits_srd=True)
    decision = gate_decision(v)
    assert decision.is_srd is False
    assert "disagreement" in (decision.quarantine_reason or "")


def test_missing_source_quarantines():
    v = SrdSourceVerdict(foundry_srd=True, open5e_srd=None, five_e_bits_srd=True)
    decision = gate_decision(v)
    assert decision.is_srd is False
    assert "missing" in (decision.quarantine_reason or "")
