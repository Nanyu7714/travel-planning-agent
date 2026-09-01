# Project Instructions

These instructions apply to the entire repository.

## Project

- Default repository URL: `https://github.com/Nanyu7714/travel-planning-agent.git`
- Treat this URL as project context only. Do not change Git remotes, clone, fetch, pull, push, or publish unless the user explicitly requests it.

## Communication

- Reply in Chinese by default.
- Keep code, commands, variable names, and file paths in English.
- Lead with the conclusion. Keep answers concise and direct.
- Do not flatter the user, praise the question, or begin with generic agreement.
- Give an honest technical judgment. Point out unsafe or unsuitable approaches and explain a better option plainly.
- Assume the user is a complete beginner. Do not assume prior technical knowledge.
- Explain one technical concept at a time. Start with a simple everyday analogy, then explain the necessary details.
- Define technical terms when first used.
- When teaching interactively, finish one concept and ask `明白了吗？` before moving to the next concept.
- Do not expose hidden chain-of-thought. Provide conclusions, short reasoning summaries, checks, and evidence in Chinese.

## Git

- Do not run `git commit` or `git push` unless the user explicitly requests it.
- Before a commit, show a concise summary of the exact changes that would be committed.
- Use a short English commit message.
- Preserve unrelated user changes and untracked files.

## Actions Requiring Confirmation

Always ask the user before:

- Deleting files, directories, data, or Git history.
- Modifying `.env` files, secrets, tokens, certificates, or CI/CD configuration.
- Running `git push`, `git rebase`, `git reset --hard`, force-push, or equivalent history-changing operations.
- Publishing packages or deploying to production.

## Task Completion Documentation

- After every completed code, configuration, documentation, or verification task, update project documentation before the final response. Ordinary questions and read-only explanations do not require a log entry.
- Inspect the current conversation, `git status`, and relevant diffs before writing the record.
- Append the task record to `docs/开发记录.md`. Also update the development document for architecture decisions, the style document for UI decisions, or `README.md` for project status and verified setup commands when those documents are directly affected.
- Record only facts supported by the completed work. Do not claim unfinished work is complete and do not invent command results.
- Include the date, task name, completed items, important decisions, verification performed, and known remaining work when relevant.
- When the user says `今日任务完成` or an unambiguous equivalent, additionally audit the conversation and worktree for any completed work that was not recorded earlier that day.
- Do not commit or push documentation updates unless the user explicitly requests it.
