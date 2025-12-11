<output_directory_inst>
Your file should be created in:
<output_dir_param>

Only put the final patch file in this directory. The user will provide you with the name of the file, and the extension will always be .diff.

You must not create files anywhere else. The patch file must be the only new file you create.

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

</output_directory_inst>

<task_inst>
Given a PR description, you need to implement the necessary changes to meet and solve the requirements in the PR.
Modify the regular source code files in /testbed to implement a fix for the issue described in the PR description.

## Output
The final output must be a unified diff patch applying your fix. Name the patch file:
<output_file_name_param>

Complete the task in the most efficient way possible. Do not waste time on unnecessary commands.
Read and interpret the task and hints to help you fix the problem.
- Treat the hints as authoritative maintainer guidance for the intended fix.
- Never ignore or contradict the hints_text.
- STOP and generate the patch file when you have fixed the problem.
- Modify the regular source code files in /testbed
</task_inst>
