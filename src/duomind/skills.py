"""Skill registry: task-specific instructions injected into the prompt.

The steering skill (``duomind.skill``) tells a small LLM *how* to behave. A
skill tells it *what workflow to follow* for a specific kind of task. Jev picks
the best-matching skill for each request; when Jev is off or low-confidence, a
local keyword matcher falls back.

Skills solve the "the model says it can't do this" problem: instead of relying
on a 3B model to improvise a multi-step plan (fetch a URL, scaffold files, run
git), we hand it the exact step-by-step workflow it should follow.
"""

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class Skill:
    """A named task workflow injected into the system prompt."""

    name: str
    description: str
    trigger_words: List[str]
    instructions: str


SKILL_REGISTRY: Dict[str, Skill] = {
    "webdev": Skill(
        name="webdev",
        description=(
            "Build a website or web project, including recreating a site to "
            "match a URL the user provides."
        ),
        trigger_words=[
            "website", "web site", "webpage", "web page", "landing page",
            "homepage", "html", "css", "javascript", "typescript", "react",
            "vue", "frontend", "front-end", "front end", "look like",
            "looks like", "make it look", "recreate", "clone the", "clone this",
            "rebuild", "redesign", "mockup", "design a site",
        ],
        instructions=(
            "You are building a website or web project. Follow this workflow exactly:\n"
            "1. If the user gave a URL and wants the site to LOOK like it, first fetch "
            "that URL with your web-fetch tool and study its HTML, layout, colors, "
            "fonts, and sections. Do not skip this step and do not answer from memory.\n"
            "2. Plan the file structure before writing code (for example index.html, "
            "styles.css, script.js, README.md).\n"
            "3. Create every file with your file-creation tool, one file at a time. "
            "Write complete, runnable code, never stubs or TODO comments.\n"
            "4. Recreate the design you saw: same layout, sections, color scheme, and "
            "typography, but use your own original text.\n"
            "5. When finished, tell the user exactly how to open or run it.\n"
            "You have a web-fetch tool and file tools. Never say you cannot access the "
            "web or cannot build the site. Use your tools."
        ),
    ),
    "coding": Skill(
        name="coding",
        description=(
            "Write, implement, or refactor code for a specific feature or task."
        ),
        trigger_words=[
            "code", "implement", "function", "class", "script", "program",
            "api", "endpoint", "algorithm", "feature", "refactor", "library",
            "module", "add a", "write a", "create a", "build a",
        ],
        instructions=(
            "You are writing code. Follow this workflow exactly:\n"
            "1. State a short plan: which files you will create or edit and why.\n"
            "2. Write complete, correct, runnable code with your file tools. Include "
            "imports, error handling, and a usage example.\n"
            "3. Use the language and style the user asked for; otherwise pick the "
            "simplest sensible one.\n"
            "4. If the user points at existing code, read it first before editing.\n"
            "5. After writing, explain how to run or test it.\n"
            "Never leave stubs or placeholders. Output real, working code."
        ),
    ),
    "debug": Skill(
        name="debug",
        description=(
            "Fix bugs, errors, exceptions, failing tests, or broken behavior."
        ),
        trigger_words=[
            "bug", "error", "exception", "fix", "broken", "not working",
            "crash", "failing", "failure", "traceback", "stack trace",
            "why does", "doesn't work", "does not work", "debug", "wrong output",
            "issue", "problem with", "can't get", "cant get",
        ],
        instructions=(
            "You are debugging. Follow this workflow exactly:\n"
            "1. If the user pasted an error or traceback, read it line by line and "
            "identify the exact file, line, and cause.\n"
            "2. If the code lives in a file, read the file first. Reason about what "
            "actually happens at runtime.\n"
            "3. Explain the root cause in one or two sentences, then give the corrected "
            "code.\n"
            "4. Apply the fix with your file tools when a file is involved.\n"
            "5. Explain why the fix works and how to verify it.\n"
            "Focus on the root cause, not the symptoms. Give the exact corrected code, "
            "not just advice."
        ),
    ),
    "git": Skill(
        name="git",
        description=(
            "Git version control: status, diff, commit, pull, push, branch, merge."
        ),
        trigger_words=[
            "git", "commit", "push", "pull", "branch", "merge", "clone",
            "checkout", "rebase", "repo", "repository", "github", "gitlab",
            "stash", "pull request", "version control",
        ],
        instructions=(
            "You are doing Git operations. Follow this workflow exactly:\n"
            "1. Inspect first: run git status and git log --oneline -10 with your "
            "command tool and read the output.\n"
            "2. Run one Git command at a time and read its output before the next step.\n"
            "3. For commits: stage only the intended files, write a clear message, and "
            "never commit secrets.\n"
            "4. Pull before push. If a conflict appears, explain it instead of "
            "force-resolving.\n"
            "5. Report exactly what changed after each operation.\n"
            "Do not invent a repository state. Always inspect with git before acting."
        ),
    ),
    "webfetch": Skill(
        name="webfetch",
        description=(
            "Fetch, read, and answer questions about content at a URL or web page."
        ),
        trigger_words=[
            "fetch", "read the", "summarize this", "summarize the",
            "look up", "lookup", "check this link", "check the", "what does this",
            "what's at", "what is at", "http://", "https://", "url", "web page",
        ],
        instructions=(
            "You need web content. Follow this workflow exactly:\n"
            "1. Fetch the URL with your web-fetch tool. Do not answer from memory or "
            "guess what the page says.\n"
            "2. Read the returned content, then answer based only on what the page "
            "actually contains.\n"
            "3. If the page could not be fetched, say exactly what failed and ask for "
            "the correct URL.\n"
            "You have a web-fetch tool. Never claim you cannot access the web. Use it."
        ),
    ),
    "general": Skill(
        name="general",
        description="Default: answer directly without a specialized workflow.",
        trigger_words=[],
        instructions="",
    ),
}

# Priority order for the local fallback matcher. Skills earlier in this list win
# ties, so "website + url" resolves to webdev before webfetch.
_SKILL_PRIORITY = ["webdev", "coding", "debug", "git", "webfetch", "general"]


def get_skill(name: str) -> Skill:
    """Return a skill by name, falling back to the general skill."""
    return SKILL_REGISTRY.get(name, SKILL_REGISTRY["general"])


def get_skill_instructions(name: str) -> str:
    """Return the instructions for a skill, or an empty string if none."""
    return get_skill(name).instructions


def list_skill_names() -> List[str]:
    """Return the names of all skills in priority order."""
    return list(_SKILL_PRIORITY)


def select_skill(state: Dict[str, Any]) -> str:
    """Pick the best-matching skill using local keyword matching.

    This is the fallback when Jev is disabled, unreachable, or low-confidence.
    Each skill scores one point per trigger word found in the prompt; the
    highest-scoring skill wins, with priority order breaking ties. This way a
    specific signal like "bug" outweighs a generic one like "script".
    """
    prompt = str(state.get("prompt", "")).lower()
    if not prompt:
        return "general"

    best_name = "general"
    best_score = 0
    for name in _SKILL_PRIORITY:
        skill = SKILL_REGISTRY[name]
        score = sum(1 for word in skill.trigger_words if word in prompt)
        if score > best_score:
            best_name = name
            best_score = score

    return best_name
