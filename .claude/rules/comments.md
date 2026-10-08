# Comments stay short

- A docstring or comment is one or two lines. Say why, not what the code already says.
- No multi-paragraph docstrings, no comment blocks narrating a function step by step.
- No comments that restate the line below them, name the task or PR, or say "added for X".
- Exception: `@tool` docstrings are model-facing instructions and may be as long as the tool needs.
- Longer reasoning belongs in the commit message, the PR body or `docs/`, not in the code.
