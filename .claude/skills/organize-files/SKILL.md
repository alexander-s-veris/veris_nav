---
name: organize-files
description: Safely move, rename, and organize files and folders with verification
---

# Safe File Organization

Follow these rules strictly when moving, renaming, or organizing files.

## Path Rules
- Always use **forward slashes** in bash: `C:/Users/...` — NEVER backslashes
- Wrap paths with spaces in double quotes: `"path/with spaces/file.txt"`
- Use absolute paths to avoid ambiguity

## Before Moving
1. Run `ls` on the source to confirm the file exists
2. Run `ls` on the destination directory to confirm it exists
3. If destination directory doesn't exist, create it with `mkdir -p`
4. Check `git status` to know which files are tracked (recoverable) vs untracked (not recoverable if lost)

## Moving Files
- Move one file per `mv` command — do NOT chain multiple `mv` commands with `&&`
- Use `mv -v` for verbose output so the operation is logged
- For files with spaces: `mv -v "source/file name.pdf" "dest/"`

## After Moving
- Run `ls` on the destination to verify the file arrived
- Run `ls` on the source to verify it's gone
- If something went wrong and the file was git-tracked, restore with `git restore <path>`

## Creating Folders
- Use `mkdir -p` to create nested directories safely
- Name folders generically so they can be reused (e.g. `reference/` not `pdfs-from-march/`)

## Never Do
- Never use backslash paths in bash
- Never chain mv commands with `&&` — if the first fails, the second may create garbage
- Never move files without verifying source exists first
- Never assume a move worked — always check
