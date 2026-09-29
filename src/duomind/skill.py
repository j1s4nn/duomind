"""Default steering skill injected into every request.

This is the "System 0" prompt that makes any local LLM cooperate with Jev's
classification output. It is model-agnostic: small models that cannot reason
about Jev's raw scores still obey these concrete, imperative rules in
milliseconds because they are plain instructions, not data to interpret.
"""

DEFAULT_SYSTEM_PROMPT = """You are DuoMind, a local AI assistant whose output is steered by a classification engine. Follow these rules exactly:

1. Match length to intent. Greetings, yes/no questions, and simple requests get ONE short sentence. Elaborate only when the user asks for explanation, analysis, code, or detail.
2. Use plain text by default. Use markdown, lists, or code blocks only when the user asks for code, files, or structured output.
3. If tools are listed in the prompt, and the task requires creating files, folders, projects, or fetching the web, reply ONLY with a tool call in the exact format shown. Never write prose where a tool call is required.
4. Never claim you cannot do something that the tools listed in the prompt allow.
5. Answer directly. No disclaimers, no apologies, no filler, no "As an AI...".

If you see a steering directive in the prompt, treat it as a hard constraint and obey it immediately."""


def build_steering_directive(
    verbosity: str = "normal",
    response_format: str = "plain_text",
    use_tool: bool = False,
) -> str:
    """Build a short, imperative steering directive from Jev's PRE decisions.

    The returned string is injected into the prompt so the LLM does not need
    to interpret Jev's raw scores itself.
    """
    length_map = {
        "brief": "Keep your response to 1-2 short sentences.",
        "normal": "Keep your response concise and to the point.",
        "detailed": "Provide a thorough, detailed answer.",
    }
    format_map = {
        "plain_text": "Respond in plain text only.",
        "markdown": "Use markdown formatting in your response.",
        "code": "Output code only, inside code blocks where appropriate.",
        "json": "Respond with valid JSON only.",
        "list": "Respond as a bulleted list.",
    }

    parts = [length_map.get(verbosity, length_map["normal"])]
    parts.append(format_map.get(response_format, format_map["plain_text"]))
    if use_tool:
        parts.append(
            "This request requires a tool. Reply ONLY with a tool call in the exact "
            "format shown above."
        )

    return " ".join(parts)
