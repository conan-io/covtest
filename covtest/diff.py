from unidiff import PatchSet


def diff(text_diff):
    """Process a unified diff and return per-file change classification.

    Returns:
        {filename: {"modified": [...], "deleted": [...], "inserted": [...]}}

    - modified: source-side line numbers of paired replacements (a removed line
                matched with a corresponding added line in the same hunk).
    - deleted:  source-side line numbers of unpaired removals (lines removed
                with no corresponding addition).
    - inserted: target-side line numbers of unpaired additions (lines added
                with no corresponding removal), blank lines excluded.
    """
    patch = PatchSet(str(text_diff))
    result = {}

    for f in patch.added_files:
        inslines = []
        for hunk in f:
            for line in hunk:
                if line.is_added and line.value.strip():
                    inslines.append(line.target_line_no)
        result[f.path] = {"modified": [], "deleted": [], "inserted": sorted(inslines)}

    for f in patch.removed_files:
        dellines = []
        for hunk in f:
            for line in hunk:
                if line.is_removed:
                    dellines.append(line.source_line_no)
        result[f.path] = {"modified": [], "deleted": sorted(dellines), "inserted": []}

    for f in patch.modified_files:
        modlines = []
        dellines = []
        inslines = []
        for hunk in f:
            removed = [l for l in hunk if l.is_removed]
            added = [l for l in hunk if l.is_added]
            # Pair removals with additions in order.
            # Paired   → replacement (modified): keep the source line number.
            # Unpaired removal → true deletion.
            # Unpaired addition (non-blank) → pure insertion.
            n_mod = min(len(removed), len(added))
            for i in range(n_mod):
                modlines.append(removed[i].source_line_no)
            for i in range(n_mod, len(removed)):
                dellines.append(removed[i].source_line_no)
            for i in range(n_mod, len(added)):
                # we cannot assume that inserted blank lines do not change anything! What if
                # they change a text string?
                # TODO: This can be optimized by syntactic diff, like difftastic
                inslines.append(added[i].target_line_no)

        result[f.path] = {
            "modified": sorted(set(modlines)),
            "deleted": sorted(set(dellines)),
            "inserted": sorted(set(inslines)),
        }

    return result
