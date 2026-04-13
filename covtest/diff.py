from unidiff import PatchSet


def diff(text_diff):
    """
    process a unidiff as text string
    :param text_diff:
    :return: a dict {filename, [modified lines]}
    """

    def filter_inserted_groups(ins_lines):
        result = []
        last = -10
        for i in ins_lines:
            if i == last + 1:
                last = i
                continue
            last = i
            result.append(i)
        return result

    patch = PatchSet(str(text_diff))
    inserted = {}
    modified = {}
    for f in patch.added_files:
        lines = []
        # TODO: How added files in a diff work towards prediction? Only new tests?
        for hunk in f:
            lines.extend(line.source_line_no for line in hunk.source_lines() if not line.is_context)
        inserted[f.path] = lines
    for f in patch.modified_files:
        modlines = []
        inslines = []
        for hunk in f:
            # Only report source-side line numbers. Coverage data is indexed against
            # the original file, so target line numbers of pure insertions must not be
            # returned — they collide with source coordinates of shifted existing code.
            modlines.extend(line.source_line_no for line in hunk.source_lines() if not line.is_context)
            inslines.extend(line.target_line_no for line in hunk.target_lines() if not line.is_context)
        modified[f.path] = list(sorted(set(modlines)))
        inserted[f.path] = filter_inserted_groups(list(sorted(set(inslines))))
    return modified, inserted
