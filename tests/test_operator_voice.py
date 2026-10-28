from prts_tool.collectors.operator import parse_voice_records


def test_voice_table_preserves_languages_and_condition():
    raw = """{{VoiceTable|标题1=任命助理|台词1={{VoiceData/word|中文|博士，您好。}}{{VoiceData/word|英文|Hello, Doctor.}}|条件1=提升信赖至40%|语音1=CN_001.wav|标题2=交谈1|台词2={{VoiceData/word|中文|继续前进。}}}}"""
    text = parse_voice_records(raw, "阿米娅")
    assert "【任命助理】（提升信赖至40%）" in text
    assert "中文：博士，您好。" in text
    assert "英文：Hello, Doctor." in text
    assert "【交谈1】\n中文：继续前进。" in text
    assert "CN_001.wav" not in text


def test_voice_page_without_table_is_empty():
    assert parse_voice_records("{{#widget:VoiceTable}}", "阿米娅") == ""
