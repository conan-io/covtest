from unidiff import PatchSet


def diff(text_diff):
    """Process a unified diff and return per-file change classification.

    Returns:
        {filename: {"modified": [...], "deleted": [...], "inserted": {...}}}

    - modified: source-side line numbers of paired replacements (a removed line
                matched with a corresponding added line in the same hunk).
    - deleted:  source-side line numbers of unpaired removals (lines removed
                with no corresponding addition).
    - inserted: dict mapping old-file line positions to the count of lines
                inserted after that position.  {4: 3} means 3 lines were
                inserted after line 4 of the old file.  Key 0 is used for
                files that are entirely new (added files).
    """
    patch = PatchSet(str(text_diff))
    result = {}

    for f in patch.added_files:
        total = sum(1 for hunk in f for line in hunk if line.is_added)
        result[f.path] = {"modified": [], "deleted": [], "inserted": {0: total} if total else {}}

    for f in patch.removed_files:
        dellines = []
        for hunk in f:
            for line in hunk:
                if line.is_removed:
                    dellines.append(line.source_line_no)
        result[f.path] = {"modified": [], "deleted": sorted(dellines), "inserted": {}}

    for f in patch.modified_files:
        modlines = []
        dellines = []
        inslines = {}  # old_pos -> count of lines inserted after that position
        for hunk in f:
            removed = [line for line in hunk if line.is_removed]
            added = [line for line in hunk if line.is_added]
            # Pair removals with additions in order.
            # Paired   → replacement (modified): keep the source line number.
            # Unpaired removal → true deletion.
            # Unpaired addition → pure insertion.
            n_mod = min(len(removed), len(added))
            for i in range(n_mod):
                modlines.append(removed[i].source_line_no)
            for i in range(n_mod, len(removed)):
                dellines.append(removed[i].source_line_no)

            # Find insertion positions by scanning hunk lines in order.
            # Track the last seen old-file line number; unpaired added lines
            # are counted as inserted after that position.
            add_idx = 0
            last_source = hunk.source_start - 1
            for line in hunk:
                if line.is_context:
                    last_source = line.source_line_no
                elif line.is_removed:
                    last_source = line.source_line_no
                elif line.is_added:
                    if add_idx >= n_mod:
                        inslines[last_source] = inslines.get(last_source, 0) + 1
                    add_idx += 1

        result[f.path] = {
            "modified": sorted(set(modlines)),
            "deleted": sorted(set(dellines)),
            "inserted": inslines,
        }

    return result
