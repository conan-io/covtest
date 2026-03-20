from unidiff import PatchSet


def diff(text_diff):
    """
    process a unidiff as text string
    :param text_diff:
    :return: a dict {filename, [modified lines]}
    """
    patch = PatchSet(str(text_diff))
    result = {}
    for f in patch.added_files:
        lines = []
        for hunk in f:
            lines.extend(line.source_line_no for line in hunk.source_lines() if not line.is_context)
        result[f.path] = lines
    for f in patch.modified_files:
        lines = []
        # source_lines() does not account for new additions
        for hunk in f:
            lines.extend(line.source_line_no for line in hunk.source_lines() if not line.is_context)
            lines.extend(line.target_line_no for line in hunk.target_lines() if not line.is_context)
        result[f.path] = list(sorted(set(lines)))
    return result
