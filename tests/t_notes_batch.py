# -*- coding: utf-8 -*-
"""notes 模块批量笔记功能测试（写入 F 盘临时文件，测完删除）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.core import notes as notes_mod  # noqa: E402

# 无论系统临时目录在哪，一律写 F 盘（约束：不碰 C 盘）
TMP_BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "tmp")
os.makedirs(TMP_BASE, exist_ok=True)
tmp = os.path.join(TMP_BASE, "notes_test_batch.json")
if os.path.exists(tmp):
    os.remove(tmp)
notes_mod.init(tmp)
ACC, TALK = "acct_test", "talker_test"

try:
    # 1) 批量写笔记
    n = notes_mod.set_messages_batch(ACC, TALK, ["m1", "m2", "m3"], note="共同笔记")
    assert n == 3, f"批量写应返回3, got {n}"
    # 2) note_mids 高亮集合
    s = notes_mod.note_mids(ACC, TALK)
    assert s == {"m1", "m2", "m3"}, f"note_mids 不对: {s}"
    # 3) 删除部分笔记（保留星标）
    notes_mod.set_messages_batch(ACC, TALK, ["m2"], star=True)
    n = notes_mod.delete_notes_batch(ACC, TALK, ["m1", "m2"])
    assert n == 2, f"删2条应返回2, got {n}"
    s = notes_mod.note_mids(ACC, TALK)
    assert s == {"m3"}, f"删除后应只剩 m3, got {s}"
    # m2 星标应保留（记录仍在）
    got = notes_mod.get_message(ACC, TALK, "m2")
    assert got and got.get("star") and not got.get("note"), f"m2 应保星标删笔记: {got}"
    # m1 应整条移除
    assert notes_mod.get_message(ACC, TALK, "m1") is None, "m1 应整条删除"
    # 4) 全删（连星标）
    n = notes_mod.delete_notes_batch(ACC, TALK, ["m2", "m3"], keep_star=False)
    assert n == 2, f"全删应返回2, got {n}"
    assert notes_mod.note_mids(ACC, TALK) == set(), "应无笔记消息"
    assert notes_mod.get_message(ACC, TALK, "m2") is None, "m2 应整条移除"
    assert notes_mod.get_message(ACC, TALK, "m3") is None, "m3 应整条移除"
    # 5) 空笔记不应保存（留空）
    n = notes_mod.set_messages_batch(ACC, TALK, ["m9"], note="")
    assert n == 0, f"空笔记应返回0, got {n}"
    # 6) 单条 set_message 仍兼容
    notes_mod.set_message(ACC, TALK, "m7", note="单独")
    assert notes_mod.get_message(ACC, TALK, "m7")["note"] == "单独"
    print("ALL PASS: 批量写/删/保星标/高亮集合/兼容性全部正确")
finally:
    try:
        os.remove(tmp)
    except OSError:
        pass