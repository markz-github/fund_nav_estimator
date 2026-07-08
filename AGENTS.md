# Codex Project Instructions

## Sensitive Files

- Do not read, print, summarize, copy, or expose the contents of `backend/.env`.
- If environment values are needed, ask the user to provide non-secret placeholders or confirm that commands should use the file without displaying it.
- It is OK to check whether `backend/.env` exists, but do not inspect its contents.

## Windows File Deletion

- Before deleting a file, confirm the target belongs to the current task and resolve the absolute path. The resolved path must stay inside this project workspace unless the user explicitly requested a different location.
- Prefer `apply_patch` delete hunks for tracked source or documentation files when the deletion is part of a code change. Use `git rm` only when the user has asked for Git-indexed deletion semantics.
- For generated or untracked files on Windows, use PowerShell end to end:
  ```powershell
  Remove-Item -LiteralPath "<absolute-path>"
  ```
- Do not compose deletion commands across shells, do not build deletion commands from untrusted strings, and do not use wildcards or recursive deletion for a single known file.
- Before any recursive delete or move, verify the resolved absolute target path is inside the intended workspace or explicitly named target directory.
- If deletion fails on Windows, assume a file lock or permission issue first. Check for running Python, Node, test, dev-server, editor, security software, or indexing processes that may be holding the file, then retry after the handle is released.
- After deletion, verify the result with `rg --files`, `Get-ChildItem`, or `git status`.
