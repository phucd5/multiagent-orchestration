<cb_env_guidelines>
Container Name: <container_name_param>
Repository Path: /testbed

## Running Commands
When you run commands inside the running container for the repo, you must use a login shell to ensure the correct testbed environment is activated:
docker exec <container_name_param> bash -lc [command]

Only simple file operations like ls or cat may skip the login shell. Everything else must use the pattern above.

For example:
- docker exec <container_name_param> ls -la /testbed
- docker exec <container_name_param> cat /testbed/path/to/file.py
- docker exec <container_name_param> bash -lc "python -V"
- docker exec <container_name_param> bash -lc "cd /workspace && pytest -q"
- docker exec <container_name_param> bash -lc "cd /workspace && git apply fix.diff"

## IMPORTANT TESTING NOTES:
- For Django repositories, use: docker exec <container> bash -lc "cd /workspace && python tests/runtests.py [test_path]"
- For other Python repos, try: docker exec <container> bash -lc "cd /workspace && python -m pytest [test_path]"

## Important Tips:
- Prefer targeted or scoped searches (grep, find, etc.) instead of scanning the entire repository. 
- Before running a broad grep, reason about which directories or files are likely relevant and search only there.
- If a pattern exists in many files, limit the initial results and refine your search iteratively.

## FORBIDDEN (DO NOT VIOLATE AT ALL):
- You SHOULD NEVER Read or Write or execute any BASH command in any parent directory of <output_dir_param>. 
- You may only read or write in <output_dir_param> and its subdirectories.
- DO NOT modify or delete any test files. All existing tests must remain unchanged.
- DO NOT install software in the system (apt, apk, brew, conda, curl scripts, pip)
- DO NOT USE PIP OR INSTALL NEW PACKAGES.
    - All problems are solvable under the current packages.
- Do NOT USE any git commands. Besides git diff to generate the patch file, you should not use any other git commands.
- You CAN NOT use your original "Read" and "Write" tools to read or write files in the codebase.
- Only use "Read" and "Write" when generating the patch file, not for interacting with the codebase.
- All commands must be run inside the Docker container using docker exec to interact with the codebase.
- Your fix must be applied only by editing existing files in the codebase. You can use the provided tools to edit existing files, but you must NOT create new files, except for the final .diff patch file.
- Avoid formatting-only changes. Only make changes needed to fix the failing test(s).
- Do NOT silence errors or hide failures. Fix the root cause of the bug.
- Do NOT disable code or wrap logic in temporary guards like if False or try/except pass.



## HARD LIMITATION
Your interaction limit is <max_turn> turns. Exceeding that limit ends the session immediately, and the repository as it exists at that moment will be treated as your final output (even if you have not generated a patch).

## CRITICAL [PAY ATTENTION]: Generating the Patch File

Generate the patch using `git diff` from the /testbed directory:
```bash
cd /testbed
git diff > /path/to/output/<output_file_name_param>
```

**FORBIDDEN [DO NOT VIOLATE AT ALL]:**
- Create backup files (.bak, .backup, .orig)
- Use the `diff` command (use `git diff` instead)
- Include timestamps in patch headers
- Reference any backup files in the patch

**Correct patch format (must have `a/` and `b/` prefixes):**
```
diff --git a/path/to/file.py b/path/to/file.py
index abc1234..def5678 100644
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -line,count +line,count @@
 context line
-removed line
+added line
```

**WRONG format (will fail to apply):**
```
--- path/to/file.py.bak
+++ path/to/file.py
```

</cb_env_guidelines>