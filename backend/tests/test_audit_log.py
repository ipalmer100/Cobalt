from specwrite.audit_log import append_entry, read_entries


def test_append_and_read_entries(tmp_path):
    append_entry(str(tmp_path), "write_cell", "Isaac", file_path="a.docx", old_value="X", new_value="Y")
    append_entry(str(tmp_path), "write_field", "Isaac", file_path="b.docx", label="Customer")

    entries = read_entries(str(tmp_path))
    assert len(entries) == 2
    # most recent first
    assert entries[0]["action"] == "write_field"
    assert entries[1]["action"] == "write_cell"
    assert entries[1]["old_value"] == "X"
    assert "timestamp" in entries[0]


def test_read_entries_on_empty_vault_returns_empty_list(tmp_path):
    assert read_entries(str(tmp_path)) == []


def test_who_defaults_to_empty_string(tmp_path):
    append_entry(str(tmp_path), "write_cell", "")
    entries = read_entries(str(tmp_path))
    assert entries[0]["who"] == ""


def test_read_entries_respects_limit(tmp_path):
    for i in range(10):
        append_entry(str(tmp_path), "write_cell", "Isaac", n=i)
    entries = read_entries(str(tmp_path), limit=3)
    assert len(entries) == 3
    assert entries[0]["n"] == 9  # most recent first


def test_log_lives_in_dotfolder_inside_vault(tmp_path):
    append_entry(str(tmp_path), "write_cell", "Isaac")
    assert (tmp_path / ".specwrite" / "audit_log.jsonl").exists()


def test_corrupted_line_is_skipped_not_fatal(tmp_path):
    log_path = tmp_path / ".specwrite" / "audit_log.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text('{"action": "write_cell", "who": "Isaac"}\nnot valid json\n{"action": "write_field", "who": "Isaac"}\n')

    entries = read_entries(str(tmp_path))
    assert len(entries) == 2
