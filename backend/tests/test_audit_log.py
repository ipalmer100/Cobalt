from cobalt.audit_log import _TAIL_CHUNK_SIZE, append_entry, read_entries


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
    assert (tmp_path / ".cobalt" / "audit_log.jsonl").exists()


def test_corrupted_line_is_skipped_not_fatal(tmp_path):
    log_path = tmp_path / ".cobalt" / "audit_log.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text('{"action": "write_cell", "who": "Isaac"}\nnot valid json\n{"action": "write_field", "who": "Isaac"}\n')

    entries = read_entries(str(tmp_path))
    assert len(entries) == 2


def test_read_entries_tail_read_spans_multiple_chunks(tmp_path):
    """read_entries reads backward from the end of the file in fixed-size
    chunks (_read_tail_lines) rather than the whole file -- exercise a log
    big enough that satisfying a limit requires more than one chunk read,
    to catch any off-by-one at a chunk boundary."""
    n = 5000  # short lines, but enough that many chunk-sized reads are needed
    for i in range(n):
        append_entry(str(tmp_path), "write_cell", "Isaac", n=i)

    log_path = tmp_path / ".cobalt" / "audit_log.jsonl"
    assert log_path.stat().st_size > _TAIL_CHUNK_SIZE * 3  # confirms multiple chunks are actually exercised

    entries = read_entries(str(tmp_path), limit=250)
    assert [e["n"] for e in entries] == list(range(n - 1, n - 251, -1))  # most recent first, contiguous, no gaps


def test_read_entries_limit_larger_than_log_returns_everything(tmp_path):
    for i in range(10):
        append_entry(str(tmp_path), "write_cell", "Isaac", n=i)
    entries = read_entries(str(tmp_path), limit=10_000)
    assert len(entries) == 10
    assert entries[0]["n"] == 9


def test_read_entries_handles_a_single_line_larger_than_one_chunk(tmp_path):
    """A pathological giant single entry (e.g. a fill-handle batch touching
    hundreds of rows, embedded as one JSON line) must not break the
    backward chunk-boundary logic even when it alone exceeds the chunk size."""
    append_entry(str(tmp_path), "write_cell", "Isaac", n=0)
    append_entry(str(tmp_path), "fill_column", "Isaac", edits=["x" * _TAIL_CHUNK_SIZE * 2])
    append_entry(str(tmp_path), "write_cell", "Isaac", n=2)

    entries = read_entries(str(tmp_path), limit=10)
    assert [e.get("action") for e in entries] == ["write_cell", "fill_column", "write_cell"]
    assert entries[2]["n"] == 0


def test_a_prerename_state_folder_is_adopted_not_abandoned(tmp_path):
    """The app was SpecWrite before it was Cobalt, and its state lives in
    the customer's own folder beside their specs.

    A vault that has already been used holds an audit trail and a set of
    exception-queue decisions somebody made table by table. Looking only
    under the new name would silently orphan all of it: the log would
    appear to restart at the rename and every triaged heading would come
    back as an open exception.
    """
    from cobalt.section_mappings import load_mappings, save_mapping, state_dir

    legacy = tmp_path / ".specwrite"
    legacy.mkdir()
    (legacy / "audit_log.jsonl").write_text(
        '{"timestamp": "2026-01-01T00:00:00+00:00", "action": "write_cell", '
        '"who": "Isaac", "spec_number": "EG1419"}\n',
        encoding="utf-8",
    )

    assert state_dir(str(tmp_path)) == str(legacy)

    # the old entries are still there...
    existing = read_entries(str(tmp_path))
    assert [e["who"] for e in existing] == ["Isaac"]

    # ...and new writes join them rather than starting a second log.
    # (read_entries is most-recent-first.)
    append_entry(str(tmp_path), "write_cell", "Someone Else", spec_number="EG1543")
    assert [e["who"] for e in read_entries(str(tmp_path))] == ["Someone Else", "Isaac"]
    assert not (tmp_path / ".cobalt").exists()

    # Exception-queue decisions land in the same adopted folder.
    save_mapping(str(tmp_path), "Press Specification", "Process Routing", who="Isaac")
    assert (legacy / "section_mappings.json").is_file()
    assert list(load_mappings(str(tmp_path)))


def test_a_fresh_vault_uses_the_current_state_folder(tmp_path):
    """Nothing pre-existing, so nothing to adopt -- the new name is used."""
    from cobalt.section_mappings import state_dir

    append_entry(str(tmp_path), "write_cell", "Isaac", spec_number="EG1419")

    assert state_dir(str(tmp_path)) == str(tmp_path / ".cobalt")
    assert (tmp_path / ".cobalt" / "audit_log.jsonl").is_file()
    assert not (tmp_path / ".specwrite").exists()
